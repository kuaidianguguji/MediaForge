"""Synchronous provider adapters. No paid request is automatically retried."""
import base64
import binascii
import io
import ipaddress
import json
import mimetypes
import re
import socket
from pathlib import Path
from urllib.parse import quote, urljoin, urlsplit

import httpx
from PIL import Image

from .security import decrypt


class ProviderError(RuntimeError):
    """A safe user-facing error, without remote response bodies or credentials."""


class SubmissionUncertain(ProviderError):
    """The upstream may have accepted a paid request; do not resubmit blindly."""


MAX_IMAGE_BYTES = 30 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024

# Translate documented error codes instead of exposing remote messages, which may
# contain API keys, signed media URLs or echoed request content.
VIDEO_ERROR_HINTS = {
    "OutputAudioSensitiveContentDetected.PolicyViolation": "生成音频可能涉及版权限制，已被火山引擎拒绝。接口未区分音乐或口播；可调整音频设置，改用原创配乐/口播，或先生成无声版本。请勿直接重复原请求。",
    "OutputAudioSensitiveContentDetected": "生成音频未通过供应商内容审核，请检查口播和配乐内容，调整音频设置后再试。",
    "InputAudioSensitiveContentDetected.PolicyViolation": "参考音频可能涉及版权限制，请更换为有使用权的音频，或关闭参考原片音频。",
    "InputVideoSensitiveContentDetected.PolicyViolation": "参考视频可能涉及版权限制，请更换可用于创作的参考素材。",
    "InputImageSensitiveContentDetected.PolicyViolation": "参考图片可能涉及版权限制，请检查并更换素材。",
    "InputTextSensitiveContentDetected.PolicyViolation": "输入文案可能涉及版权限制，请检查和修改文案。",
    "OutputVideoSensitiveContentDetected.PolicyViolation": "生成画面可能涉及版权限制，请检查参考素材和分镜。",
    "InputVideoSensitiveContentDetected.PrivacyInformation": "参考视频包含需要授权的真人素材，请按供应商要求处理授权或更换素材。",
    "InputImageSensitiveContentDetected.PrivacyInformation": "参考图片包含需要授权的真人素材，请按供应商要求处理授权或更换素材。",
    "InputVideoSensitiveContentDetected": "参考视频未通过供应商内容审核，请检查素材。",
    "InputImageSensitiveContentDetected": "参考图片未通过供应商内容审核，请检查素材。",
    "InputTextSensitiveContentDetected": "文案未通过供应商内容审核，请检查输入内容。",
    "OutputVideoSensitiveContentDetected": "生成画面未通过供应商内容审核，请检查分镜与参考素材。",
    "InvalidParameter": "请求参数不符合当前模型要求，请检查素材规格、时长、比例和分辨率。",
    "OperationDenied.ServiceOverdue": "服务商账户欠费，请管理员检查余额。",
}


def video_error_hint(result):
    error = result.get("error") if isinstance(result, dict) else None
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    if not isinstance(code, str) or code not in VIDEO_ERROR_HINTS:
        return None
    return f"{VIDEO_ERROR_HINTS[code]} [错误码：{code}]"


def _client(timeout=180):
    return httpx.Client(timeout=httpx.Timeout(timeout, connect=20),
                        follow_redirects=False, trust_env=False)


def _endpoint(model, path):
    try:
        base = str(model.base_url).strip().rstrip("/")
        parsed = urlsplit(base)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError
        parsed.port
    except (ValueError, TypeError):
        raise ProviderError("模型接口地址无效，请填写包含版本路径的 Base URL。") from None
    return base + "/" + path.lstrip("/")


def _headers(model):
    try:
        key = decrypt(model.api_key_cipher)
    except Exception:
        raise ProviderError("模型密钥无法解密，请管理员重新保存密钥。") from None
    if not key or any(c in key for c in "\r\n"):
        raise ProviderError("请管理员配置有效的模型 API Key。")
    if model.protocol == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": "Bearer " + key}


def _request(model, method, path, *, submitting=False, extra_headers=None, **kwargs):
    endpoint = _endpoint(model, path)
    headers = _headers(model)
    if extra_headers:
        headers.update(extra_headers)
    try:
        with _client(300 if submitting else 180) as client:
            response = client.request(method, endpoint, headers=headers, **kwargs)
    except (httpx.HTTPError, ValueError):
        if submitting:
            raise SubmissionUncertain("请求结果未确认，上游可能已受理。请先核查服务商任务或账单，勿重复提交。") from None
        raise ProviderError("模型服务连接失败，请稍后重试或检查接口配置。") from None
    if submitting and (response.status_code >= 500 or response.status_code == 408):
        raise SubmissionUncertain("上游响应异常，任务可能已受理。请先核查服务商任务或账单，勿重复提交。")
    if not response.is_success:
        if response.is_redirect:
            raise ProviderError("模型接口返回重定向；请管理员填写最终 Base URL。")
        advice = {401: "密钥无效", 403: "没有模型访问权限", 404: "接口或模型不存在",
                  413: "输入文件过大", 429: "服务商限流或额度不足"}.get(response.status_code, "请检查模型配置与输入参数")
        try:
            hint = wan_error_hint(response.json()) if model.protocol == "dashscope" else video_error_hint(response.json())
        except ValueError:
            hint = None
        if hint:
            raise ProviderError(f"模型服务 HTTP {response.status_code}：{hint}")
        raise ProviderError(f"模型服务 HTTP {response.status_code}：{advice}。")
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError):
        exc = SubmissionUncertain if submitting else ProviderError
        raise exc("服务商响应格式无效；请检查兼容协议。已提交的请求请勿直接重复提交。") from None


def _json_object(text):
    if not isinstance(text, str):
        raise ProviderError("分析模型未返回有效文本。")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ProviderError("分析模型没有返回有效 JSON 对象，请更换支持结构化分析的模型。") from None


def analyze(model, prompt: str, images: list[bytes], on_response=None) -> dict:
    """Capture assistant text before parsing, so a failed analysis can be recovered.

    ``on_response(text, metadata)`` receives only assistant text and completion
    metadata, never request headers, credentials or the full HTTP response.
    Capture errors propagate: callers must not continue with an unsaved result.
    """
    if model.protocol not in {"openai", "anthropic", "volcengine"}:
        raise ProviderError("不支持此视觉分析协议。")
    if any(len(image) > MAX_IMAGE_BYTES for image in images):
        raise ProviderError("分析图片过大。")
    instruction = "仅输出一个 JSON 对象，不要 Markdown，不要省略要求的字段。\n" + prompt
    if model.protocol == "anthropic":
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                    "data": base64.b64encode(img).decode("ascii")}} for img in images]
        content.append({"type": "text", "text": instruction})
        result = _request(model, "POST", "messages", json={"model": model.model_id,
            "max_tokens": 8192, "messages": [{"role": "user", "content": content}]})
        finish_reason = result.get("stop_reason")
        blocks = result.get("content", [])
        if not isinstance(blocks, list):
            raise ProviderError("视觉模型响应缺少分析内容。")
        texts = [x.get("text", "") for x in blocks
                 if isinstance(x, dict) and x.get("type") == "text"]
        if not all(isinstance(value, str) for value in texts):
            raise ProviderError("分析模型未返回有效文本。")
        text = "\n".join(texts)
    else:
        content = [{"type": "text", "text": instruction}]
        content.extend({"type": "image_url", "image_url": {"url":
            "data:image/jpeg;base64," + base64.b64encode(img).decode("ascii")}} for img in images)
        result = _request(model, "POST", "chat/completions", json={"model": model.model_id,
            "messages": [{"role": "user", "content": content}]})
        try:
            choice = result["choices"][0]
            finish_reason = choice.get("finish_reason")
            text = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, AttributeError):
            raise ProviderError("视觉模型响应缺少分析内容。") from None
    if not isinstance(text, str):
        raise ProviderError("分析模型未返回有效文本。")
    truncated = finish_reason in {"max_tokens", "length"} if isinstance(finish_reason, str) else False
    if on_response is not None:
        # Finish reasons are provider metadata, not trusted user-facing text.
        safe_reason = finish_reason if isinstance(finish_reason, str) and finish_reason in {
            "stop", "length", "content_filter", "tool_calls", "function_call",
            "end_turn", "max_tokens", "stop_sequence", "tool_use", "pause_turn", "refusal"
        } else "unknown" if finish_reason is not None else None
        on_response(text, {"finish_reason": safe_reason, "truncated": truncated})
    if truncated:
        message = ("分析结果超过模型输出限制，请减少输入视频长度或选择其他模型。"
                   if model.protocol == "anthropic" else
                   "分析输出被截断，请减少视频长度或更换模型。")
        raise ProviderError(message)
    return _json_object(text)


def _image_mime(data):
    if not isinstance(data, bytes) or not data or len(data) > MAX_IMAGE_BYTES:
        raise ProviderError("图片为空或超过 30 MB。")
    try:
        with Image.open(io.BytesIO(data)) as img:
            kind = img.format
            img.verify()
        return {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}[kind]
    except Exception:
        raise ProviderError("图片需要是有效的 JPEG、PNG 或 WebP。") from None


def edit_image(model, image: bytes, prompt: str) -> bytes:
    return edit_images(model, [image], prompt)


def edit_images(model, images: list[bytes], prompt: str) -> bytes:
    """The first image supplies the scene; subsequent images define the product."""
    if model.protocol not in {"openai", "volcengine"}:
        raise ProviderError("Anthropic Messages 协议不提供图像编辑，请选择 OpenAI 图像编辑或火山引擎图像模型。")
    if not 1 <= len(images) <= 9:
        raise ProviderError("图像编辑需要 1–9 张输入图片；模型须支持多图编辑。")
    mimes = [_image_mime(image) for image in images]
    if model.protocol == "openai":
        files = {"image": ("product." + mimes[0].split("/")[1], images[0], mimes[0])} if len(images) == 1 else [
            ("image[]", (f"reference-{i}." + mime.split("/")[1], image, mime))
            for i, (image, mime) in enumerate(zip(images, mimes))]
        result = _request(model, "POST", "images/edits", submitting=True,
            data={"model": model.model_id, "prompt": prompt, "n": "1"},
            files=files)
    else:
        inputs = ["data:" + mime + ";base64," + base64.b64encode(image).decode("ascii") for image, mime in zip(images, mimes)]
        result = _request(model, "POST", "images/generations", submitting=True, json={
            "model": model.model_id, "prompt": prompt,
            "image": inputs[0] if len(inputs) == 1 else inputs,
            "response_format": "b64_json", "size": "2K", "watermark": False})
    try:
        item = result["data"][0]
        if item.get("b64_json"):
            encoded = item["b64_json"]
            if len(encoded) > MAX_IMAGE_BYTES * 4 // 3 + 4:
                raise ValueError
            output = base64.b64decode(encoded, validate=True)
        else:
            output = download_media(item["url"], max_bytes=MAX_IMAGE_BYTES)
    except (KeyError, IndexError, TypeError, ValueError, binascii.Error):
        raise ProviderError("图像服务未返回有效图片。") from None
    _image_mime(output)
    return output


def transcribe(model, audio: Path) -> str:
    if model.protocol != "openai":
        raise ProviderError("语音转写需要支持 /audio/transcriptions 的 OpenAI 兼容服务。")
    try:
        if audio.stat().st_size > 25 * 1024 * 1024:
            raise ProviderError("转写音频超过 25 MB，请先压缩或分段。")
        with audio.open("rb") as stream:
            result = _request(model, "POST", "audio/transcriptions",
                data={"model": model.model_id}, files={"file": (audio.name, stream,
                    mimetypes.guess_type(audio.name)[0] or "application/octet-stream")})
    except OSError:
        raise ProviderError("无法读取待转写音频。") from None
    if not isinstance(result.get("text"), str):
        raise ProviderError("转写服务未返回文字。")
    return result["text"]


def create_video(model, prompt: str, image_urls: list[str], video_url: str | None,
                 duration: int, ratio="9:16", resolution="720p", generate_audio=True) -> str:
    if model.protocol == "dashscope":
        body = wan_video_payload(model, prompt, image_urls, video_url, duration, ratio, resolution, generate_audio)
        result = _request(model, "POST", "services/aigc/video-generation/video-synthesis", submitting=True,
                          extra_headers={"X-DashScope-Async": "enable"}, json=body)
        output = result.get("output")
        task_id = output.get("task_id") if isinstance(output, dict) else None
        if isinstance(task_id, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
            return task_id
        hint = wan_error_hint(result)
        if hint:
            raise ProviderError(hint)
        raise SubmissionUncertain("阿里云没有返回有效任务 ID，可能已受理；请先核查百炼任务记录，避免重复扣费。")
    if model.protocol != "volcengine":
        raise ProviderError("Seedance 视频需要火山引擎原生协议；Chat 兼容接口不等于视频接口兼容。")
    if type(duration) is not int or not 4 <= duration <= 15:
        raise ProviderError("Seedance 2.0 每段生成时长必须为 4–15 秒整数。")
    if not 1 <= len(image_urls) <= 9:
        raise ProviderError("产品复刻需要 1–9 张参考图。")
    if ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"}:
        raise ProviderError("不支持此视频比例。")
    if resolution not in {"480p", "720p", "1080p", "4k"}:
        raise ProviderError("不支持此视频分辨率。")
    if ("fast" in model.model_id or "mini" in model.model_id) and resolution not in {"480p", "720p"}:
        raise ProviderError("Seedance 2.0 fast/mini 支持 480p 或 720p。")
    for url in image_urls + ([video_url] if video_url else []):
        # The provider must fetch these itself; local URLs will never work.
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ProviderError("视频参考素材需要公网 HTTPS 临时链接。")
    content = [{"type": "text", "text": prompt}]
    content.extend({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"}
                   for url in image_urls)
    if video_url:
        content.append({"type": "video_url", "video_url": {"url": video_url}, "role": "reference_video"})
    result = _request(model, "POST", "contents/generations/tasks", submitting=True, json={
        "model": model.model_id, "content": content, "duration": duration,
        "ratio": ratio, "resolution": resolution, "generate_audio": bool(generate_audio),
        "watermark": False, "execution_expires_after": 86400})
    task_id = result.get("id")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
        raise SubmissionUncertain("服务商未返回有效任务 ID，可能已受理。请先核查服务商任务记录。")
    return task_id


def get_video(model, task_id) -> dict:
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", task_id):
        raise ProviderError("视频任务 ID 无效。")
    if model.protocol == "dashscope":
        result = _request(model, "GET", "tasks/" + quote(task_id, safe=""))
        output = result.get("output")
        if not isinstance(output, dict):
            raise ProviderError(wan_error_hint(result) or "阿里云响应缺少视频任务信息，请核查 Base URL 和模型权限。")
        returned_id = output.get("task_id")
        if returned_id is not None and returned_id != task_id:
            raise ProviderError("阿里云返回的任务 ID 与查询不符，已停止处理。")
        upstream_status = output.get("task_status")
        if upstream_status == "UNKNOWN":
            raise ProviderError("阿里云任务不存在、状态未知或已超过 24 小时查询期限。已保留任务 ID，请在百炼控制台核查，系统不会重新提交。")
        status = {"PENDING": "queued", "RUNNING": "running", "SUCCEEDED": "succeeded",
                  "FAILED": "failed", "CANCELED": "cancelled"}.get(upstream_status) if isinstance(upstream_status, str) else None
        if status is None:
            raise ProviderError("阿里云返回未知任务状态，已保留任务 ID，请稍后重试查询。")
        url = output.get("video_url")
        if status == "succeeded" and (not isinstance(url, str) or not url.startswith("https://")):
            raise ProviderError("阿里云任务成功但缺少有效下载地址，已保留任务 ID，请核查任务结果。")
        error = (wan_error_hint(result) or "阿里云视频生成失败，请在百炼控制台核查任务详情。") if status == "failed" else "阿里云视频任务已取消。" if status == "cancelled" else None
        return {"status": status, "video_url": url if status == "succeeded" else None, "error": error}
    if model.protocol != "volcengine":
        raise ProviderError("此模型没有配置受支持的视频任务协议。")
    result = _request(model, "GET", "contents/generations/tasks/" + quote(task_id, safe=""))
    status = result.get("status")
    if status not in {"queued", "running", "succeeded", "failed", "cancelled", "expired"}:
        raise ProviderError("服务商返回未知任务状态。")
    output = result.get("content") or {}
    url = output.get("video_url") if isinstance(output, dict) else None
    if status == "succeeded" and not isinstance(url, str):
        raise ProviderError("视频任务成功但缺少下载地址。")
    # Known codes retain an actionable reason; never expose raw remote messages.
    error = {"failed": "视频生成失败，请管理员在服务商控制台核查任务详情。",
             "cancelled": "服务商视频任务已取消。", "expired": "服务商视频任务已超时。"}.get(status)
    if status == "failed":
        error = video_error_hint(result) or error
    return {"status": status, "video_url": url, "error": error}


WAN_ERROR_HINTS = {
    "InvalidApiKey": "阿里云 API Key 无效，请确认密钥、业务空间与地域匹配。",
    "invalid_api_key": "阿里云 API Key 无效，请确认密钥、业务空间与地域匹配。",
    "InvalidParameter": "万相输入参数或素材规格不符合要求，请检查图片、视频、时长和分辨率。",
    "Arrearage": "阿里云账户可能欠费，请管理员检查账户状态与余额。",
    "DataInspectionFailed": "万相输入或输出未通过内容审核，请检查素材和文案。",
    "data_inspection_failed": "万相输入或输出未通过内容审核，请检查素材和文案。",
    "AccessDenied": "没有万相模型调用权限，请检查百炼模型授权。",
    "AccessDenied.Unpurchased": "请先开通阿里云百炼服务并申请模型权限。",
    "Model.AccessDenied": "没有万相模型调用权限，请检查业务空间的模型授权。",
    "Workspace.AccessDenied": "没有此百炼业务空间的权限，请检查 Base URL 和 API Key 是否匹配。",
}


def wan_error_hint(result):
    if not isinstance(result, dict):
        return None
    output = result.get("output")
    code = output.get("code") if isinstance(output, dict) and output.get("code") else result.get("code")
    if not isinstance(code, str) or code not in WAN_ERROR_HINTS:
        return None
    return f"{WAN_ERROR_HINTS[code]} [错误码：{code}]"


def wan_video_payload(model, prompt, image_urls, video_url, duration, ratio, resolution, generate_audio):
    """Validate before recording a submission or charging an attempt; no network."""
    if model.model_id not in {"wan3.0-video", "wan3.0-video-prime"}:
        raise ProviderError("阿里云视频接口目前支持 wan3.0-video 与 wan3.0-video-prime。")
    if urlsplit(model.base_url).path.rstrip("/") != "/api/v1":
        raise ProviderError("阿里云视频 Base URL 必须以 /api/v1 结尾，不包含具体操作路径。")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 20000:
        raise ProviderError("万相视频提示词不能为空且不能超过 20000 字符，请精简该片段分镜与产品约束后再生成。")
    # Keep the existing <=15s segment/FFmpeg workflow; Wan's 30s mode is not exposed here.
    if type(duration) is not int or not 4 <= duration <= 15:
        raise ProviderError("本项目万相每段生成时长为 4–15 秒整数，长视频会自动分段拼接。")
    if not isinstance(image_urls, list) or not 1 <= len(image_urls) <= 10:
        raise ProviderError("万相产品复刻需要 1–10 张参考图片。")
    if ratio not in {"16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"} or resolution not in {"480p", "720p", "1080p"}:
        raise ProviderError("万相不支持此比例或分辨率，请选择 480P、720P 或 1080P。")
    for url in image_urls + ([video_url] if video_url else []):
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ProviderError("万相参考素材需要可访问的公网 HTTPS 临时链接。")
    media = [{"type": "reference_image", "url": url} for url in image_urls]
    if video_url:
        media.append({"type": "reference_video", "url": video_url})
    return {"model": model.model_id, "input": {"prompt": prompt, "media": media},
            "parameters": {"duration": duration, "ratio": ratio, "resolution": resolution.upper(),
                           "audio": bool(generate_audio), "prompt_extend": False, "watermark": False}}


def _public_target(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (parsed.scheme != "https" or not host or parsed.username or parsed.password
                or parsed.fragment or "%" in host or parsed.port not in {None, 443}):
            raise ValueError
        host = host.encode("idna").decode("ascii")
        if host.rstrip(".").lower() in {"localhost", "metadata.google.internal", "metadata"}:
            raise ValueError
        records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        ips = {record[4][0] for record in records}
        if not ips:
            raise ValueError
        for address in ips:
            ip = ipaddress.ip_address(address)
            if not ip.is_global or ip.is_multicast or ip.is_reserved:
                raise ValueError
            if isinstance(ip, ipaddress.IPv6Address) and (ip.ipv4_mapped or ip.sixtofour or ip.teredo):
                raise ValueError
        return host, sorted(ips)[0]
    except (ValueError, TypeError, UnicodeError, OSError):
        raise ProviderError("媒体下载只允许公网 HTTPS 地址；禁止本机、局域网和云元数据地址。") from None


def download_media(url, max_bytes=MAX_DOWNLOAD_BYTES) -> bytes:
    if type(max_bytes) is not int or max_bytes < 1:
        raise ProviderError("媒体下载大小限制无效。")
    for _ in range(6):
        host, address = _public_target(url)
        try:
            # Pin DNS to the already checked IP; Host and SNI keep TLS verification intact.
            target = httpx.URL(url).copy_with(host=address)
            host_header = "[" + host + "]" if ":" in host else host
            with _client(300) as client:
                with client.stream("GET", target, headers={"Host": host_header},
                                   extensions={"sni_hostname": host}) as response:
                    if response.status_code in {301, 302, 303, 307, 308}:
                        location = response.headers.get("location")
                        if not location:
                            raise ProviderError("媒体下载跳转缺少地址。")
                        url = urljoin(url, location)
                        continue
                    if not response.is_success:
                        raise ProviderError(f"媒体下载失败（HTTP {response.status_code}），临时链接可能已过期。")
                    length = response.headers.get("content-length")
                    if length and int(length) > max_bytes:
                        raise ProviderError("媒体文件超过允许大小。")
                    result = bytearray()
                    for chunk in response.iter_bytes():
                        if len(result) + len(chunk) > max_bytes:
                            raise ProviderError("媒体文件超过允许大小。")
                        result.extend(chunk)
                    if not result:
                        raise ProviderError("下载的媒体文件为空。")
                    return bytes(result)
        except (httpx.HTTPError, ValueError):
            raise ProviderError("媒体下载连接失败或响应无效。") from None
    raise ProviderError("媒体下载重定向次数过多。")


def publish_media(settings: dict, key, data, mime) -> str:
    required = ("endpoint", "region", "bucket", "access_key_id", "secret_access_key")
    if any(not settings.get(name) for name in required):
        raise ProviderError("请管理员完整配置火山引擎 TOS 存储桶。")
    try:
        endpoint = settings["endpoint"].strip().rstrip("/")
        if "://" not in endpoint:
            endpoint = "https://" + endpoint
        parsed = urlsplit(endpoint)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError
        ttl = int(settings.get("url_ttl", 172800))
        if not 3600 <= ttl <= 604800 or not isinstance(key, str) or not key or key.startswith("/"):
            raise ValueError
    except (ValueError, TypeError):
        raise ProviderError("TOS 配置无效：Endpoint 需为 HTTPS，临时链接有效期为 1 小时至 7 天。") from None
    try:
        import tos
        client = tos.TosClientV2(settings["access_key_id"], settings["secret_access_key"],
                                 endpoint, settings["region"])
        client.put_object(settings["bucket"], key, content=data, content_type=mime,
                          acl=tos.ACLType.ACL_Private)
        signed = client.pre_signed_url(tos.HttpMethodType.Http_Method_Get,
            bucket=settings["bucket"], key=key, expires=ttl)
        return signed.signed_url
    except Exception:
        raise ProviderError("TOS 上传或签名失败，请检查桶地域、权限和密钥。") from None
