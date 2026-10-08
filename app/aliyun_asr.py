"""Native Qwen file transcription: one paid submission, then task queries.

The caller owns durable task IDs and raw-response receipts. This adapter never
retries a submission, stores credentials, or sends authentication to result URLs.
Reference: https://www.alibabacloud.com/help/en/model-studio/qwen-asr-api-reference
"""
import datetime
import json
import math
import re
from urllib.parse import quote, urlsplit, urlunsplit

from . import providers

MAX_RESULT_BYTES = 4 * 1024 * 1024
MAX_WORDS = 20000
MAX_DURATION_MS = 12 * 60 * 60 * 1000
NO_SPEECH_CODE = "SUCCESS_WITH_NO_VALID_FRAGMENT"
LANGUAGES = frozenset({"zh", "yue", "en", "ja", "de", "ko", "ru", "fr", "pt", "ar", "it",
                       "es", "hi", "id", "th", "tr", "uk", "vi", "cs", "da", "fil", "fi",
                       "is", "ms", "no", "pl", "sv"})
ERROR_HINTS = {
    "InvalidApiKey": "阿里云语音密钥无效，请确认 API Key、业务空间与地域匹配。",
    "invalid_api_key": "阿里云语音密钥无效，请确认 API Key、业务空间与地域匹配。",
    "AccessDenied": "没有阿里云语音模型访问权限，请管理员检查百炼授权。",
    "AccessDenied.Unpurchased": "请先开通阿里云百炼并申请语音模型权限。",
    "Model.AccessDenied": "没有阿里云语音模型访问权限，请检查模型与地域。",
    "Workspace.AccessDenied": "没有此百炼业务空间的权限，请检查 Base URL 和 API Key。",
    "Arrearage": "阿里云账户可能欠费，请管理员检查账户余额。",
    "InvalidParameter": "阿里云语音参数不符合要求，请检查模型与音频规格。",
    "FILE_403_FORBIDDEN": "阿里云无法读取转写音频，请检查存储桶临时链接与访问权限。",
    "FILE_404_NOT_FOUND": "阿里云未找到转写音频，请检查临时链接是否已过期。",
    "FILE_DOWNLOAD_FAILED": "阿里云读取转写音频失败，请检查公网临时链接。",
    "UNSUPPORTED_FORMAT": "阿里云不支持此音频格式，请检查音轨。",
    NO_SPEECH_CODE: "阿里云未识别到有效语音；音频可能没有口播，或人声未被识别。",
    "ASR_RESPONSE_HAVE_NO_WORDS": "阿里云转写结果为空，请检查音频中的人声内容。",
    "FILE_CHECK_FAILED": "阿里云音频格式检查未通过，请检查音频编码与文件内容。",
    "FILE_TOO_LARGE": "阿里云转写音频超过大小限制，请检查文件是否超过 2 GB。",
    "AUDIO_DURATION_TOO_LONG": "阿里云转写音频超过时长限制，请检查音频是否超过 12 小时。",
    "FILE_NORMALIZE_FAILED": "阿里云音频处理失败，请检查音频是否损坏或无法播放。",
    "FILE_PARSE_FAILED": "阿里云音频解析失败，请检查音频是否损坏或无法播放。",
    "DECODE_ERROR": "阿里云音频解码失败，请检查下载文件是否包含有效的音轨。",
    "NO_VALID_AUDIO_ERROR": "阿里云未获得有效音频，请检查音频编码与采样率。",
    "FILE_TRANS_TASK_EXPIRED": "阿里云转写任务不存在或已过查询期限，请管理员核查已保存的任务 ID。",
}


def validate_model(model):
    if not model or getattr(model, "protocol", None) != "dashscope_asr":
        raise providers.ProviderError("阿里云音频转写需要阿里云语音转写原生协议。")
    model_id = getattr(model, "model_id", None)
    if not isinstance(model_id, str) or not re.fullmatch(r"qwen3-asr-flash-filetrans(?:-\d{4}-\d{2}-\d{2})?", model_id):
        raise providers.ProviderError("阿里云语音接口目前支持 qwen3-asr-flash-filetrans 及其日期快照版。")
    if model_id != "qwen3-asr-flash-filetrans":
        try:
            datetime.date.fromisoformat(model_id[-10:])
        except ValueError:
            raise providers.ProviderError("阿里云语音模型的快照日期无效。") from None
    endpoint = providers._endpoint(model, "services/audio/asr/transcription")
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or urlsplit(str(model.base_url).strip().rstrip("/")).path != "/api/v1":
        raise providers.ProviderError("阿里云语音 Base URL 需要公网 HTTPS 地址并以 /api/v1 结尾，不包含操作路径。")


def payload(model, audio_url: str, language: str | None = None) -> dict:
    validate_model(model)
    # Validate before a caller records a paid attempt. The provider itself will
    # download this audio; local and cloud metadata endpoints cannot be inputs.
    providers._public_target(audio_url)
    if language is not None and (not isinstance(language, str) or language not in LANGUAGES):
        raise providers.ProviderError("阿里云语音识别语言无效；巴西葡语请使用 pt。")
    parameters = {"channel_id": [0], "enable_itn": False, "enable_words": True}
    if language:
        parameters["language"] = language
    return {"model": model.model_id, "input": {"file_url": audio_url}, "parameters": parameters}


def _error_code(result):
    """Return only recognized codes, never arbitrary provider diagnostics."""
    if not isinstance(result, dict):
        return None
    output = result.get("output")
    code = output.get("code") if isinstance(output, dict) and output.get("code") else result.get("code")
    return code if isinstance(code, str) and code in ERROR_HINTS else None


def _hint(result):
    return ERROR_HINTS.get(_error_code(result))


def submit(model, audio_url: str, language: str | None = None) -> str:
    body = payload(model, audio_url, language)
    result = providers._request(model, "POST", "services/audio/asr/transcription", submitting=True,
                                extra_headers={"X-DashScope-Async": "enable"}, json=body)
    output = result.get("output")
    task_id = output.get("task_id") if isinstance(output, dict) else None
    if isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
        return task_id
    if hint := _hint(result):
        raise providers.ProviderError(hint)
    raise providers.SubmissionUncertain("阿里云语音未返回有效任务 ID，可能已受理；请先核查百炼任务记录，避免重复扣费。")


def _secure_result_url(url):
    try:
        if not isinstance(url, str) or not 0 < len(url) <= 16384:
            raise ValueError
        parsed = urlsplit(url)
        host = parsed.hostname
        if not host or parsed.username or parsed.password or parsed.fragment or parsed.port not in {None, 443}:
            raise ValueError
        # Official responses can contain HTTP OSS URLs. Their signatures do not
        # depend on the URL scheme; use TLS to the same official host and path.
        if parsed.scheme == "http" and re.fullmatch(r"[a-zA-Z0-9.-]+\.oss-[a-zA-Z0-9-]+\.aliyuncs\.com", host):
            return urlunsplit(parsed._replace(scheme="https"))
        if parsed.scheme != "https":
            raise ValueError
        return url
    except (ValueError, TypeError):
        raise providers.ProviderError("阿里云转写结果下载地址无效，已保留任务 ID；请核查服务商结果。") from None


def poll(model, task_id: str) -> dict:
    validate_model(model)
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
        raise providers.ProviderError("阿里云语音任务 ID 无效。")
    result = providers._request(model, "GET", "tasks/" + quote(task_id, safe=""))
    output = result.get("output")
    if not isinstance(output, dict):
        raise providers.ProviderError(_hint(result) or "阿里云语音响应缺少任务信息，已保留任务 ID。")
    if output.get("task_id") is not None and output["task_id"] != task_id:
        raise providers.ProviderError("阿里云语音返回的任务 ID 与查询不符，已停止处理。")
    upstream_status = output.get("task_status")
    status = {"PENDING": "queued", "RUNNING": "running", "SUCCEEDED": "succeeded",
              "FAILED": "failed", "CANCELED": "cancelled", "CANCELLED": "cancelled"}.get(upstream_status) if isinstance(upstream_status, str) else None
    if status is None:
        raise providers.ProviderError("阿里云语音任务状态未知、任务不存在或已过查询期限。已保留任务 ID，系统不会重新提交。")
    result_url, error = None, None
    if status == "succeeded":
        data = output.get("result")
        result_url = _secure_result_url(data.get("transcription_url") if isinstance(data, dict) else None)
    elif status == "failed":
        error = _hint(result) or "阿里云音频转写失败，请管理员在百炼控制台核查任务详情。"
    elif status == "cancelled":
        error = "阿里云音频转写任务已取消。"
    snapshot = {"status": status, "result_url": result_url, "error": error}
    if status == "failed" and (code := _error_code(result)):
        snapshot["error_code"] = code
    return snapshot


def fetch_result(url: str) -> dict:
    """Download raw JSON with pinned public DNS, redirects checked, and no key."""
    data = providers.download_media(_secure_result_url(url), max_bytes=MAX_RESULT_BYTES)
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise providers.ProviderError("阿里云转写结果文件不是有效 JSON 对象，已保留任务 ID，未重新提交。") from None


def _time_span(item):
    begin, end = item.get("begin_time"), item.get("end_time")
    if (isinstance(begin, bool) or isinstance(end, bool) or not isinstance(begin, (int, float))
            or not isinstance(end, (int, float)) or not math.isfinite(begin) or not math.isfinite(end)
            or begin < 0 or end < begin or end > MAX_DURATION_MS):
        raise providers.ProviderError("阿里云转写结果的时间戳无效；原始结果已保留，未重新提交。")
    return float(begin) / 1000, float(end) / 1000


def normalize(raw: dict) -> dict:
    """Convert measured millisecond timestamps; never estimate word timings.

    Some genuine Qwen words have identical start/end timestamps. Preserve these
    in normalized output so the subtitle caller can handle them explicitly.
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("transcripts"), list) or len(raw["transcripts"]) > 16:
        raise providers.ProviderError("阿里云转写结果缺少音轨文字；原始结果已保留，未重新提交。")
    channels = [entry for entry in raw["transcripts"] if isinstance(entry, dict)
                and type(entry.get("channel_id")) is int and entry["channel_id"] == 0]
    if len(channels) != 1 or not isinstance(channels[0].get("text"), str):
        raise providers.ProviderError("阿里云转写结果缺少唯一的第一音轨文字；原始结果已保留，未重新提交。")
    channel = channels[0]
    sentences = channel.get("sentences", [])
    if not isinstance(sentences, list) or len(sentences) > MAX_WORDS:
        raise providers.ProviderError("阿里云转写结果的句子格式无效；原始结果已保留，未重新提交。")
    words, segments, languages = [], [], set()
    for sentence in sentences:
        if not isinstance(sentence, dict) or not isinstance(sentence.get("text"), str):
            raise providers.ProviderError("阿里云转写结果的句子文字无效；原始结果已保留，未重新提交。")
        start, end = _time_span(sentence)
        segments.append({"text": sentence["text"].strip(), "start": start, "end": end})
        if isinstance(sentence.get("language"), str):
            languages.add(sentence["language"])
        source = sentence.get("words", [])
        if not isinstance(source, list) or len(source) + len(words) > MAX_WORDS:
            raise providers.ProviderError("阿里云转写结果的逐词列表无效；原始结果已保留，未重新提交。")
        for item in source:
            if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
                raise providers.ProviderError("阿里云逐词转写的文字无效；原始结果已保留，未重新提交。")
            word_start, word_end = _time_span(item)
            punctuation = item.get("punctuation", "")
            if not isinstance(punctuation, str) or len(punctuation) > 16:
                raise providers.ProviderError("阿里云逐词转写的标点无效；原始结果已保留，未重新提交。")
            text = item["text"].strip()
            if punctuation and not text.endswith(punctuation):
                text += punctuation
            words.append({"word": text, "start": word_start, "end": word_end})
    return {"text": channel["text"].strip(), "words": words, "segments": segments,
            "language": next(iter(languages)) if len(languages) == 1 else None,
            "duration": max((item["end"] for item in segments + words), default=0.0)}
