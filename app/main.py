import asyncio
import copy
import hashlib
import hmac
import logging
import os
import secrets
import tempfile
import threading
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote, urlsplit

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config, media
from .db import Asset, Audit, Job, ModelConfig, Project, Segment, SessionLocal, SessionToken, Setting, User, get_db
from .schemas import AnalysisPlan, AudioOptionsInput, LoginInput, ModelInput, PlanInput, ProjectInput, SegmentRepairInput, SetupInput, StorageInput, UserInput, UserPatch
from .security import admin_user, current_user, encrypt, hash_password, local_secret, token_hash, verify_password
from .storage import add_asset, asset_json, storage_settings

log = logging.getLogger("uvicorn.error")
mutation_lock = threading.RLock()
login_attempts = defaultdict(deque)

def migrate():
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(config.ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(config.ROOT / "migrations"))
    command.upgrade(cfg, "head")

@asynccontextmanager
async def lifespan(app):
    from filelock import FileLock
    # The embedded durable worker deliberately runs as a single process.
    lock = FileLock(str(config.DATA_DIR / "server.lock"))
    lock.acquire(timeout=0)
    try:
        migrate()
        from .pipeline import Worker
        with SessionLocal() as db:
            if not db.scalar(select(func.count()).select_from(User)):
                token = local_secret("setup.token", lambda: secrets.token_urlsafe(24))
                log.warning("首次管理员初始化口令（仅本机保存）：%s", token)
        worker = Worker()
        app.state.worker = worker
        if os.environ.get("VIO_DISABLE_WORKER") != "1":
            worker.start()
        yield
        worker.stop()
    finally:
        lock.release()

app = FastAPI(title="VideoImageOperation", lifespan=lifespan, docs_url=None, redoc_url=None)

@app.middleware("http")
async def headers_and_origin(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and urlsplit(origin).netloc != request.headers.get("host"):
            return JSONResponse({"detail": "不允许跨站请求"}, status_code=403)
        try:
            if int(request.headers.get("content-length", "0")) > config.MAX_UPLOAD + 1024 * 1024:
                return JSONResponse({"detail": "上传超过服务器文件大小限制"}, status_code=413)
        except ValueError:
            return JSONResponse({"detail": "无效 Content-Length"}, status_code=400)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "no-store"
    elif request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response

def audit(db, user, action, target=""):
    db.add(Audit(user_id=user.id, action=action, target=target))

def user_json(user):
    return {"id": user.id, "username": user.username, "role": user.role, "active": user.active}

def model_json(model, admin=False):
    data = {k: getattr(model, k) for k in ["id", "name", "kind", "protocol", "model_id", "enabled", "max_duration", "price_per_second"]}
    if admin:
        data.update(base_url=model.base_url, api_key_set=bool(model.api_key_cipher))
    return data

def owned_project(db, project_id, user):
    project = db.get(Project, project_id)
    if not project or (project.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "项目不存在")
    return project

def project_json(db, project, detail=False):
    result = {k: getattr(project, k) for k in ["id", "name", "product_description", "status", "options", "created_at", "error", "output_asset_id", "vision_model_id", "video_model_id", "image_model_id", "transcription_model_id"]}
    if detail:
        result["analysis"] = project.analysis
        result["assets"] = [asset_json(a) for a in db.scalars(select(Asset).where(Asset.project_id == project.id).order_by(Asset.created_at))]
        result["jobs"] = [{k: getattr(j, k) for k in ["id", "action", "status", "progress", "message", "error", "created_at"]} for j in db.scalars(select(Job).where(Job.project_id == project.id).order_by(Job.created_at))]
        result["segments"] = [{k: getattr(s, k) for k in ["id", "index", "status", "remote_id", "asset_id", "error", "quality", "history", "attempts"]} for s in db.scalars(select(Segment).where(Segment.project_id == project.id).order_by(Segment.index))]
    return result

def check_model(db, model_id, kind):
    model = db.get(ModelConfig, model_id) if model_id else None
    if not model or not model.enabled or model.kind != kind:
        raise HTTPException(422, f"请选择已启用的 {kind} 模型")
    return model

@app.get("/api/bootstrap")
def bootstrap_state(db: Session = Depends(get_db)):
    return {"initialized": bool(db.scalar(select(func.count()).select_from(User)))}

@app.post("/api/bootstrap", status_code=201)
def bootstrap(body: SetupInput, db: Session = Depends(get_db)):
    with mutation_lock:
        if db.scalar(select(func.count()).select_from(User)):
            raise HTTPException(409, "已完成初始化；新用户只能由管理员创建")
        if not hmac.compare_digest(body.setup_token, local_secret("setup.token", lambda: secrets.token_urlsafe(24))):
            raise HTTPException(403, "初始化口令不正确，请查看服务启动窗口或 data/setup.token")
        user = User(username=body.username.lower(), password_hash=hash_password(body.password), role="admin")
        db.add(user)
        db.flush()
        audit(db, user, "bootstrap")
        db.commit()
        (config.DATA_DIR / "setup.token").unlink(missing_ok=True)
        return user_json(user)

@app.post("/api/auth/login")
def login(body: LoginInput, request: Request, response: Response, db: Session = Depends(get_db)):
    key = request.client.host if request.client else "local"
    now = time.time()
    with mutation_lock:
        attempts = login_attempts[key]
        while attempts and attempts[0] < now - 300:
            attempts.popleft()
        if len(attempts) >= 15:
            raise HTTPException(429, "登录尝试过多，请 5 分钟后再试")
        attempts.append(now)
    user = db.scalar(select(User).where(User.username == body.username.lower()))
    if not user or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "用户名或密码不正确")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db.execute(delete(SessionToken).where(SessionToken.expires_at < now))
    db.add(SessionToken(token_hash=token_hash(token), user_id=user.id, csrf=csrf, expires_at=now + config.SESSION_SECONDS))
    audit(db, user, "login")
    db.commit()
    response.set_cookie("vio_session", token, max_age=config.SESSION_SECONDS, httponly=True, samesite="strict", secure=config.SECURE_COOKIE)
    return {"user": user_json(user), "csrf_token": csrf}

@app.get("/api/auth/me")
def me(request: Request, user: User = Depends(current_user)):
    return {"user": user_json(user), "csrf_token": request.state.session.csrf}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.delete(request.state.session)
    db.commit()
    response.delete_cookie("vio_session")
    return {"ok": True}

@app.get("/api/health")
def health(user: User = Depends(current_user)):
    try:
        media.ffmpeg_path()
        ok = True
    except Exception:
        ok = False
    return {"ffmpeg": ok, "database": "SQLite" if config.DATABASE_URL.startswith("sqlite") else "SQL", "version": "0.1.0"}

@app.get("/api/users")
def users(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return [user_json(u) for u in db.scalars(select(User).order_by(User.created_at))]

@app.post("/api/users", status_code=201)
def create_user(body: UserInput, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    new = User(username=body.username.lower(), password_hash=hash_password(body.password), role=body.role)
    db.add(new)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "用户名已存在")
    audit(db, user, "create_user", new.id)
    db.commit()
    return user_json(new)

@app.patch("/api/users/{user_id}")
def update_user(user_id: str, body: UserPatch, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    with mutation_lock:
        target = db.get(User, user_id)
        if not target:
            raise HTTPException(404, "用户不存在")
        if target.id == user.id and (body.active is False or body.role == "user"):
            raise HTTPException(422, "不能停用或降低当前管理员自身权限")
        for field in ["active", "role"]:
            value = getattr(body, field)
            if value is not None:
                setattr(target, field, value)
        if body.password:
            target.password_hash = hash_password(body.password)
        db.execute(delete(SessionToken).where(SessionToken.user_id == target.id))
        audit(db, user, "update_user", target.id)
        db.commit()
        return user_json(target)

@app.get("/api/models")
def models(user: User = Depends(current_user), db: Session = Depends(get_db)):
    query = select(ModelConfig)
    if user.role != "admin":
        query = query.where(ModelConfig.enabled.is_(True))
    return [model_json(m, user.role == "admin") for m in db.scalars(query)]

def save_model(db, model, body, user):
    for key, value in body.model_dump(exclude={"api_key"}).items():
        setattr(model, key, value)
    if body.api_key:
        model.api_key_cipher = encrypt(body.api_key)
    if not model.api_key_cipher:
        raise HTTPException(422, "请填写 API Key")
    db.add(model)
    db.flush()
    audit(db, user, "save_model", model.id)
    db.commit()
    return model_json(model, True)

@app.post("/api/models", status_code=201)
def create_model(body: ModelInput, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return save_model(db, ModelConfig(), body, user)

@app.put("/api/models/{model_id}")
def update_model(model_id: str, body: ModelInput, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    model = db.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")
    if db.scalar(select(Job.id).join(Project, Project.id == Job.project_id).where(Job.status.in_(["queued", "running"]),
        (Project.video_model_id == model_id) | (Project.vision_model_id == model_id) | (Project.image_model_id == model_id) | (Project.transcription_model_id == model_id))):
        raise HTTPException(409, "该模型有任务正在使用，完成或取消后再修改")
    # A recorded remote task must always be polled against the original endpoint/model.
    if (model.base_url != body.base_url or model.model_id != body.model_id or model.protocol != body.protocol or model.kind != body.kind) and db.scalar(select(Project.id).where((Project.video_model_id == model_id) | (Project.vision_model_id == model_id) | (Project.image_model_id == model_id) | (Project.transcription_model_id == model_id))):
        raise HTTPException(409, "模型已被项目引用，修改协议、地址、用途或模型 ID 请新增配置")
    return save_model(db, model, body, user)

@app.delete("/api/models/{model_id}")
def disable_model(model_id: str, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    model = db.get(ModelConfig, model_id)
    if not model:
        raise HTTPException(404, "模型不存在")
    model.enabled = False
    audit(db, user, "disable_model", model.id)
    db.commit()
    return {"ok": True}

@app.get("/api/settings/storage")
def read_storage(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    row = db.get(Setting, "storage")
    value = dict(row.value) if row else StorageInput().model_dump(exclude={"secret_access_key"})
    value["secret_set"] = bool(value.pop("secret_cipher", ""))
    return value

@app.put("/api/settings/storage")
def save_storage(body: StorageInput, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    row = db.get(Setting, "storage") or Setting(key="storage", value={})
    value = body.model_dump(exclude={"secret_access_key"})
    value["secret_cipher"] = encrypt(body.secret_access_key) if body.secret_access_key else row.value.get("secret_cipher", "")
    if body.enabled and not value["secret_cipher"]:
        raise HTTPException(422, "请填写 TOS Secret Access Key")
    row.value = value
    db.add(row)
    audit(db, user, "save_storage")
    db.commit()
    return read_storage(user, db)

@app.get("/api/projects")
def projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    # Even administrators see their own dashboard; explicit detail access is allowed for support.
    return [project_json(db, p) for p in db.scalars(select(Project).where(Project.owner_id == user.id).order_by(Project.created_at.desc()).limit(200))]

@app.post("/api/projects", status_code=201)
def create_project(body: ProjectInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    for field, kind in [("vision_model_id", "vision"), ("video_model_id", "video"), ("image_model_id", "image"), ("transcription_model_id", "transcription")]:
        if getattr(body, field):
            check_model(db, getattr(body, field), kind)
    project = Project(owner_id=user.id, **body.model_dump())
    db.add(project)
    db.flush()
    audit(db, user, "create_project", project.id)
    db.commit()
    return project_json(db, project, True)

@app.get("/api/projects/{project_id}")
def project_detail(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return project_json(db, owned_project(db, project_id, user), True)

@app.post("/api/projects/{project_id}/assets", status_code=201)
def upload_asset(project_id: str, role: str = Form(...), file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project = owned_project(db, project_id, user)
        if role not in {"reference", "product"}:
            raise HTTPException(422, "不支持的素材类型")
        allowed = project.status == "draft" or (role == "product" and project.status in {"ready", "failed", "needs_attention"})
        if not allowed or db.scalar(select(Segment.id).where(Segment.project_id == project.id)):
            raise HTTPException(409, "仅视频生成前可补充产品图；更换参考视频请新建项目")
        if db.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(["queued", "running"]))):
            raise HTTPException(409, "请等待当前任务结束后再补充素材")
        existing = db.scalar(select(func.count()).select_from(Asset).where(Asset.project_id == project.id, Asset.role == role))
        if existing >= (1 if role == "reference" else 8):
            raise HTTPException(422, "最多 1 个参考视频、8 张产品图")
        data = file.file.read(config.MAX_UPLOAD + 1)
        if not data or len(data) > config.MAX_UPLOAD:
            raise HTTPException(413, "文件为空或超过上传限制")
        suffix = Path(file.filename or "").suffix.lower()
        try:
            if role == "product":
                _, meta = media.normalize_image(data)
                from PIL import Image
                import io
                with Image.open(io.BytesIO(data)) as img:
                    mime = Image.MIME.get(img.format, "image/jpeg")
                if mime not in {"image/jpeg", "image/png", "image/webp"}:
                    raise ValueError("产品图请使用 JPEG、PNG 或 WebP")
            else:
                if suffix not in {".mp4", ".mov", ".webm", ".mkv"}:
                    raise ValueError("参考视频支持 MP4、MOV、WebM、MKV")
                with tempfile.TemporaryDirectory(prefix="vio-probe-") as tmp:
                    path = Path(tmp) / ("reference" + suffix)
                    path.write_bytes(data)
                    meta = media.probe(path)
                if not meta["width"] or not meta["height"]:
                    raise ValueError("文件没有有效视频画面")
                if not 2 <= meta["duration"] <= 300:
                    raise ValueError("第一版参考视频长度支持 2–300 秒")
                mime = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska"}[suffix]
            asset = add_asset(db, project, data, file.filename or "upload", mime, role, meta)
        except Exception as exc:
            raise HTTPException(422, str(exc)[:500])
        if role == "product":
            # Recompute derived images using all original uploads on the next analysis.
            db.execute(delete(Asset).where(Asset.project_id == project.id, Asset.role.in_(["normalized_product", "optimized_product"])))
            project.analysis, project.status, project.error = None, "draft", None
        audit(db, user, "upload_" + role, project.id)
        db.commit()
        return asset_json(asset)

def queue_job(db, project, action, user, *, commit=True):
    if db.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(["queued", "running"]))):
        raise HTTPException(409, "项目已有运行中的任务")
    active_count = db.scalar(select(func.count()).select_from(Job).join(Project).where(Project.owner_id == user.id, Job.status.in_(["queued", "running"])))
    if active_count >= 5:
        raise HTTPException(429, "每位用户最多同时排队 5 个任务")
    if action == "analyze":
        roles = set(db.scalars(select(Asset.role).where(Asset.project_id == project.id)))
        if not {"reference", "product"}.issubset(roles):
            raise HTTPException(422, "请先上传参考视频和至少 1 张产品图")
        check_model(db, project.vision_model_id, "vision")
    elif action == "review":
        check_model(db, project.vision_model_id, "vision")
        planned = (project.analysis or {}).get("segments", [])
        records = list(db.scalars(select(Segment).where(Segment.project_id == project.id)))
        if not planned or len(records) != len(planned) or any(not record.asset_id for record in records):
            raise HTTPException(422, "请先完成全部视频片段的生成，再进行一致性检查")
        if {record.index for record in records} != {segment.get("index") for segment in planned}:
            raise HTTPException(422, "视频片段与分镜不对应，无法检查")
    else:
        check_model(db, project.video_model_id, "video")
        check_model(db, project.vision_model_id, "vision")
        if not project.analysis:
            raise HTTPException(422, "请先完成分镜分析")
        try:
            plan = AnalysisPlan.model_validate(project.analysis)
        except ValueError:
            raise HTTPException(422, "分镜数据无效，请检查后重新保存")
        completed_indices = set(db.scalars(select(Segment.index).where(Segment.project_id == project.id, Segment.asset_id.is_not(None))))
        pending = [segment for segment in plan.segments if segment.index not in completed_indices]
        if any(segment.strategy == "needs_reference" for segment in pending):
            raise HTTPException(422, "部分镜头缺少产品素材，请先补图并重新分析，或明确改编策略后再生成")
        if any(segment.strategy == "keyframe" for segment in pending):
            check_model(db, project.image_model_id, "image")
        try:
            storage_settings(db)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        if db.scalar(select(Segment.id).where(Segment.project_id == project.id, Segment.status == "submitting", Segment.remote_id.is_(None))):
            raise HTTPException(409, "有片段提交结果未知，请在供应商控制台核对任务 ID，再用管理接口关联；避免重复扣费")
    project.status, project.error = {"analyze": "analyzing", "review": "reviewing", "generate": "generating"}[action], None
    job = Job(project_id=project.id, action=action)
    db.add(job)
    audit(db, user, action, project.id)
    db.flush()
    if commit:
        db.commit()
    return {"id": job.id, "status": job.status}

@app.post("/api/projects/{project_id}/analyze")
def analyze_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project = owned_project(db, project_id, user)
        if project.status not in {"draft", "ready", "failed", "needs_attention"} or db.scalar(select(Segment.id).where(Segment.project_id == project.id)):
            raise HTTPException(409, "当前项目不能重新分析")
        result = queue_job(db, project, "analyze", user, commit=False)
        project.analysis = None
        db.commit()
        return result

@app.put("/api/projects/{project_id}/plan")
def save_plan(project_id: str, body: PlanInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project = owned_project(db, project_id, user)
        if project.status not in {"ready", "failed", "needs_attention"} or db.scalar(select(Segment.id).where(Segment.project_id == project.id)):
            raise HTTPException(409, "只能在开始视频生成前编辑分镜")
        if db.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(["queued", "running"]))):
            raise HTTPException(409, "当前有排队或运行中的任务，不能编辑分镜")
        if not project.analysis:
            raise HTTPException(422, "尚无分镜")
        old_duration = sum(s["duration"] for s in project.analysis["segments"])
        if abs(sum(s.duration for s in body.analysis.segments) - old_duration) > 0.05:
            raise HTTPException(422, "编辑后总时长必须与原计划一致")
        max_duration = db.get(ModelConfig, project.video_model_id).max_duration
        if any(s.generation_duration > max_duration for s in body.analysis.segments):
            raise HTTPException(422, "分镜时长超过模型配置的上限")
        project.analysis = body.analysis.model_dump()
        project.status, project.error = "ready", None
        db.commit()
        return project_json(db, project, True)

@app.post("/api/projects/{project_id}/generate")
def generate_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project = owned_project(db, project_id, user)
        if project.status != "ready":
            raise HTTPException(409, "请先完成并检查分镜")
        return queue_job(db, project, "generate", user)

@app.patch("/api/projects/{project_id}/audio-options")
def update_audio_options(project_id: str, body: AudioOptionsInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project = owned_project(db, project_id, user)
        if project.status not in {"draft", "ready", "failed", "needs_attention"}:
            raise HTTPException(409, "请等待当前任务结束后再调整音频")
        if db.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(["queued", "running"]))):
            raise HTTPException(409, "当前有排队或运行中的任务，不能修改音频")
        records = list(db.scalars(select(Segment).where(Segment.project_id == project.id)))
        if any(s.asset_id or s.status not in {"pending", "failed"} for s in records):
            raise HTTPException(409, "项目已有生成结果或未确认的供应商任务，为保证各段声音一致，请新建项目调整音频")
        project.options = {**project.options, **body.model_dump()}
        audit(db, user, "update_audio_options", project.id)
        db.commit()
        return project_json(db, project, True)

@app.post("/api/projects/{project_id}/retry")
def retry_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project = owned_project(db, project_id, user)
        if project.status not in {"failed", "needs_attention"}:
            raise HTTPException(409, "该任务目前不需要重试")
        previous = db.scalar(select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc()).limit(1))
        action = "review" if previous and previous.action == "review" else ("generate" if project.analysis else "analyze")
        return queue_job(db, project, action, user)

@app.post("/api/projects/{project_id}/review")
def review_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project = owned_project(db, project_id, user)
        return queue_job(db, project, "review", user)

def repair_target(db, segment_id, user):
    segment = db.get(Segment, segment_id)
    if not segment:
        raise HTTPException(404, "片段不存在")
    project = owned_project(db, segment.project_id, user)
    if db.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(["queued", "running"]))):
        raise HTTPException(409, "请等待当前任务结束后再修改片段")
    if not project.analysis or not any(s.get("index") == segment.index for s in project.analysis.get("segments", [])):
        raise HTTPException(422, "没有找到该片段的分镜")
    return project, segment

def update_segment_strategy(db, project, segment, body):
    if body.strategy == "keyframe":
        check_model(db, project.image_model_id, "image")
    analysis = copy.deepcopy(project.analysis)
    planned = next(s for s in analysis["segments"] if s["index"] == segment.index)
    planned.update(strategy=body.strategy, repair_prompt=body.repair_prompt)
    project.analysis = analysis

@app.post("/api/segments/{segment_id}/regenerate")
def regenerate_segment(segment_id: str, body: SegmentRepairInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project, segment = repair_target(db, segment_id, user)
        records = list(db.scalars(select(Segment).where(Segment.project_id == project.id)))
        if not segment.asset_id or any(not record.asset_id for record in records) or len(records) != len(project.analysis["segments"]):
            raise HTTPException(409, "请先完成全部片段的生成，再选择局部重做")
        if segment.attempts >= 3:
            raise HTTPException(409, "该片段已达到 3 次视频提交上限，请检查素材和方案后新建项目")
        try:
            update_segment_strategy(db, project, segment, body)
            segment.history = [*(segment.history or []), {"asset_id": segment.asset_id, "remote_id": segment.remote_id,
                                                        "quality": copy.deepcopy(segment.quality or {}), "attempts": segment.attempts}]
            segment.asset_id, segment.remote_id, segment.error = None, None, None
            segment.quality, segment.status = {}, "pending"
            result = queue_job(db, project, "generate", user, commit=False)
            audit(db, user, "regenerate_segment", segment.id)
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise

@app.post("/api/segments/{segment_id}/strategy")
def save_segment_strategy(segment_id: str, body: SegmentRepairInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with mutation_lock:
        project, segment = repair_target(db, segment_id, user)
        if segment.asset_id or (segment.remote_id and segment.status != "failed") or segment.status in {"submitting", "submitted"}:
            raise HTTPException(409, "仅尚未提交视频任务的片段可修改策略；已有结果请使用局部重做")
        if segment.attempts >= 3:
            raise HTTPException(409, "该片段已达到 3 次视频提交上限")
        update_segment_strategy(db, project, segment, body)
        if segment.remote_id:
            segment.history = [*(segment.history or []), {"asset_id": None, "remote_id": segment.remote_id,
                "error": segment.error, "quality": copy.deepcopy(segment.quality or {}), "attempts": segment.attempts}]
            segment.remote_id = None
        segment.quality = {key: value for key, value in (segment.quality or {}).items() if not key.startswith("keyframe_")}
        segment.error, segment.status = None, "pending"
        project.error, project.status = None, "needs_attention"
        audit(db, user, "update_segment_strategy", segment.id)
        db.commit()
        return project_json(db, project, True)

@app.post("/api/projects/{project_id}/cancel")
def cancel_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    project = owned_project(db, project_id, user)
    for job in db.scalars(select(Job).where(Job.project_id == project.id, Job.status.in_(["queued", "running"]))):
        job.cancel_requested = True
    db.commit()
    return {"ok": True, "message": "将在当前安全检查点停止；供应商已接受的生成任务可能继续计费"}

@app.post("/api/segments/{segment_id}/resolve")
def resolve_segment(segment_id: str, body: dict, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    segment = db.get(Segment, segment_id)
    if not segment or segment.status != "submitting" or segment.remote_id:
        raise HTTPException(409, "该片段没有待核对的提交")
    remote_id = str(body.get("remote_id", "")).strip()
    if not remote_id or len(remote_id) > 200 or not all(c.isalnum() or c in "-_" for c in remote_id):
        raise HTTPException(422, "请提供供应商控制台的有效任务 ID")
    segment.remote_id, segment.status = remote_id, "submitted"
    audit(db, user, "resolve_submission", segment.id)
    db.commit()
    return {"ok": True}

@app.get("/api/assets/{asset_id}")
def get_asset(asset_id: str, request: Request, download: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    asset = db.get(Asset, asset_id)
    if not asset or (asset.owner_id != user.id and user.role != "admin"):
        raise HTTPException(404, "素材不存在")
    start, end = 0, asset.size - 1
    range_header = request.headers.get("range")
    status = 200
    headers = {"Accept-Ranges": "bytes", "Content-Disposition": f"{'attachment' if download else 'inline'}; filename*=UTF-8''{quote(asset.name, safe='')}"}
    if range_header:
        try:
            unit, value = range_header.split("=", 1)
            left, right = value.split("-", 1)
            if unit != "bytes" or "," in value or (not left and not right):
                raise ValueError()
            if not left:
                count = int(right)
                if count <= 0:
                    raise ValueError()
                start = max(0, asset.size - count)
            else:
                start = int(left)
                end = min(int(right), end) if right else end
            if start < 0 or start > end or start >= asset.size:
                raise ValueError()
        except ValueError:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{asset.size}"})
        status = 206
        headers["Content-Range"] = f"bytes {start}-{end}/{asset.size}"
    headers["Content-Length"] = str(end - start + 1)
    # Read chunks directly from the DB, rather than loading the entire video into RAM.
    def chunks():
        with SessionLocal() as stream_db:
            for offset in range(start, end + 1, 1024 * 1024):
                length = min(1024 * 1024, end - offset + 1)
                yield stream_db.scalar(select(func.substr(Asset.data, offset + 1, length)).where(Asset.id == asset_id))
    return StreamingResponse(chunks(), status_code=status, media_type=asset.mime, headers=headers)

app.mount("/static", StaticFiles(directory=config.ROOT / "app" / "static"), name="static")

@app.get("/")
def index():
    static_dir = config.ROOT / "app" / "static"
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    # A new URL bypasses previously cached scripts after an application update.
    for filename in ("app.js", "style.css"):
        version = hashlib.sha256((static_dir / filename).read_bytes()).hexdigest()[:16]
        html = html.replace(f'"/static/{filename}"', f'"/static/{filename}?v={version}"')
    return HTMLResponse(html)
