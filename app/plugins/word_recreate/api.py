"""Optional feature endpoints; identities, permissions and media stay in the host."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ... import analysis_results
from ...db import Asset, Job, Project, Segment, Setting, User, get_db
from ...security import admin_user, current_user
from . import engine
from .schemas import WordPlanInput, WordProjectInput, WordSettingsInput

router = APIRouter()
SETTING_KEY = "word_recreate"


def host():
    # Delayed import keeps the host's optional router registration acyclic.
    from ... import main
    return main


def get_word_settings(db):
    row = db.get(Setting, SETTING_KEY)
    return {"enabled": bool(row and (row.value or {}).get("enabled") is True)}


def runtime_status(db):
    return {**engine.status(), **get_word_settings(db), "engine": "hypit"}


def require_enabled(db):
    if not get_word_settings(db)["enabled"]:
        raise HTTPException(409, "词-复刻视频尚未启用，请联系管理员；历史作品仍可查看和下载")


def require_runtime():
    try:
        engine.require_ready()
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def word_project(db, project_id, user, *, enabled=True):
    project = host().owned_project(db, project_id, user)
    if (project.options or {}).get("engine") != "hypit":
        raise HTTPException(409, "该项目不属于词-复刻视频，请使用原视频复刻入口")
    if enabled:
        require_enabled(db)
    return project


def require_alignment_model(db, project):
    options = project.options or {}
    if options.get("replicate_subtitles", True) and options.get("replicate_voice", True):
        model = host().check_model(db, project.transcription_model_id, "transcription")
        if model.protocol not in {"openai", "dashscope_asr"}:
            raise HTTPException(422, "逐词字幕需要支持词级时间戳的 OpenAI 兼容或阿里云音频转写模型")
        if model.protocol == "dashscope_asr":
            from ...audio_transcription import preflight
            try:
                preflight(db, model)
            except (ValueError, RuntimeError) as exc:
                raise HTTPException(422, str(exc)) from exc


def enqueue(db, project, action, user):
    require_runtime()
    if action in {"analyze", "generate"}:
        require_alignment_model(db, project)
    if action == "review":
        output = db.get(Asset, project.output_asset_id) if project.output_asset_id else None
        if not output or output.role != "output" or output.project_id != project.id:
            raise HTTPException(422, "请先完成 Hypit 成片导出，再进行一致性复查；合成失败请重试以复用现有片段")
    result = host().queue_job(db, project, action, user, commit=False)
    db.get(Job, result["id"]).action = "word_" + action
    return result


@router.get("/api/settings/word-recreate")
def read_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return runtime_status(db)


@router.get("/api/settings/word-recreate/runtime")
def check_runtime(user: User = Depends(admin_user), db: Session = Depends(get_db)):
    return runtime_status(db)


@router.put("/api/settings/word-recreate")
def save_settings(body: WordSettingsInput, user: User = Depends(admin_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        if body.enabled:
            require_runtime()
        row = db.get(Setting, SETTING_KEY) or Setting(key=SETTING_KEY)
        row.value = {"enabled": body.enabled}
        db.add(row)
        host().audit(db, user, "save_word_recreate", "enabled" if body.enabled else "disabled")
        db.commit()
        return runtime_status(db)


@router.post("/api/word-recreate/projects", status_code=201)
def create_project(body: WordProjectInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        require_enabled(db)
        require_runtime()
        for field, kind in [("vision_model_id", "vision"), ("video_model_id", "video"), ("image_model_id", "image"), ("transcription_model_id", "transcription")]:
            if getattr(body, field):
                host().check_model(db, getattr(body, field), kind)
        project = Project(owner_id=user.id, **body.model_dump())
        require_alignment_model(db, project)
        db.add(project)
        db.flush()
        host().audit(db, user, "create_word_project", project.id)
        db.commit()
        return host().project_json(db, project, True, user=user)


@router.post("/api/word-recreate/projects/{project_id}/analyze")
def analyze_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        project = word_project(db, project_id, user)
        if project.status not in {"draft", "ready", "failed", "needs_attention"} or db.scalar(select(Segment.id).where(Segment.project_id == project.id)):
            raise HTTPException(409, "当前项目不能重新分析")
        result = enqueue(db, project, "analyze", user)
        analysis_results.invalidate_replies(db, project.id)
        project.analysis = None
        db.commit()
        return result


@router.put("/api/word-recreate/projects/{project_id}/plan")
def save_plan(project_id: str, body: WordPlanInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        project = word_project(db, project_id, user)
        if project.status not in {"ready", "failed", "needs_attention"} or db.scalar(select(Segment.id).where(Segment.project_id == project.id)):
            raise HTTPException(409, "只能在开始视频生成前编辑分镜")
        if db.scalar(select(Job.id).where(Job.project_id == project.id, Job.status.in_(["queued", "running"]))):
            raise HTTPException(409, "当前有排队或运行中的任务，不能编辑分镜")
        if not project.analysis:
            raise HTTPException(422, "尚无分镜")
        old_duration = sum(s["duration"] for s in project.analysis["segments"])
        if abs(sum(s.duration for s in body.analysis.segments) - old_duration) > 0.05:
            raise HTTPException(422, "编辑后总时长必须与原计划一致")
        model = host().check_model(db, project.video_model_id, "video")
        if any(s.generation_duration > model.max_duration for s in body.analysis.segments):
            raise HTTPException(422, "分镜时长超过模型配置的上限")
        product_count = len(list(db.scalars(select(Asset.id).where(Asset.project_id == project.id, Asset.role == "product"))))
        if any(index >= product_count for item in [*body.analysis.shots, *body.analysis.segments] for index in item.reference_image_indices):
            raise HTTPException(422, "分镜引用了不存在的产品图片，请检查参考图片编号")
        project.analysis = body.analysis.model_dump()
        project.status, project.error = "ready", None
        host().audit(db, user, "save_word_plan", project.id)
        db.commit()
        return host().project_json(db, project, True, user=user)


@router.post("/api/word-recreate/projects/{project_id}/generate")
def generate_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        project = word_project(db, project_id, user)
        if project.status != "ready":
            raise HTTPException(409, "请先完成并检查分镜")
        result = enqueue(db, project, "generate", user)
        db.commit()
        return result


@router.post("/api/word-recreate/projects/{project_id}/retry")
def retry_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        project = word_project(db, project_id, user)
        if project.status not in {"failed", "needs_attention"}:
            raise HTTPException(409, "该任务目前不需要重试")
        previous = db.scalar(select(Job).where(Job.project_id == project.id).order_by(Job.created_at.desc(), Job.id.desc()).limit(1))
        action = "review" if previous and previous.action == "word_review" else ("generate" if project.analysis else "analyze")
        result = enqueue(db, project, action, user)
        db.commit()
        return result


@router.post("/api/word-recreate/projects/{project_id}/review")
def review_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        result = enqueue(db, word_project(db, project_id, user), "review", user)
        db.commit()
        return result


@router.post("/api/word-recreate/projects/{project_id}/cancel")
def cancel_project(project_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    with host().mutation_lock:
        project = word_project(db, project_id, user, enabled=False)
        return host().cancel_project(project.id, user, db)
