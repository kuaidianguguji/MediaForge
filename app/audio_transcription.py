"""Durable native Aliyun ASR tasks, independent of the optional video plugin."""
import hashlib
import json
import time
from pathlib import Path

from sqlalchemy import func, select

from . import aliyun_asr, config, providers
from .db import Asset
from .storage import add_asset, storage_settings

MAX_RESPONSE_BYTES = 4 * 1024 * 1024
POLL_SECONDS = 5
MAX_WAIT_SECONDS = 1800


def _attention(message):
    from .pipeline import NeedsAttention
    return NeedsAttention(message)


def preflight(db, model):
    aliyun_asr.validate_model(model)
    providers._headers(model)
    try:
        return storage_settings(db)
    except ValueError:
        raise ValueError("阿里云音频转写需要公网音频链接，请管理员先配置并启用 TOS 存储桶。") from None


def _binding(model):
    return hashlib.sha256(json.dumps([model.id, model.protocol, model.base_url, model.model_id]).encode()).hexdigest()


def _fingerprint(model, source_key, purpose, language):
    return hashlib.sha256(json.dumps([1, _binding(model), source_key, purpose, language]).encode()).hexdigest()


def _write_raw(db, receipt, raw):
    # URLs can contain a temporary bucket signature. Capture the actual ASR
    # content and timing fields, excluding URLs and arbitrary diagnostic fields.
    def keep(value, fields):
        return {key: value[key] for key in fields if key in value} if isinstance(value, dict) else value

    captured = {}
    if "audio_info" in raw:
        captured["audio_info"] = keep(raw["audio_info"], ("format", "sample_rate", "channels", "duration"))
    if "transcripts" in raw:
        transcripts = raw["transcripts"]
        if isinstance(transcripts, list):
            transcripts = [keep(item, ("channel_id", "text", "sentences")) for item in transcripts]
            for channel in transcripts:
                if not isinstance(channel, dict) or not isinstance(channel.get("sentences"), list):
                    continue
                channel["sentences"] = [keep(item, ("begin_time", "end_time", "text", "language", "words"))
                                        for item in channel["sentences"]]
                for sentence in channel["sentences"]:
                    if isinstance(sentence, dict) and isinstance(sentence.get("words"), list):
                        sentence["words"] = [keep(item, ("begin_time", "end_time", "text", "punctuation"))
                                             for item in sentence["words"]]
        captured["transcripts"] = transcripts
    data = json.dumps(captured, ensure_ascii=False).encode()
    if len(data) > MAX_RESPONSE_BYTES:
        raise providers.ProviderError("阿里云转写结果超过本项目允许大小，任务 ID 已保留。")
    receipt.data, receipt.size = data, len(data)
    receipt.sha256 = hashlib.sha256(data).hexdigest()
    receipt.meta = {**receipt.meta, "state": "received", "error": None}
    db.commit()  # Persist every paid timing reply before normalization or validation.
    return captured


def _no_speech_result(purpose):
    if purpose == "generated":
        raise _attention("成片音轨未识别到有效口播，无法制作逐词字幕。已保留生成片段、转写记录和任务 ID；请检查成片声音，系统不会重复提交音频或自动重新生成视频。")
    # An explicit provider no-speech result is not a transcript. Do not invent
    # source words or timings; the visual analysis can explain this limitation.
    return {"text": "", "words": [], "segments": [], "language": None, "duration": 0.0}


def _received_result(raw, purpose):
    normalized = aliyun_asr.normalize(raw)
    if purpose == "generated" and not normalized["text"]:
        return _no_speech_result(purpose)
    return normalized


def _write_failure(db, receipt, snapshot):
    # Save only recognized codes and our translated message. Provider diagnostic
    # messages can contain private URLs or credentials and must not be archived.
    code = snapshot.get("error_code")
    if snapshot["status"] != "failed" or not isinstance(code, str) or code not in aliyun_asr.ERROR_HINTS:
        code = None
    no_speech = snapshot["status"] == "failed" and code == aliyun_asr.NO_SPEECH_CODE
    provider_status = "FAILED" if snapshot["status"] == "failed" else "CANCELED"
    output = {"task_id": receipt.meta["remote_id"], "task_status": provider_status}
    if code:
        output["code"] = code
    data = json.dumps({"output": output}, ensure_ascii=False).encode()
    receipt.data, receipt.size = data, len(data)
    receipt.sha256 = hashlib.sha256(data).hexdigest()
    error = "阿里云音频转写任务已取消。" if snapshot["status"] == "cancelled" else (
        aliyun_asr.ERROR_HINTS.get(code) or "阿里云音频转写失败，请管理员在百炼控制台核查任务详情。")
    receipt.meta = {**receipt.meta, "state": "no_speech" if no_speech else "failed",
                    "provider_status": provider_status, "error_code": code, "error": error}
    db.commit()
    return no_speech


def _wait(checkpoint):
    for _ in range(POLL_SECONDS * 2):
        if checkpoint:
            checkpoint()
        time.sleep(0.5)


def durable_transcribe(db, project, job, model, audio: Path, *, source_key, purpose,
                      language=None, checkpoint=None, role="asr_raw"):
    """Return a normalized transcript and its receipt; never retry a paid POST.

    Received replies and remote task IDs survive process failure. Read-only task
    polling may be resumed explicitly without republishing or resubmitting audio.
    """
    aliyun_asr.validate_model(model)
    if role not in {"asr_raw", "word_asr_raw"} or purpose not in {"reference", "generated"}:
        raise ValueError("音频转写记录类型无效。")
    fingerprint = _fingerprint(model, source_key, purpose, language)
    key_hash = hashlib.sha256((model.api_key_cipher or "").encode()).hexdigest()
    rows = list(db.scalars(select(Asset).where(Asset.project_id == project.id, Asset.role == role)
                          .order_by(Asset.created_at.desc(), Asset.id.desc())))
    receipt = next((row for row in rows if row.meta.get("fingerprint") == fingerprint), None)
    if receipt and receipt.meta.get("state") in {"received", "no_speech"} and checkpoint:
        checkpoint()
    if receipt and receipt.meta.get("state") == "received":
        try:
            raw = json.loads(receipt.data)
        except (ValueError, TypeError):
            raise ValueError("已保存的阿里云转写回复无法读取；未再次提交付费请求。") from None
        return _received_result(raw, purpose), receipt
    if receipt and receipt.meta.get("state") == "no_speech":
        if receipt.meta.get("error_code") != aliyun_asr.NO_SPEECH_CODE or not receipt.meta.get("remote_id"):
            raise _attention("已保存的无口播转写记录不完整，请管理员核对；未重新提交音频。")
        return _no_speech_result(purpose), receipt
    if receipt and not receipt.meta.get("remote_id"):
        state = receipt.meta.get("state")
        if state in {"submitting", "uncertain"}:
            raise _attention("阿里云音频转写提交结果未知，未重复提交。请管理员在百炼控制台核对任务 ID 并关联，再重试查询。")
        if state == "rejected":
            if receipt.meta.get("key_hash") == key_hash:
                raise _attention("阿里云转写请求已被拒绝；未重复提交。请管理员修正 API Key 或模型配置后再明确重试。")
            receipt.meta = {**receipt.meta, "state": "prepared", "key_hash": key_hash, "error": None}
            db.commit()
        elif state != "prepared":
            raise _attention("已有音频转写提交记录但没有可恢复的任务 ID，请管理员核对，未重复提交。")
    # Changing model settings cannot turn an unresolved request into a new POST.
    if not receipt:
        unresolved = next((row for row in rows if row.meta.get("model_config_id") == model.id
            and row.meta.get("source_key") == source_key and row.meta.get("purpose") == purpose
            and row.meta.get("state") in {"submitting", "uncertain", "submitted", "query_error"}), None)
        if unresolved:
            raise _attention("该音频已有未完成的阿里云转写，模型配置已更改。请恢复原配置查询或先核对原任务，未重复提交。")
    if not receipt or not receipt.meta.get("remote_id"):
        settings = preflight(db, model)
        try:
            data = Path(audio).read_bytes()
        except OSError:
            raise ValueError("无法读取待转写音频，未提交付费请求。") from None
        if not data or len(data) > config.MAX_UPLOAD:
            raise ValueError("待转写音频为空或超过本项目上传限制，未提交付费请求。")
        if not receipt:
            usage = db.scalar(select(func.coalesce(func.sum(Asset.size), 0)).where(Asset.owner_id == project.owner_id))
            if usage + len(data) + MAX_RESPONSE_BYTES > config.USER_QUOTA:
                raise ValueError("存储额度不足以保存音频和转写回复，未提交付费请求。")
            audio_role = "word_asr_audio" if role == "word_asr_raw" else "asr_audio"
            stored_audio = add_asset(db, project, data, f"asr-audio-{fingerprint[:24]}.mp3", "audio/mpeg", audio_role,
                {"purpose": purpose, "protocol": "dashscope_asr"})
            receipt = add_asset(db, project, b"{}", f"aliyun-asr-{purpose}-{job.id}.json", "application/json", role,
                {"fingerprint": fingerprint, "state": "prepared", "protocol": "dashscope_asr", "purpose": purpose,
                 "source_key": source_key, "model_config_id": model.id, "key_hash": key_hash,
                 "job_id": job.id, "audio_asset_id": stored_audio.id})
            db.commit()
        else:
            stored_audio = db.get(Asset, receipt.meta.get("audio_asset_id"))
            if not stored_audio or stored_audio.project_id != project.id:
                raise ValueError("已保存的转写音频不存在，请管理员检查；未提交付费请求。")
        if checkpoint:
            checkpoint()
        # This uploads privately and signs one object. Neither signature nor
        # storage credentials enter project metadata or the transcript archive.
        audio_url = providers.publish_media(settings,
            f"vio/{project.owner_id}/{project.id}/asr/{stored_audio.sha256}.mp3", stored_audio.data, "audio/mpeg")
        if checkpoint:
            checkpoint()
        receipt.meta = {**receipt.meta, "state": "submitting", "key_hash": key_hash, "error": None}
        db.commit()
        try:
            remote_id = aliyun_asr.submit(model, audio_url, language)
            receipt.meta = {**receipt.meta, "remote_id": remote_id, "state": "submitted"}
            db.commit()  # Before any cancellation check or network polling.
        except Exception as exc:
            db.rollback()
            receipt = db.get(Asset, receipt.id)
            uncertain = isinstance(exc, providers.SubmissionUncertain) or not isinstance(exc, providers.ProviderError)
            receipt.meta = {**receipt.meta, "state": "uncertain" if uncertain else "rejected",
                            "error": "提交结果未知" if uncertain else "请求被服务商拒绝"}
            db.commit()
            if uncertain:
                raise _attention("阿里云音频转写提交结果未知，提交记录已保存；请管理员核对并关联任务 ID，系统不会再次提交。") from None
            raise
    remote_id = receipt.meta["remote_id"]
    deadline = time.monotonic() + MAX_WAIT_SECONDS
    while True:
        if checkpoint:
            checkpoint()
        try:
            snapshot = aliyun_asr.poll(model, remote_id)
            if snapshot["status"] in {"failed", "cancelled"}:
                if _write_failure(db, receipt, snapshot):
                    if checkpoint:
                        checkpoint()
                    return _no_speech_result(purpose), receipt
                raise _attention(f"{receipt.meta['error']} 任务 ID 已保存；重试不会重新提交音频，请先核查百炼任务详情。")
            if snapshot["status"] == "succeeded":
                raw = aliyun_asr.fetch_result(snapshot["result_url"])
                raw = _write_raw(db, receipt, raw)
                break
            receipt.meta = {**receipt.meta, "state": "submitted", "error": None}
            db.commit()
        except providers.ProviderError:
            db.rollback()
            receipt = db.get(Asset, receipt.id)
            receipt.meta = {**receipt.meta, "state": "query_error", "error": "查询或下载转写结果失败"}
            db.commit()
            raise _attention("阿里云转写查询或结果下载失败，已保留任务 ID；请明确重试以继续查询，不会再次提交音频。") from None
        if time.monotonic() >= deadline:
            raise _attention("阿里云转写等待超时，已保留任务 ID；重试将继续查询，不会再次提交音频。")
        _wait(checkpoint)
    if checkpoint:
        checkpoint()
    return _received_result(raw, purpose), receipt
