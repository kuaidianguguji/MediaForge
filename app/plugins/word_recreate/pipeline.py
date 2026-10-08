"""An isolated serial worker for Hypit word-based recreation.

The native generation adapter owns paid video submissions and product QA. This
plugin owns measured final-audio alignment and the real Hypit composition step.
Disabling the plugin only blocks new API jobs; already accepted jobs drain.
"""
import hashlib
import json
import logging
import re
import shutil
import tempfile
import threading
import time
from pathlib import Path

from sqlalchemy import select

from ... import media, pipeline as native, providers
from ...config import DATA_DIR
from ...db import Asset, Job, Project, SessionLocal
from ...schemas import AnalysisPlan
from ...storage import add_asset
from . import engine, transcription

log = logging.getLogger("uvicorn.error")
WORD_ACTIONS = ("word_analyze", "word_generate", "word_review")
RENDER_ROOT = DATA_DIR / "word-work"


def _word_project(project):
    if not project or project.options.get("engine") != "hypit":
        raise ValueError("该任务不是词-复刻视频项目。")


def _words_model(db, project):
    if not project.transcription_model_id:
        raise ValueError("请为词-复刻视频选择支持逐词时间戳的语音转写模型。")
    model = native.model_for(db, project.transcription_model_id, "transcription")
    transcription.compatible(model)
    if model.protocol == "dashscope_asr":
        from ...audio_transcription import preflight
        preflight(db, model)
    else:
        providers._endpoint(model, "audio/transcriptions")
        providers._headers(model)
    return model


def analyze_project(db, project, job, work, stop_event):
    _word_project(project)
    native.checkpoint(db, job, "检查词-复刻视频引擎与转写配置", 2, stop_event)
    engine.preflight()
    requires_words = project.options.get("replicate_voice") and project.options.get("replicate_subtitles")
    word_model = _words_model(db, project) if requires_words else None
    references = native.assets_for(db, project.id, "reference")
    if not references:
        raise ValueError("请先上传参考视频。")
    reference_words_verified = False

    def reference_transcription(model, audio):
        nonlocal reference_words_verified
        raw, _ = transcription.durable_transcribe(db, project, job, model, audio,
            source_key=references[0].sha256, purpose="reference", language=None,
            checkpoint=lambda: native.checkpoint(db, job, stop_event=stop_event))
        text = transcription.response_text(raw)
        if requires_words and text:
            transcription.measured_words(raw, media.probe(audio)["duration"])
            reference_words_verified = True
        return text

    # Confirm the configured gateway's measured-word capability on the source
    # transcript before spending on visual analysis or video generation. Do this
    # even when native visual analysis has a cache, so older text-only receipts
    # cannot bypass the new preflight. Silent source clips cannot prove speech
    # timestamp capability; state that explicitly instead of inventing times.
    if requires_words:
        source = work / ("word-reference" + Path(references[0].name).suffix.lower())
        source.write_bytes(references[0].data)
        if media.probe(source).get("has_audio"):
            audio = media.extract_audio(source, work / "word-reference-audio.mp3")
            reference_transcription(word_model, audio)

    native.analyze_project(db, project, job, work, stop_event,
                           transcription_handler=reference_transcription)
    # Replace only the native engine's own subtitle warning. Product, speech and
    # other risks remain exactly as recorded by analysis and quality adapters.
    plan = dict(project.analysis)
    risks = [item for item in plan.get("risks", [])
             if not item.startswith("字幕按分段时间叠加，尚无逐词对齐；")]
    if project.options.get("replicate_subtitles"):
        risks.append("词-复刻视频将在生成后转写实际成片音轨，并用服务商测得的逐词时间戳制作字幕；时间戳或口播不符合要求时保留片段并停止合成，不会用计划文案伪造对齐。" if project.options.get("replicate_voice")
                     else "已关闭口播：字幕按分镜时间展示，属于场景字幕，不是逐词口播对齐。")
    if requires_words and not reference_words_verified:
        risks.append("参考视频没有可识别口播，尚未验证该转写接口的逐词时间戳能力；生成后必须对实际口播验证，缺少词级结果会停止合成并保留已生成片段。")
    risks.append("Hypit 负责字幕与画面编排，产品替换质量仍取决于所选视频模型；抽帧质检不能代替完整预览。")
    plan["risks"] = risks[:99] + (["\n".join(risks[99:])] if len(risks) > 99 else [])
    plan["sampling"] = {**plan.get("sampling", {}), "composition_engine": "hypit",
                        "reference_word_timestamps_verified": reference_words_verified}
    project.analysis = AnalysisPlan.model_validate(plan).model_dump()
    db.commit()


def _render_version(project, segments, plan):
    value = {"version": 1, "clips": [row.asset_id for row in segments],
             "durations": [item.duration for item in plan.segments], "options": project.options,
             "subtitles": [item.subtitle for item in plan.segments]}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def _render_work(project_id, version):
    if not re.fullmatch(r"[a-f0-9]{32}", project_id) or not re.fullmatch(r"[a-f0-9]{64}", version):
        raise ValueError("词-复刻工作目录标识无效。")
    root = RENDER_ROOT.resolve()
    path = (root / project_id / version).resolve()
    if not path.is_relative_to(root):
        raise ValueError("词-复刻工作目录无效。")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _render_state(db, project, job, version):
    candidates = db.scalars(select(Asset).where(Asset.project_id == project.id,
                                               Asset.role == "word_render_state")
                            .order_by(Asset.created_at.desc()))
    existing = next((row for row in candidates if row.meta.get("version") == version), None)
    if existing:
        return existing
    row = add_asset(db, project, b"{}", f"word-render-{version[:16]}.json", "application/json", "word_render_state",
                    {"version": version, "state": "prepared", "job_id": job.id})
    db.commit()
    return row


def _archive_result(db, project, result, version, alignment, info):
    # Archive every usable result before changing the project output pointer.
    # If an archive fails, any prior final output remains selectable.
    meta = {"engine": "hypit", "version": version, "alignment_type": alignment["type"]}
    workflow = native.put_unique(db, project, result.workflow.read_bytes(), f"hypit-workflow-{version[:16]}.zip",
                                 "application/zip", "word_workflow", meta)
    aligned = native.put_unique(db, project, json.dumps(alignment, ensure_ascii=False).encode(),
                                f"word-alignment-{version[:16]}.json", "application/json", "word_alignment", meta)
    evidence = native.put_unique(db, project, result.evidence.read_bytes(), f"hypit-evidence-{version[:16]}.json",
                                 "application/json", "word_evidence", meta)
    return native.put_unique(db, project, result.video.read_bytes(), f"word-video-final-{version[:16]}.mp4",
                             "video/mp4", "output", {**info, **meta, "workflow_asset_id": workflow.id,
                                "alignment_asset_id": aligned.id, "evidence_asset_id": evidence.id})


def generate_project(db, project, job, work, stop_event):
    _word_project(project)
    native.checkpoint(db, job, "检查 Hypit 编排引擎，准备视频片段", 1, stop_event)
    engine.preflight()  # Always before any paid generation or ASR.
    options = project.options
    word_subtitles = options.get("replicate_subtitles") and options.get("replicate_voice")
    asr_model = _words_model(db, project) if word_subtitles else None
    generated = native.generate_project(db, project, job, work, stop_event, finalize=False)
    plan, segments, clips = generated["plan"], generated["segments"], generated["clips"]
    if word_subtitles and any(not media.probe(path).get("has_audio") for path in clips):
        raise native.NeedsAttention("生成片段缺少音轨，无法对齐实际口播。已有视频片段已保留，未用静音轨冒充口播，也未重复生成。")
    native.checkpoint(db, job, "统一画幅与音轨，准备实际口播对齐", 86, stop_event)
    version = _render_version(project, segments, plan)
    render_work = _render_work(project.id, version)
    video = media.join_clips(clips, render_work / "base.mp4", durations=[item.duration for item in plan.segments],
                             ratio=options["ratio"], resolution=options["resolution"], subtitles=None,
                             mute=not (options.get("replicate_music") or options.get("replicate_voice")))
    info = media.probe(video)
    words, cues = [], []
    alignment = {"type": "none", "words": [], "cues": [], "source": "generated_audio",
                 "duration": info["duration"], "caption_style": options.get("caption_style", "highlight")}
    speech_warning = False
    if word_subtitles:
        if not info.get("has_audio"):
            raise native.NeedsAttention("生成片段没有音轨，无法对齐实际口播。已有视频片段已保留，未重复生成。")
        native.checkpoint(db, job, "转写成片实际音轨，获取逐词时间戳", 89, stop_event)
        audio = media.extract_audio(video, render_work / "final-audio.mp3")
        raw, receipt = transcription.durable_transcribe(db, project, job, asr_model, audio,
            source_key=hashlib.sha256(audio.read_bytes()).hexdigest(), purpose="generated",
            language="pt" if options.get("site") == "BR" else None,
            checkpoint=lambda: native.checkpoint(db, job, stop_event=stop_event))
        words = transcription.measured_words(raw, info["duration"])
        if options.get("site") == "BR" and any(re.search(r"[\u4e00-\u9fff]", word["word"]) for word in words):
            raise native.NeedsAttention("实际口播转写包含中文，不符合巴西站点要求；片段与转写均已保存，请先检查音轨，未自动重新生成。")
        alignment.update(type="word", words=words, transcript=transcription.response_text(raw),
                         asr_asset_id=receipt.id, language=raw.get("language"))
        if any(word["start"] == word["end"] for word in words):
            alignment["notices"] = ["服务商返回部分零时长词；这些词随相邻字幕显示，不能单独高亮，未补造时间戳。"]
        # Generated speech is probabilistic. A real timestamp does not prove the
        # intended sales claims or language were followed, so require preview.
        speech_warning = True
    elif options.get("replicate_subtitles"):
        cues = [{"text": item.subtitle, "start": item.start, "end": item.start + item.duration}
                for item in plan.segments if item.subtitle.strip()]
        alignment.update(type="scene", cues=cues, source="approved_scene_plan")
    native.checkpoint(db, job, "Hypit 正在编排字幕与画面并渲染", 93, stop_event)
    state = _render_state(db, project, job, version)

    def on_build(build_id):
        state.meta = {**state.meta, "state": "rendering", "build_id": build_id}
        db.commit()

    def cancelled():
        native.checkpoint(db, job, stop_event=stop_event)
        return False

    result = engine.render(render_work, video, words=words, cues=cues,
        width=info["width"], height=info["height"], caption_style=options.get("caption_style", "highlight"),
        cancelled=cancelled, on_build=on_build, resume_build_id=state.meta.get("build_id"))
    native.checkpoint(db, job, "保存 Hypit 工作流、词级对齐与成片", 98, stop_event)
    rendered_info = media.probe(result.video)
    if (abs(rendered_info["duration"] - info["duration"]) > 0.2 or rendered_info["width"] != info["width"]
            or rendered_info["height"] != info["height"] or rendered_info["has_audio"] != info["has_audio"]):
        raise native.NeedsAttention("Hypit 导出时长、画幅或音轨与生成片段不一致；已保留片段和先前成片，请检查本地引擎。")
    asset = _archive_result(db, project, result, version, alignment, rendered_info)
    native.checkpoint(db, job, stop_event=stop_event)
    project.output_asset_id = asset.id
    project.status = "needs_review" if speech_warning or any(row.quality.get("status") != "pass" for row in segments) else "completed"
    project.error = None
    state.meta = {**state.meta, "state": "completed", "output_asset_id": asset.id}
    db.commit()
    native.checkpoint(db, job, "词-复刻视频已完成，请完整预览产品、口播与字幕" if project.status == "needs_review"
                      else "词-复刻视频已完成，请完整预览后发布", 100, stop_event)
    # Canonical generated clips, alignment and portable workflow live in DB;
    # successful local render inputs can be recreated on any later retry.
    try:
        shutil.rmtree(render_work)
    except OSError:
        log.info("词-复刻成片已归档，本地临时工作目录将在后续维护时清理")


def review_project(db, project, job, work, stop_event):
    _word_project(project)
    output = db.get(Asset, project.output_asset_id) if project.output_asset_id else None
    if not output or output.project_id != project.id or output.role != "output" or output.meta.get("engine") != "hypit":
        raise ValueError("请先完成 Hypit 成片合成，再复查现有作品；已生成片段可通过重试继续合成。")
    native.review_project(db, project, job, work, stop_event)
    if project.output_asset_id:
        asset = db.get(Asset, project.output_asset_id)
        if asset and asset.meta.get("alignment_type") == "word":
            project.status = "needs_review"
            db.commit()
            native.checkpoint(db, job, "产品抽帧复查完成；实际口播和词级字幕仍需完整预览", 100, stop_event)


class WordWorker:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def recover_interrupted(self):
        with SessionLocal() as db:
            for job in db.scalars(select(Job).where(Job.status == "running", Job.action.in_(WORD_ACTIONS))):
                job.status, job.error = "needs_attention", "词-复刻任务因服务中断，请明确重试；已保存的片段和转写记录会复用，未知付费请求不会重新提交。"
                job.message, job.updated_at = job.error, time.time()
                project = db.get(Project, job.project_id)
                if project:
                    project.status, project.error = "needs_attention", job.error
            db.commit()

    def start(self):
        self.stop_event.clear()
        self.recover_interrupted()
        self.thread = threading.Thread(target=self.loop, name="vio-word-worker", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=10)

    def loop(self):
        while not self.stop_event.is_set():
            try:
                with SessionLocal() as db:
                    job = db.scalar(select(Job).where(Job.status == "queued", Job.action.in_(WORD_ACTIONS))
                                    .order_by(Job.created_at).limit(1))
                    job_id = job.id if job else None
                if job_id:
                    self.run_job(job_id)
                else:
                    self.stop_event.wait(1)
            except Exception:
                log.error("词-复刻任务队列暂时不可用，请检查数据库和本地资源")
                self.stop_event.wait(3)

    def run_job(self, job_id):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if not job or job.status != "queued" or job.action not in WORD_ACTIONS:
                return
            project = db.get(Project, job.project_id)
            job.status, job.updated_at = "running", time.time()
            db.commit()
            try:
                with tempfile.TemporaryDirectory(prefix="vio-word-") as tmp:
                    handler = {"word_analyze": analyze_project, "word_generate": generate_project,
                               "word_review": review_project}[job.action]
                    handler(db, project, job, Path(tmp), self.stop_event)
                job.status = "succeeded"
                db.commit()
            except Exception as exc:
                db.rollback()
                job = db.get(Job, job_id)
                project = db.get(Project, job.project_id)
                attention = isinstance(exc, (native.Cancelled, native.NeedsAttention, providers.SubmissionUncertain))
                job.status = "needs_attention" if attention else "failed"
                # Adapter errors are safe fixed messages. Unknown local errors,
                # including engine diagnostics, never expose remote bodies.
                safe = isinstance(exc, (ValueError, native.Cancelled, native.NeedsAttention, providers.ProviderError))
                message = str(exc)[:1200] if safe else f"词-复刻处理失败（{type(exc).__name__}），请检查本地引擎或模型配置"
                job.error, job.message, job.updated_at = message, message, time.time()
                if project:
                    project.status, project.error = job.status, message
                db.commit()
                log.warning("词-复刻任务 %s 结束，状态 %s，错误类型 %s", job_id, job.status, type(exc).__name__)


worker = WordWorker()
