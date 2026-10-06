import base64
import io
import json
import socket
import sys
from types import SimpleNamespace

import httpx
import pytest
from PIL import Image

from app import providers as p


@pytest.fixture
def model(monkeypatch):
    monkeypatch.setattr(p, "decrypt", lambda value: "private-api-key")
    return SimpleNamespace(protocol="volcengine", base_url="https://proxy.example/api/v3",
                           model_id="doubao-seedance-2-0-260128", api_key_cipher="cipher")


def transport(monkeypatch, handler):
    monkeypatch.setattr(p, "_client", lambda timeout=180: httpx.Client(
        transport=httpx.MockTransport(handler), follow_redirects=False, trust_env=False))


def png():
    out = io.BytesIO()
    Image.new("RGB", (16, 16), "white").save(out, "PNG")
    return out.getvalue()


def public_dns(monkeypatch):
    monkeypatch.setattr(p.socket, "getaddrinfo", lambda host, port, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))])


def test_create_uses_ark_roles_and_explicit_output(monkeypatch, model):
    def handler(request):
        assert str(request.url) == "https://proxy.example/api/v3/contents/generations/tasks"
        assert request.headers["authorization"] == "Bearer private-api-key"
        body = json.loads(request.content)
        assert body["duration"] == 9 and body["ratio"] == "9:16" and body["resolution"] == "720p"
        assert body["generate_audio"] is False
        assert [x.get("role") for x in body["content"]] == [None, "reference_image", "reference_video"]
        assert body["execution_expires_after"] == 86400
        return httpx.Response(200, json={"id": "cgt-test_123"})
    transport(monkeypatch, handler)
    assert p.create_video(model, "replace product", ["https://bucket.example/a.jpg"],
                          "https://bucket.example/b.mp4", 9, generate_audio=False) == "cgt-test_123"


@pytest.mark.parametrize("duration", [0, 3, 16, 4.2, True])
def test_invalid_duration_never_submits(model, duration):
    with pytest.raises(p.ProviderError):
        p.create_video(model, "x", ["https://example.com/a.jpg"], None, duration)


def test_chat_compatibility_is_not_video_compatibility(model):
    model.protocol = "openai"
    with pytest.raises(p.ProviderError, match="Chat"):
        p.create_video(model, "x", ["https://example.com/a.jpg"], None, 5)


@pytest.mark.parametrize("failure", ["timeout", "500", "408", "malformed", "missing_id"])
def test_uncertain_submission_does_not_retry_or_leak(monkeypatch, model, failure):
    calls = []
    def handler(request):
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout("private-api-key secret-signed-url", request=request)
        if failure in {"500", "408"}:
            return httpx.Response(int(failure), text="private-api-key secret-signed-url")
        if failure == "malformed":
            return httpx.Response(200, text="private-api-key secret-signed-url")
        return httpx.Response(200, json={"secret": "private-api-key"})
    transport(monkeypatch, handler)
    with pytest.raises(p.SubmissionUncertain) as error:
        p.create_video(model, "x", ["https://example.com/a.jpg"], None, 5)
    assert len(calls) == 1
    assert "private-api-key" not in str(error.value)
    assert "secret-signed-url" not in str(error.value)


def test_api_redirect_is_not_followed(monkeypatch, model):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(307, headers={"location": "https://evil.example/collect"})
    transport(monkeypatch, handler)
    with pytest.raises(p.ProviderError, match="重定向"):
        p.get_video(model, "cgt-example")
    assert len(calls) == 1


def test_internal_admin_proxy_allowed(monkeypatch, model):
    model.base_url = "http://127.0.0.1:8899/v1"
    model.protocol = "openai"
    def handler(request):
        assert request.url.host == "127.0.0.1"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"ok":true}'}}]})
    transport(monkeypatch, handler)
    assert p.analyze(model, "analyze", []) == {"ok": True}


def test_anthropic_vision_payload(monkeypatch, model):
    model.protocol = "anthropic"
    model.base_url = "https://proxy.example/v1"
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1/messages"
        assert request.headers["x-api-key"] == "private-api-key"
        assert request.headers["anthropic-version"] == "2023-06-01"
        assert "authorization" not in request.headers
        assert body["messages"][0]["content"][0]["source"]["media_type"] == "image/jpeg"
        return httpx.Response(200, json={"content": [{"type": "text", "text": '```json\n{"shots":[]}\n```'}]})
    transport(monkeypatch, handler)
    assert p.analyze(model, "describe", [b"jpeg-bytes"]) == {"shots": []}
    with pytest.raises(p.ProviderError, match="不提供图像编辑"):
        p.edit_image(model, png(), "white background")


def test_image_edit_multipart_and_base64(monkeypatch, model):
    model.protocol = "openai"
    picture = png()
    def handler(request):
        assert request.url.path.endswith("/images/edits")
        assert request.headers["content-type"].startswith("multipart/form-data")
        assert b'name="image"' in request.content and b'image/png' in request.content
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(picture).decode()}]})
    transport(monkeypatch, handler)
    assert p.edit_image(model, picture, "white background") == picture


def test_volcengine_image_edit_uses_image_input(monkeypatch, model):
    model.model_id = "doubao-seedream-4-5-251128"
    picture = png()
    def handler(request):
        body = json.loads(request.content)
        assert request.url.path.endswith("/images/generations")
        assert body["image"].startswith("data:image/png;base64,")
        assert body["size"] == "2K"
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(picture).decode()}]})
    transport(monkeypatch, handler)
    assert p.edit_image(model, picture, "white background") == picture


@pytest.mark.parametrize('protocol', ['openai', 'volcengine'])
def test_multi_image_edit_retains_scene_and_product_references(monkeypatch, model, protocol):
    model.protocol = protocol
    picture = png()
    def handler(request):
        if protocol == 'openai':
            assert request.content.count(b'name="image[]"') == 2
        else:
            body = json.loads(request.content)
            assert len(body['image']) == 2
            assert all(i.startswith('data:image/png;base64,') for i in body['image'])
        return httpx.Response(200, json={'data':[{'b64_json':base64.b64encode(picture).decode()}]})
    transport(monkeypatch, handler)
    assert p.edit_images(model, [picture,picture], 'replace all product parts') == picture


def test_transcription_upload(monkeypatch, model, tmp_path):
    model.protocol = "openai"
    file = tmp_path / "audio.mp3"
    file.write_bytes(b"test-audio")
    def handler(request):
        assert request.url.path.endswith("/audio/transcriptions")
        assert b'name="file"' in request.content and b'filename="audio.mp3"' in request.content
        return httpx.Response(200, json={"text": "Ol\u00e1 Brasil"})
    transport(monkeypatch, handler)
    assert p.transcribe(model, file) == "Ol\u00e1 Brasil"


def test_poll_hides_remote_errors(monkeypatch, model):
    transport(monkeypatch, lambda request: httpx.Response(200, json={
        "status": "failed", "error": {"message": "private-api-key https://secret?signature=x"}}))
    response = p.get_video(model, "cgt-example")
    assert response["status"] == "failed"
    assert response["video_url"] is None
    assert "private-api-key" not in response["error"]
    assert "signature" not in response["error"]


def test_audio_copyright_failure_keeps_reason_without_remote_secrets(monkeypatch, model):
    code = "OutputAudioSensitiveContentDetected.PolicyViolation"
    transport(monkeypatch, lambda request: httpx.Response(200, json={
        "status": "failed", "error": {"code": code, "message": "private-api-key https://secret?signature=x"}}))
    result = p.get_video(model, "cgt-example")
    assert code in result["error"] and "版权" in result["error"]
    assert "音乐或口播" in result["error"]
    assert "private-api-key" not in result["error"] and "signature" not in result["error"]


def test_unknown_code_and_raw_message_are_not_exposed(monkeypatch, model):
    transport(monkeypatch, lambda request: httpx.Response(200, json={
        "status": "failed", "error": {"code": "private-api-key", "message": "private-api-key"}}))
    assert "private-api-key" not in p.get_video(model, "cgt-example")["error"]


def test_immediate_audio_rejection_uses_same_safe_hint(monkeypatch, model):
    transport(monkeypatch, lambda request: httpx.Response(400, json={
        "error": {"code": "OutputAudioSensitiveContentDetected.PolicyViolation", "message": "private-api-key"}}))
    with pytest.raises(p.ProviderError, match="版权") as exc:
        p.create_video(model, "original audio", ["https://example.com/a.jpg"], None, 8)
    assert "private-api-key" not in str(exc.value)


@pytest.mark.parametrize("url", ["http://example.com/a", "https://localhost/a", "https://user:pass@example.com/a",
    "https://example.com:444/a", "file:///c:/secret", "https://metadata.google.internal/a"])
def test_media_rejects_invalid_hosts_before_request(monkeypatch, url):
    monkeypatch.setattr(p, "_client", lambda *args: pytest.fail("must not send a request"))
    with pytest.raises(p.ProviderError):
        p.download_media(url)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "100.100.100.200",
                                     "::1", "fc00::1", "::ffff:127.0.0.1", "224.0.0.1"])
def test_media_rejects_nonpublic_dns(monkeypatch, address):
    monkeypatch.setattr(p.socket, "getaddrinfo", lambda *args, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    with pytest.raises(p.ProviderError, match="公网"):
        p.download_media("https://untrusted.example/media")


def test_download_pins_dns_and_never_sends_credentials(monkeypatch):
    public_dns(monkeypatch)
    def handler(request):
        assert request.url.host == "93.184.216.34"
        assert request.headers["host"] == "cdn.example"
        assert request.extensions["sni_hostname"] == "cdn.example"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        return httpx.Response(200, content=b"video")
    transport(monkeypatch, handler)
    assert p.download_media("https://cdn.example/output.mp4?signature=private") == b"video"


def test_redirect_revalidated_and_cookie_not_forwarded(monkeypatch):
    public_dns(monkeypatch)
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(302, headers={"location": "https://localhost/secret", "set-cookie": "secret=x"})
    transport(monkeypatch, handler)
    with pytest.raises(p.ProviderError):
        p.download_media("https://cdn.example/media")
    assert len(calls) == 1


def test_download_stream_limit_without_content_length(monkeypatch):
    public_dns(monkeypatch)
    transport(monkeypatch, lambda request: httpx.Response(200, content=b"0123456789"))
    with pytest.raises(p.ProviderError, match="超过"):
        p.download_media("https://cdn.example/media", max_bytes=4)


def test_tos_objects_are_private_and_links_expire(monkeypatch):
    calls = {}
    class FakeClient:
        def __init__(self, *args):
            calls["init"] = args
        def put_object(self, bucket, key, **kwargs):
            calls["upload"] = (bucket, key, kwargs)
        def pre_signed_url(self, method, **kwargs):
            calls["sign"] = (method, kwargs)
            return SimpleNamespace(signed_url="https://bucket.example/file?signature=temporary")
    monkeypatch.setitem(sys.modules, "tos", SimpleNamespace(TosClientV2=FakeClient,
        ACLType=SimpleNamespace(ACL_Private="private"), HttpMethodType=SimpleNamespace(Http_Method_Get="GET")))
    link = p.publish_media({"endpoint": "tos-cn-beijing.volces.com", "region": "cn-beijing", "bucket": "private",
        "access_key_id": "ak", "secret_access_key": "sk", "url_ttl": 172800}, "job/id/file.mp4", b"x", "video/mp4")
    assert link.endswith("signature=temporary")
    assert calls["init"][2] == "https://tos-cn-beijing.volces.com"
    assert calls["upload"][2]["acl"] == "private"
    assert calls["sign"][1]["expires"] == 172800
