import io
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image
from sqlalchemy import func, select

from app import config
from app.db import Asset, Job, ModelConfig, Project, Segment, SessionLocal, User
from app.security import encrypt
from app.storage import add_asset


PASSWORD = "Test-safe-password-492!"


def bootstrap(client):
    response = client.post("/api/bootstrap", json={
        "username": "admin", "password": PASSWORD,
        "setup_token": (config.DATA_DIR / "setup.token").read_text().strip(),
    })
    assert response.status_code == 201, response.text
    return response.json()


def login(client, username="admin", password=PASSWORD):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    csrf = response.json()["csrf_token"]
    return {"X-CSRF-Token": csrf}


def create_user(client, headers, username):
    response = client.post("/api/users", json={"username": username, "password": PASSWORD}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def create_models():
    with SessionLocal() as db:
        vision = ModelConfig(name="Vision", kind="vision", protocol="openai", base_url="https://example.invalid/v1",
                             model_id="vision-test", api_key_cipher=encrypt("secret-vision"))
        video = ModelConfig(name="Video", kind="video", protocol="volcengine", base_url="https://example.invalid/api/v3",
                            model_id="seedance-test", api_key_cipher=encrypt("secret-video"))
        db.add_all([vision, video])
        db.commit()
        return {"vision_model_id": vision.id, "video_model_id": video.id}


def create_project(client, headers, **extra):
    response = client.post("/api/projects", json={"name": "Produto Brasil", **create_models(), **extra}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(buffer, "PNG")
    return buffer.getvalue()


def seed_asset(project_id, *, role="reference", data=b"0123456789", name="vídeo.mp4", mime="video/mp4"):
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        asset = add_asset(db, project, data, name, mime, role, {"duration": 8, "width": 720, "height": 1280, "has_audio": False})
        db.commit()
        return asset.id


def test_bootstrap_requires_local_secret_and_cannot_repeat(api_client):
    assert api_client.get("/api/bootstrap").json() == {"initialized": False}
    response = api_client.post("/api/bootstrap", json={"username": "admin", "password": PASSWORD, "setup_token": "incorrect"})
    assert response.status_code == 403
    admin = bootstrap(api_client)
    assert admin["role"] == "admin"
    assert not (config.DATA_DIR / "setup.token").exists()
    assert api_client.get("/api/bootstrap").json() == {"initialized": True}
    response = api_client.post("/api/bootstrap", json={"username": "intruder", "password": PASSWORD, "setup_token": "anything"})
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 1


def test_authentication_login_cookie_logout_and_expired_session(api_client):
    assert api_client.get("/api/projects").status_code == 401
    bootstrap(api_client)
    assert api_client.post("/api/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
    response = api_client.post("/api/auth/login", json={"username": "ADMIN", "password": PASSWORD})
    assert response.status_code == 200
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    assert api_client.get("/api/auth/me").json()["user"]["username"] == "admin"
    csrf = {"X-CSRF-Token": response.json()["csrf_token"]}
    assert api_client.post("/api/auth/logout", headers=csrf).status_code == 200
    assert api_client.get("/api/auth/me").status_code == 401
    login(api_client)
    from app.db import SessionToken
    with SessionLocal() as db:
        for session in db.scalars(select(SessionToken)):
            session.expires_at = 0
        db.commit()
    assert api_client.get("/api/auth/me").status_code == 401


def test_regular_user_cannot_manage_users_models_or_storage(api_client):
    bootstrap(api_client)
    admin_headers = login(api_client)
    user = create_user(api_client, admin_headers, "operator")
    create_models()
    headers = login(api_client, "operator")
    for url in ["/api/users", "/api/settings/storage"]:
        assert api_client.get(url).status_code == 403
    assert api_client.post("/api/users", headers=headers, json={"username": "rogue", "password": PASSWORD}).status_code == 403
    assert api_client.patch(f"/api/users/{user['id']}", headers=headers, json={"role": "admin"}).status_code == 403
    assert api_client.post("/api/models", headers=headers, json={
        "name": "Rogue", "kind": "vision", "protocol": "openai", "base_url": "https://example.invalid/v1", "model_id": "fake", "api_key": "secret",
    }).status_code == 403
    assert api_client.put("/api/settings/storage", headers=headers, json={"enabled": False}).status_code == 403
    models = api_client.get("/api/models").json()
    assert len(models) == 2
    for model in models:
        assert "api_key_cipher" not in model and "api_key" not in model and "base_url" not in model


def test_csrf_and_origin_protect_authenticated_writes(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    body = {"username": "created", "password": PASSWORD}
    assert api_client.post("/api/users", json=body).status_code == 403
    assert api_client.post("/api/users", json=body, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert api_client.post("/api/users", json=body, headers={**headers, "Origin": "https://attacker.invalid"}).status_code == 403
    assert api_client.post("/api/users", json=body, headers={**headers, "Origin": "http://testserver"}).status_code == 201
    assert api_client.get("/api/users").status_code == 200
    assert api_client.get("/api/users").headers["cache-control"] == "no-store"


def test_project_and_asset_isolation_and_default_brazil_options(api_client):
    bootstrap(api_client)
    admin_headers = login(api_client)
    create_user(api_client, admin_headers, "alice")
    create_user(api_client, admin_headers, "bob")
    alice_headers = login(api_client, "alice")
    project = create_project(api_client, alice_headers)
    assert project["options"] == {"site": "BR", "level": "balanced", "replicate_music": True,
                                  "replicate_voice": True, "reference_audio": True, "replicate_subtitles": True, "duration": None,
                                  "ratio": "9:16", "resolution": "720p"}
    upload = api_client.post(f"/api/projects/{project['id']}/assets", headers=alice_headers,
                             data={"role": "product"}, files={"file": ("produto.png", png(), "image/png")})
    assert upload.status_code == 201, upload.text
    asset = upload.json()
    assert api_client.get(asset["url"]).content == png()
    bob_headers = login(api_client, "bob")
    assert api_client.get("/api/projects").json() == []
    assert api_client.get(f"/api/projects/{project['id']}").status_code == 404
    assert api_client.get(asset["url"]).status_code == 404
    assert api_client.get(asset["url"], headers={"Range": "bytes=0-9"}).status_code == 404
    for action in ["analyze", "generate", "retry", "cancel"]:
        assert api_client.post(f"/api/projects/{project['id']}/{action}", headers=bob_headers).status_code == 404
    assert api_client.post(f"/api/projects/{project['id']}/assets", headers=bob_headers,
                           data={"role": "product"}, files={"file": ("fake.png", png(), "image/png")}).status_code == 404
    # Administrators may explicitly inspect a user's project for support.
    login(api_client)
    assert api_client.get(f"/api/projects/{project['id']}").status_code == 200
    assert api_client.get(asset["url"]).status_code == 200


def test_concurrent_analyze_requests_create_only_one_job(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project = create_project(api_client, headers)
    seed_asset(project["id"])
    seed_asset(project["id"], role="product", data=png(), name="produto.png", mime="image/png")
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: api_client.post(f"/api/projects/{project['id']}/analyze", headers=headers), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Job)) == 1
        assert db.get(Project, project["id"]).status == "analyzing"


@pytest.mark.parametrize("range_header, status, expected, content_range", [
    (None, 200, b"0123456789", None),
    ("bytes=0-3", 206, b"0123", "bytes 0-3/10"),
    ("bytes=4-", 206, b"456789", "bytes 4-9/10"),
    ("bytes=-3", 206, b"789", "bytes 7-9/10"),
    ("bytes=-99", 206, b"0123456789", "bytes 0-9/10"),
    ("bytes=7-99", 206, b"789", "bytes 7-9/10"),
    ("bytes=10-20", 416, b"", "bytes */10"),
    ("bytes=4-2", 416, b"", "bytes */10"),
    ("bytes=0-1,3-4", 416, b"", "bytes */10"),
    ("bytes=-0", 416, b"", "bytes */10"),
    ("items=0-1", 416, b"", "bytes */10"),
    ("bytes=oops", 416, b"", "bytes */10"),
])
def test_video_byte_ranges(api_client, range_header, status, expected, content_range):
    bootstrap(api_client)
    headers = login(api_client)
    project = create_project(api_client, headers)
    asset_id = seed_asset(project["id"])
    response = api_client.get(f"/api/assets/{asset_id}", headers={"Range": range_header} if range_header else {})
    assert response.status_code == status
    assert response.content == expected
    assert response.headers.get("content-range") == content_range
    if status != 416:
        assert response.headers["accept-ranges"] == "bytes"
        assert int(response.headers["content-length"]) == len(expected)
        assert response.headers["content-type"] == "video/mp4"
        assert "filename*=UTF-8''v%C3%ADdeo.mp4" in response.headers["content-disposition"]


def test_disabling_user_revokes_existing_session(api_client):
    bootstrap(api_client)
    admin_headers = login(api_client)
    user = create_user(api_client, admin_headers, "operator")
    login(api_client, "operator")
    user_cookie = api_client.cookies.get("vio_session")
    admin_headers = login(api_client)
    assert api_client.patch(f"/api/users/{user['id']}", json={"active": False}, headers=admin_headers).status_code == 200
    response = api_client.get("/api/auth/me", headers={"Cookie": f"vio_session={user_cookie}"})
    assert response.status_code == 401
    assert api_client.post("/api/auth/login", json={"username": "operator", "password": PASSWORD}).status_code == 401


def test_audio_options_change_preserves_failed_task_and_does_not_enqueue(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    p = create_project(api_client, headers)
    with SessionLocal() as db:
        project = db.get(Project, p['id'])
        project.status = 'failed'
        db.add(Segment(project_id=p['id'], index=0, status='failed', remote_id='cgt-existing', error='copyright'))
        db.commit()
    options = {'replicate_music': False, 'replicate_voice': True, 'reference_audio': False}
    r = api_client.patch(f"/api/projects/{p['id']}/audio-options", json=options, headers=headers)
    assert r.status_code == 200, r.text
    assert all(r.json()['options'][key] == value for key, value in options.items())
    assert r.json()['status'] == 'failed'
    assert r.json()['segments'][0]['remote_id'] == 'cgt-existing'
    assert r.json()['options']['replicate_subtitles'] is True
    assert not r.json()['jobs']
    assert api_client.patch(f"/api/projects/{p['id']}/audio-options", json=options).status_code == 403
    create_user(api_client, headers, 'other_user')
    other_headers = login(api_client, 'other_user')
    assert api_client.patch(f"/api/projects/{p['id']}/audio-options", json=options, headers=other_headers).status_code == 404


@pytest.mark.parametrize('segment_status', ['succeeded', 'submitting', 'submitted'])
def test_audio_options_cannot_change_submitted_or_successful_segments(api_client, segment_status):
    bootstrap(api_client)
    headers = login(api_client)
    p = create_project(api_client, headers)
    with SessionLocal() as db:
        db.get(Project, p['id']).status = 'needs_attention'
        db.add(Segment(project_id=p['id'], index=0, status=segment_status))
        db.commit()
    r = api_client.patch(f"/api/projects/{p['id']}/audio-options", json={'replicate_music':False,'replicate_voice':False,'reference_audio':False}, headers=headers)
    assert r.status_code == 409


@pytest.mark.parametrize('username,password', [
    ('甲', '123'),
    ('贺强', '123'),
    ('👩‍💻 !@#$% <用户> / "', 'x'),
    ('用' * 4096, '密' * 1024),
    (' ', ' '),
])
def test_nonempty_credentials_create_and_login_without_format_or_length_limits(api_client, username, password):
    bootstrap(api_client)
    headers = login(api_client)
    response = api_client.post('/api/users', headers=headers, json={'username':username, 'password':password})
    assert response.status_code == 201, response.text
    assert response.json()['username'] == username
    login(api_client, username, password)
    assert api_client.get('/api/auth/me').json()['user']['id'] == response.json()['id']


@pytest.mark.parametrize('username,password', [('', '123'), ('甲', '')])
def test_empty_credentials_still_rejected(api_client, username, password):
    bootstrap(api_client)
    headers = login(api_client)
    body = {'username':username, 'password':password}
    assert api_client.post('/api/users', headers=headers, json=body).status_code == 422
    assert api_client.post('/api/auth/login', json=body).status_code == 422


def test_short_password_reset_and_empty_means_no_change_in_form(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    user = create_user(api_client, headers, '甲')
    route = f"/api/users/{user['id']}"
    assert api_client.patch(route, headers=headers, json={'password':''}).status_code == 422
    assert api_client.patch(route, headers=headers, json={'password':'123'}).status_code == 200
    # Editing a user with an empty password form omits the password field.
    assert api_client.patch(route, headers=headers, json={'active':True}).status_code == 200
    login(api_client, '甲', '123')


def test_initial_admin_accepts_single_character_credentials(api_client):
    response = api_client.post('/api/bootstrap', json={
        'username':'管', 'password':'1', 'setup_token':(config.DATA_DIR / 'setup.token').read_text().strip()})
    assert response.status_code == 201
    login(api_client, '管', '1')


def test_cli_reset_accepts_short_password(api_client, monkeypatch):
    from app import cli
    import sys
    bootstrap(api_client)
    answers = iter(['123', '123'])
    monkeypatch.setattr(cli, 'getpass', lambda prompt: next(answers))
    monkeypatch.setattr(sys, 'argv', ['app.cli', 'reset-password', 'admin'])
    cli.main()
    login(api_client, 'admin', '123')


def test_frontend_assets_revalidate_and_change_url_after_update(api_client, monkeypatch, tmp_path):
    import re

    first = api_client.get('/')
    assert first.status_code == 200
    assert first.headers['cache-control'] == 'no-cache, must-revalidate'
    script_url = re.search(r'src="([^"]+app\.js\?v=[a-f0-9]+)"', first.text).group(1)
    script = api_client.get(script_url)
    assert script.status_code == 200
    assert script.headers['cache-control'] == 'no-cache, must-revalidate'
    cached = api_client.get(script_url, headers={'If-None-Match': script.headers['etag']})
    assert cached.status_code == 304
    assert cached.headers['cache-control'] == 'no-cache, must-revalidate'

    # Simulate an updated deployment without modifying the real frontend files.
    static_dir = tmp_path / 'app' / 'static'
    static_dir.mkdir(parents=True)
    for name in ('index.html', 'app.js', 'style.css'):
        content = (config.ROOT / 'app' / 'static' / name).read_bytes()
        (static_dir / name).write_bytes(content + (b'\n// updated release\n' if name == 'app.js' else b''))
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    updated = api_client.get('/')
    assert script_url not in updated.text
    assert re.search(r'src="/static/app\.js\?v=[a-f0-9]+"', updated.text)


def completed_project(client, headers):
    project = create_project(client, headers)
    first = seed_asset(project["id"], role="generated_segment", name="first.mp4")
    second = seed_asset(project["id"], role="generated_segment", name="second.mp4")
    output = seed_asset(project["id"], role="output", name="final.mp4")
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.status, row.output_asset_id = "needs_review", output
        row.analysis = {"product_identity": "target", "segments": [
            {"index": 0, "start": 0, "duration": 4, "prompt": "target close-up"},
            {"index": 1, "start": 4, "duration": 4, "prompt": "target background"},
        ]}
        records = [Segment(project_id=row.id, index=i, status="succeeded", remote_id=f"remote-{i}",
                           asset_id=asset_id, attempts=1, quality={"status": "issues", "summary": "old product"})
                   for i, asset_id in enumerate([first, second])]
        db.add_all(records)
        db.commit()
        return project["id"], [record.id for record in records], [first, second], output


def test_quality_review_only_requires_vision_and_preserves_results(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project_id, segments, assets, output = completed_project(api_client, headers)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        db.get(ModelConfig, project.video_model_id).enabled = False
        db.commit()
    route = f"/api/projects/{project_id}/review"
    assert api_client.post(route).status_code == 403
    response = api_client.post(route, headers=headers)
    assert response.status_code == 200, response.text
    assert api_client.post(route, headers=headers).status_code == 409
    detail = api_client.get(f"/api/projects/{project_id}").json()
    assert detail["status"] == "reviewing"
    assert detail["output_asset_id"] == output
    assert detail["jobs"][0]["action"] == "review"
    assert [item["asset_id"] for item in detail["segments"]] == assets
    assert detail["segments"][0]["quality"]["status"] == "issues"


def test_quality_review_requires_complete_results_and_plan(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project_id, segments, _, _ = completed_project(api_client, headers)
    with SessionLocal() as db:
        db.get(Segment, segments[1]).asset_id = None
        db.commit()
    assert api_client.post(f"/api/projects/{project_id}/review", headers=headers).status_code == 422
    detail = api_client.get(f"/api/projects/{project_id}").json()
    assert detail["jobs"] == [] and detail["status"] == "needs_review"


def test_retry_of_failed_review_requeues_review_without_video_or_storage(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project_id, _, assets, output = completed_project(api_client, headers)
    with SessionLocal() as db:
        row = db.get(Project, project_id)
        row.status = "failed"
        db.get(ModelConfig, row.video_model_id).enabled = False
        db.add(Job(project_id=project_id, action="review", status="failed", created_at=time.time() - 60))
        db.commit()
    response = api_client.post(f"/api/projects/{project_id}/retry", headers=headers)
    assert response.status_code == 200, response.text
    detail = api_client.get(f"/api/projects/{project_id}").json()
    assert detail["status"] == "reviewing" and detail["jobs"][-1]["action"] == "review"
    assert [segment["asset_id"] for segment in detail["segments"]] == assets
    assert detail["output_asset_id"] == output


def test_regenerate_preserves_history_output_and_other_segment(api_client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "storage_settings", lambda db: {})
    bootstrap(api_client)
    headers = login(api_client)
    project_id, segments, assets, output = completed_project(api_client, headers)
    response = api_client.post(f"/api/segments/{segments[0]}/regenerate", headers=headers,
                               json={"strategy": "adapt", "repair_prompt": "Replace all visible product parts."})
    assert response.status_code == 200, response.text
    detail = api_client.get(f"/api/projects/{project_id}").json()
    first, second = detail["segments"]
    assert first["asset_id"] is None and first["remote_id"] is None
    assert first["status"] == "pending" and first["quality"] == {}
    assert first["attempts"] == 1
    assert first["history"] == [{"asset_id": assets[0], "remote_id": "remote-0", "attempts": 1,
                                 "quality": {"status": "issues", "summary": "old product"}}]
    assert second["asset_id"] == assets[1] and second["remote_id"] == "remote-1"
    assert second["quality"]["status"] == "issues"
    assert detail["output_asset_id"] == output
    assert detail["analysis"]["segments"][0]["strategy"] == "adapt"
    assert api_client.get(f"/api/assets/{assets[0]}").status_code == 200
    assert detail["jobs"][0]["action"] == "generate"


def test_failed_regenerate_queue_rolls_back_every_mutation(api_client, monkeypatch):
    from app import main
    def invalid_storage(db):
        raise ValueError("未配置存储")
    monkeypatch.setattr(main, "storage_settings", invalid_storage)
    bootstrap(api_client)
    headers = login(api_client)
    project_id, segments, assets, output = completed_project(api_client, headers)
    before = api_client.get(f"/api/projects/{project_id}").json()
    response = api_client.post(f"/api/segments/{segments[0]}/regenerate", headers=headers,
                               json={"strategy": "adapt", "repair_prompt": "Use target shape."})
    assert response.status_code == 422
    assert api_client.get(f"/api/projects/{project_id}").json() == before


def test_concurrent_segment_regenerations_enqueue_only_one_repair(api_client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "storage_settings", lambda db: {})
    bootstrap(api_client)
    headers = login(api_client)
    project_id, segments, _, _ = completed_project(api_client, headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: api_client.post(f"/api/segments/{segments[0]}/regenerate", headers=headers,
                            json={"strategy": "direct", "repair_prompt": "Replace background product too."}), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    detail = api_client.get(f"/api/projects/{project_id}").json()
    assert len(detail["jobs"]) == 1 and len(detail["segments"][0]["history"]) == 1


def test_ordinary_retry_preserves_existing_segment_results_and_quality(api_client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "storage_settings", lambda db: {})
    bootstrap(api_client)
    headers = login(api_client)
    project_id, _, assets, output = completed_project(api_client, headers)
    with SessionLocal() as db:
        db.get(Project, project_id).status = "failed"
        db.commit()
    assert api_client.post(f"/api/projects/{project_id}/retry", headers=headers).status_code == 200
    detail = api_client.get(f"/api/projects/{project_id}").json()
    assert [item["asset_id"] for item in detail["segments"]] == assets
    assert all(item["quality"]["status"] == "issues" and not item["history"] for item in detail["segments"])
    assert detail["output_asset_id"] == output


def test_segment_repairs_require_owner_and_enforce_attempt_limit(api_client):
    bootstrap(api_client)
    admin_headers = login(api_client)
    create_user(api_client, admin_headers, "alice")
    create_user(api_client, admin_headers, "bob")
    headers = login(api_client, "alice")
    project_id, segments, _, _ = completed_project(api_client, headers)
    body = {"strategy": "direct", "repair_prompt": "Fix product."}
    with SessionLocal() as db:
        db.get(Segment, segments[0]).attempts = 3
        db.commit()
    assert api_client.post(f"/api/segments/{segments[0]}/regenerate", headers=headers, json=body).status_code == 409
    assert api_client.post(f"/api/segments/{segments[1]}/regenerate", json=body).status_code == 403
    bob_headers = login(api_client, "bob")
    for endpoint in ["regenerate", "strategy"]:
        assert api_client.post(f"/api/segments/{segments[0]}/{endpoint}", headers=bob_headers, json=body).status_code == 404
    assert api_client.post(f"/api/projects/{project_id}/review", headers=bob_headers).status_code == 404


def test_failed_keyframe_strategy_can_be_saved_without_queueing(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project_id, segments, _, _ = completed_project(api_client, headers)
    with SessionLocal() as db:
        record = db.get(Segment, segments[0])
        record.asset_id, record.remote_id, record.status = None, None, "pending"
        record.quality = {"keyframe_status": "uncertain", "keyframe_error": "timeout", "summary": "keep me"}
        db.get(Project, project_id).status = "needs_attention"
        db.commit()
    route = f"/api/segments/{segments[0]}/strategy"
    assert api_client.post(route, headers=headers, json={"strategy": "direct", "repair_prompt": "  "}).status_code == 422
    # Keyframe generation cannot be selected without an enabled image model.
    assert api_client.post(route, headers=headers, json={"strategy": "keyframe", "repair_prompt": "Fix frame."}).status_code == 422
    response = api_client.post(route, headers=headers, json={"strategy": "adapt", "repair_prompt": "Use a simpler target-product interaction."})
    assert response.status_code == 200, response.text
    assert response.json()["segments"][0]["quality"] == {"summary": "keep me"}
    assert response.json()["analysis"]["segments"][0]["strategy"] == "adapt"
    assert response.json()["jobs"] == []
    with SessionLocal() as db:
        db.get(Segment, segments[0]).remote_id = "already-submitted"
        db.commit()
    assert api_client.post(route, headers=headers, json={"strategy": "direct", "repair_prompt": "Fix."}).status_code == 409


@pytest.mark.parametrize("strategy", ["needs_reference", "keyframe"])
def test_generation_checks_missing_material_or_image_model_before_queue(api_client, strategy):
    bootstrap(api_client)
    headers = login(api_client)
    project = create_project(api_client, headers)
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.status = "ready"
        row.analysis = {"segments": [{"index": 0, "start": 0, "duration": 4, "prompt": "show target", "strategy": strategy}]}
        db.commit()
    response = api_client.post(f"/api/projects/{project['id']}/generate", headers=headers)
    assert response.status_code == 422
    assert "补图" in response.text if strategy == "needs_reference" else "image" in response.text
    assert api_client.get(f"/api/projects/{project['id']}").json()["jobs"] == []


def test_supplemental_products_invalidate_only_derived_images_and_analysis(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project = create_project(api_client, headers)
    original = seed_asset(project["id"], role="product", data=png(), name="original.png", mime="image/png")
    normalized = seed_asset(project["id"], role="normalized_product")
    optimized = seed_asset(project["id"], role="optimized_product")
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.analysis, row.status = {"summary": "old plan"}, "ready"
        db.commit()
    response = api_client.post(f"/api/projects/{project['id']}/assets", headers=headers, data={"role": "product"},
                               files={"file": ("extra.png", png(), "image/png")})
    assert response.status_code == 201, response.text
    detail = api_client.get(f"/api/projects/{project['id']}").json()
    assert detail["status"] == "draft" and detail["analysis"] is None
    assert {item["id"] for item in detail["assets"]} == {original, response.json()["id"]}
    assert api_client.get(f"/api/assets/{original}").content == png()
    assert api_client.get(f"/api/assets/{normalized}").status_code == 404
    assert api_client.get(f"/api/assets/{optimized}").status_code == 404


def test_supplemental_product_is_blocked_after_generation_or_during_job(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project = create_project(api_client, headers)
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.status = "failed"
        record = Segment(project_id=row.id, index=0)
        db.add(record)
        db.commit()
        segment_id = record.id
    def upload():
        return api_client.post(f"/api/projects/{project['id']}/assets", headers=headers, data={"role": "product"},
                               files={"file": ("extra.png", png(), "image/png")})
    assert upload().status_code == 409
    with SessionLocal() as db:
        db.delete(db.get(Segment, segment_id))
        db.add(Job(project_id=project["id"], action="analyze", status="queued"))
        db.commit()
    assert upload().status_code == 409


def test_ready_project_can_explicitly_reanalyze_but_invalid_request_preserves_plan(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project = create_project(api_client, headers)
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.status, row.analysis = "ready", {"summary": "existing plan"}
        db.commit()
    route = f"/api/projects/{project['id']}/analyze"
    assert api_client.post(route, headers=headers).status_code == 422
    assert api_client.get(f"/api/projects/{project['id']}").json()["analysis"] == {"summary": "existing plan"}
    seed_asset(project["id"])
    seed_asset(project["id"], role="product", data=png(), name="original.png", mime="image/png")
    assert api_client.post(route, headers=headers).status_code == 200
    detail = api_client.get(f"/api/projects/{project['id']}").json()
    assert detail["analysis"] is None and detail["status"] == "analyzing"


def test_fresh_analysis_invalidates_receipts_atomically_and_retry_preserves_them(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project = create_project(api_client, headers)
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.status = "failed"
        receipt = add_asset(db, row, b'{"text":"original analysis"}', "analysis.json", "application/json", "analysis_raw", {"fingerprint": "test", "superseded": False})
        db.commit()
        receipt_id = receipt.id
    route = f"/api/projects/{project['id']}"
    assert api_client.post(route + "/analyze", headers=headers).status_code == 422
    with SessionLocal() as db:
        assert not db.get(Asset, receipt_id).meta["superseded"]
    seed_asset(project["id"])
    seed_asset(project["id"], role="product", data=png(), name="original.png", mime="image/png")
    assert api_client.post(route + "/retry", headers=headers).status_code == 200
    with SessionLocal() as db:
        assert not db.get(Asset, receipt_id).meta["superseded"]
        db.get(Project, project["id"]).status = "failed"
        db.scalar(select(Job).where(Job.project_id == project["id"])).status = "failed"
        db.commit()
    assert api_client.post(route + "/analyze", headers=headers).status_code == 200
    with SessionLocal() as db:
        assert db.get(Asset, receipt_id).meta["superseded"]
        assert db.get(Asset, receipt_id).data == b'{"text":"original analysis"}'


def test_quality_migration_backfills_existing_segments(tmp_path):
    import importlib.util
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = config.ROOT / "migrations" / "versions" / "f2c49a71e602_product_quality.py"
    spec = importlib.util.spec_from_file_location("quality_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'migration.db').as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE segments (id TEXT PRIMARY KEY, status TEXT, remote_id TEXT, asset_id TEXT)")
        connection.exec_driver_sql("INSERT INTO segments VALUES ('old', 'succeeded', 'remote-1', 'asset-1'), ('pending', 'pending', NULL, NULL)")
        module.op = Operations(MigrationContext.configure(connection))
        module.upgrade()
        old = connection.execute(sa.text("SELECT * FROM segments WHERE id='old'")).mappings().one()
        assert old["asset_id"] == "asset-1" and old["remote_id"] == "remote-1"
        assert old["quality"] == "{}" and old["history"] == "[]" and old["attempts"] == 1
        assert connection.scalar(sa.text("SELECT attempts FROM segments WHERE id='pending'")) == 0
    engine.dispose()


def editable_project_plan(client, headers):
    project = create_project(client, headers)
    plan = {"segments": [
        {"index": 0, "start": 0, "duration": 4, "prompt": "front view", "strategy": "direct", "shot_indices": [99]},
        {"index": 1, "start": 4, "duration": 4, "prompt": "supported interaction", "strategy": "adapt", "shot_indices": [99]},
    ], "shots": [
        {"start": 0, "end": 3, "strategy": "needs_reference"},
        {"start": 3, "end": 6, "strategy": "needs_reference"},
        {"start": 6, "end": 8, "strategy": "needs_reference"},
    ]}
    with SessionLocal() as db:
        row = db.get(Project, project["id"])
        row.status, row.analysis = "ready", plan
        db.commit()
    return project["id"], plan


def test_editing_plan_rederives_shot_links_and_preserves_explicit_strategies(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project_id, plan = editable_project_plan(api_client, headers)
    response = api_client.put(f"/api/projects/{project_id}/plan", headers=headers, json={"analysis": plan})
    assert response.status_code == 200, response.text
    segments = response.json()["analysis"]["segments"]
    assert [segment["shot_indices"] for segment in segments] == [[0, 1], [1, 2]]
    assert [segment["strategy"] for segment in segments] == ["direct", "adapt"]
    plan["shots"][1]["end"] = 4
    plan["shots"][2]["start"] = 4
    response = api_client.put(f"/api/projects/{project_id}/plan", headers=headers, json={"analysis": plan})
    assert response.status_code == 200
    assert [segment["shot_indices"] for segment in response.json()["analysis"]["segments"]] == [[0, 1], [2]]


@pytest.mark.parametrize("start,end", [(0, 0), (7, 8.2), (8.1, 8.2), (-1, 3)])
def test_editing_plan_rejects_empty_or_out_of_range_shots(api_client, start, end):
    bootstrap(api_client)
    headers = login(api_client)
    project_id, plan = editable_project_plan(api_client, headers)
    before = api_client.get(f"/api/projects/{project_id}").json()["analysis"]
    plan["shots"] = [{"start": start, "end": end}]
    response = api_client.put(f"/api/projects/{project_id}/plan", headers=headers, json={"analysis": plan})
    assert response.status_code == 422
    assert api_client.get(f"/api/projects/{project_id}").json()["analysis"] == before


def test_generate_checks_vision_is_enabled_before_queuing(api_client, monkeypatch):
    from app import main
    monkeypatch.setattr(main, "storage_settings", lambda db: {})
    bootstrap(api_client)
    headers = login(api_client)
    project_id, _ = editable_project_plan(api_client, headers)
    with SessionLocal() as db:
        project = db.get(Project, project_id)
        db.get(ModelConfig, project.vision_model_id).enabled = False
        db.commit()
    response = api_client.post(f"/api/projects/{project_id}/generate", headers=headers)
    assert response.status_code == 422 and "vision" in response.text
    detail = api_client.get(f"/api/projects/{project_id}").json()
    assert detail["status"] == "ready" and not detail["jobs"]


def test_confirmed_failed_video_can_change_strategy_without_losing_attempts(api_client):
    bootstrap(api_client)
    headers = login(api_client)
    project_id, segments, _, _ = completed_project(api_client, headers)
    with SessionLocal() as db:
        record = db.get(Segment, segments[0])
        record.asset_id, record.remote_id, record.status = None, 'cgt-failed', 'failed'
        record.error, record.attempts = 'confirmed provider failure', 2
        db.get(Project, project_id).status = 'failed'
        db.commit()
    response = api_client.post(f'/api/segments/{segments[0]}/strategy', headers=headers,
        json={'strategy':'adapt', 'repair_prompt':'Change unsupported operation.'})
    assert response.status_code == 200, response.text
    record = response.json()['segments'][0]
    assert record['remote_id'] is None and record['status'] == 'pending'
    assert record['attempts'] == 2 and record['history'][-1]['remote_id'] == 'cgt-failed'
    assert not response.json()['jobs']
