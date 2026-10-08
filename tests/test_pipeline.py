import io
import copy
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
from PIL import Image
from sqlalchemy import select

from app import media, pipeline, providers
from app.db import Asset, Job, ModelConfig, Project, Segment, Setting, User
from app.schemas import Options
from app.security import encrypt, hash_password
from app.storage import add_asset

REAL_CREATE_VIDEO = providers.create_video
REAL_GET_VIDEO = providers.get_video


@pytest.fixture
def workflow(db_session, tmp_path, monkeypatch):
    db = db_session
    user = User(username="maker", password_hash=hash_password("test-only-password"))
    vision = ModelConfig(name="Test vision", kind="vision", protocol="openai", base_url="https://example.com/v1", model_id="vision", api_key_cipher=encrypt("test"))
    video = ModelConfig(name="Test video", kind="video", protocol="volcengine", base_url="https://example.com/api/v3", model_id="doubao-seedance-2-0-260128", api_key_cipher=encrypt("test"), price_per_second=0.5)
    db.add_all([user, vision, video])
    db.flush()
    p = Project(owner_id=user.id, name="Produto brasileiro", vision_model_id=vision.id, video_model_id=video.id,
                options=Options(resolution="480p").model_dump(), product_description="一只绿色杯子")
    db.add(p)
    db.flush()
    source = tmp_path / "source.mp4"
    subprocess.run([media.ffmpeg_path(), "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=180x320:r=30:d=16", "-f", "lavfi", "-i", "sine=frequency=440:duration=16", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(source)], check=True, capture_output=True)
    picture = io.BytesIO()
    Image.new("RGB", (720, 720), "green").save(picture, "JPEG")
    add_asset(db, p, source.read_bytes(), "reference.mp4", "video/mp4", "reference", media.probe(source))
    add_asset(db, p, picture.getvalue(), "product.jpg", "image/jpeg", "product")
    db.add(Setting(key="storage", value={"enabled": True, "endpoint": "https://example.com", "region": "cn-beijing", "bucket": "testing", "access_key_id": "test", "secret_cipher": encrypt("test"), "url_ttl": 86400}))
    db.commit()
    output = tmp_path / "generated.mp4"
    media.cut_reference(source, output, 0, 8, keep_audio=False)
    analyze = Mock(return_value={"status": "pass", "issues": [], "summary": "分镜分析", "product_identity": "绿色杯子", "risks": [], "image_assessment": "图片可用", "shots": [
        {"start":0,"end":8,"description":"杯子特写","product_visibility":"full"},
        {"start":8,"end":16,"description":"旋转杯子","product_visibility":"full"}], "segments": [
        {"prompt": "Show the green cup close up", "voiceover": "Conheça seu novo copo.", "subtitle": "Seu novo copo"},
        {"prompt": "Slowly rotate the green cup", "voiceover": "Feito para o seu dia.", "subtitle": "Para o seu dia"}]})
    submit = Mock(side_effect=["task-1", "task-2"])
    query = Mock(return_value={"status": "succeeded", "video_url": "https://example.com/output.mp4", "error": None})
    monkeypatch.setattr(providers, "analyze", analyze)
    monkeypatch.setattr(providers, "create_video", submit)
    monkeypatch.setattr(providers, "get_video", query)
    monkeypatch.setattr(providers, "publish_media", Mock(return_value="https://example.com/signed"))
    monkeypatch.setattr(providers, "download_media", Mock(return_value=output.read_bytes()))
    return db, p, analyze, submit, query, tmp_path


def run(db, project, action):
    job = Job(project_id=project.id, action=action)
    project.status = "analyzing" if action == "analyze" else "generating"
    db.add(job)
    db.commit()
    pipeline.Worker().run_job(job.id)
    db.expire_all()
    return db.get(Job, job.id), db.get(Project, project.id)


def test_real_ffmpeg_end_to_end_with_mocked_paid_services(workflow):
    db, p, analyze, submit, query, tmp_path = workflow
    job, p = run(db, p, "analyze")
    assert job.status == "succeeded", job.error
    assert p.status == "ready"
    assert [s["duration"] for s in p.analysis["segments"]] == [8, 8]
    assert p.analysis["estimated_cost"] == 8
    job, p = run(db, p, "generate")
    assert job.status == "succeeded", job.error
    assert p.status == "completed" and p.output_asset_id
    assert submit.call_count == 2
    assert "Brazilian Portuguese" in submit.call_args_list[0].args[1]
    assert "previous generated clip" in submit.call_args_list[1].args[1]
    output = db.get(Asset, p.output_asset_id)
    path = tmp_path / "result.mp4"
    path.write_bytes(output.data)
    assert abs(media.probe(path)["duration"] - 16) < 0.1
    assert media.probe(path)["width"] == 480
    assert len(list(db.scalars(select(Asset).where(Asset.project_id == p.id, Asset.role == "segment")))) == 2


def test_uncertain_submission_is_never_automatically_resubmitted(workflow):
    db, p, _, submit, query, _ = workflow
    _, p = run(db, p, "analyze")
    submit.side_effect = providers.SubmissionUncertain("unknown")
    job, p = run(db, p, "generate")
    assert job.status == "needs_attention"
    segment = db.scalar(select(Segment).where(Segment.project_id == p.id, Segment.index == 0))
    assert segment.status == "submitting" and segment.remote_id is None
    job, p = run(db, p, "generate")
    assert job.status == "needs_attention" and submit.call_count == 1
    assert query.call_count == 0


def test_retry_reuses_recorded_remote_task(workflow):
    db, p, _, submit, query, _ = workflow
    _, p = run(db, p, "analyze")
    query.side_effect = providers.ProviderError("temporary query failure")
    job, p = run(db, p, "generate")
    assert job.status == "failed" and submit.call_count == 1
    segment = db.scalar(select(Segment).where(Segment.project_id == p.id, Segment.index == 0))
    assert segment.remote_id == "task-1"
    query.side_effect = None
    job, p = run(db, p, "generate")
    assert job.status == "succeeded", job.error
    assert submit.call_count == 2  # second clip only; first clip was not submitted twice
    assert query.call_args_list[1].args[1] == "task-1"


def test_cancelled_job_never_submits(workflow):
    db, p, analyze, submit, _, _ = workflow
    job = Job(project_id=p.id, action="analyze", cancel_requested=True)
    db.add(job)
    db.commit()
    pipeline.Worker().run_job(job.id)
    db.expire_all()
    assert db.get(Job, job.id).status == "needs_attention"
    analyze.assert_not_called()
    submit.assert_not_called()


@pytest.mark.parametrize('music,voice,reference,expected_audio', [(False,True,False,False),(False,False,True,False),(True,True,True,True)])
def test_reference_audio_and_generated_audio_are_separate(workflow, monkeypatch, music, voice, reference, expected_audio):
    db, p, _, submit, _, tmp_path = workflow
    _, p = run(db, p, 'analyze')
    p.options = {**p.options, 'replicate_music':music, 'replicate_voice':voice, 'reference_audio':reference}
    db.commit()
    uploaded = []
    def publish(settings, key, data, mime):
        if mime == 'video/mp4':
            path = tmp_path / 'submitted-reference.mp4'
            path.write_bytes(data)
            uploaded.append(media.probe(path)['has_audio'])
        return 'https://example.com/signed'
    monkeypatch.setattr(providers, 'publish_media', publish)
    submit.side_effect = providers.ProviderError('stop after capturing request')
    run(db, p, 'generate')
    assert uploaded == [expected_audio]
    assert submit.call_args.args[7] is (music or voice)
    prompt = submit.call_args.args[1]
    if not music:
        assert 'No background music' in prompt
    if not reference:
        assert 'reference video is visual-only' in prompt


def test_quality_issue_preserves_output_without_automatic_regeneration(workflow):
    db, p, analyze, submit, _, _ = workflow
    _, p = run(db, p, 'analyze')
    analyze.side_effect = [
        {'status': 'issues', 'summary': '局部混合旧产品', 'issues': [
            {'time': 2, 'category': 'mixed_identity', 'severity': 'error', 'description': '把手结构错误', 'suggestion': '使用关键画面'}]},
        {'status': 'pass', 'summary': '抽样未发现问题', 'issues': []},
    ]
    job, p = run(db, p, 'generate')
    assert job.status == 'succeeded', job.error
    assert p.status == 'needs_review' and p.output_asset_id
    assert submit.call_count == 2
    records = list(db.scalars(select(Segment).where(Segment.project_id == p.id).order_by(Segment.index)))
    assert records[0].quality['issues'][0]['time'] == 2
    assert records[0].attempts == 1
    assert 'previous generated clip' not in submit.call_args_list[1].args[1]
    assert len(submit.call_args_list[1].args[2]) == 1


@pytest.mark.parametrize('response', [
    {'status': 'pass', 'issues': [{'time': 900, 'category': 'geometry', 'description': 'bad'}]},
    {'unexpected': 'invalid response'},
])
def test_invalid_quality_report_never_marks_video_as_passed(workflow, response):
    db, p, analyze, submit, _, _ = workflow
    _, p = run(db, p, 'analyze')
    analyze.return_value = response
    job, p = run(db, p, 'generate')
    assert job.status == 'succeeded', job.error
    assert p.status == 'needs_review' and p.output_asset_id
    assert submit.call_count == 2
    assert all(s.quality['status'] == 'uncertain' for s in db.scalars(select(Segment).where(Segment.project_id == p.id)))


def test_review_only_checks_existing_assets_and_never_generates(workflow):
    db, p, analyze, submit, query, _ = workflow
    _, p = run(db, p, 'analyze')
    _, p = run(db, p, 'generate')
    output_id = p.output_asset_id
    submit.reset_mock(); query.reset_mock()
    analyze.return_value = {'status':'uncertain', 'summary':'图片缺少侧面', 'issues':[]}
    job, p = run(db, p, 'review')
    assert job.status == 'succeeded', job.error
    assert p.status == 'needs_review' and p.output_asset_id == output_id
    submit.assert_not_called(); query.assert_not_called()


def test_local_repair_reuses_other_clips_and_keeps_old_assets(workflow):
    db, p, _, submit, _, _ = workflow
    _, p = run(db, p, 'analyze')
    _, p = run(db, p, 'generate')
    old_output = p.output_asset_id
    records = list(db.scalars(select(Segment).where(Segment.project_id == p.id).order_by(Segment.index)))
    old_first, old_second = [s.asset_id for s in records]
    first = records[0]
    first.history = [{'asset_id': first.asset_id, 'remote_id':first.remote_id, 'quality':first.quality, 'attempts':first.attempts}]
    first.asset_id = first.remote_id = None
    first.quality = {}; first.status = 'pending'
    db.commit()
    submit.side_effect = ['task-repair']
    job, p = run(db, p, 'generate')
    assert job.status == 'succeeded', job.error
    assert submit.call_count == 3
    assert records[0].asset_id != old_first and records[1].asset_id == old_second
    assert p.output_asset_id != old_output
    assert db.get(Asset, old_first) and db.get(Asset, old_output)
    assert records[0].attempts == 2 and records[1].attempts == 1


def test_missing_reference_stops_before_any_video_submission(workflow):
    db, p, _, submit, _, _ = workflow
    _, p = run(db, p, 'analyze')
    plan = copy.deepcopy(p.analysis)
    plan['segments'][0]['strategy'] = 'needs_reference'
    p.analysis = plan
    db.commit()
    job, p = run(db, p, 'generate')
    assert job.status == 'needs_attention'
    submit.assert_not_called()


def keyframe_plan(db, p):
    model = ModelConfig(name='Edit',kind='image',protocol='openai',base_url='https://example.com/v1',model_id='edit')
    db.add(model);db.flush()
    p.image_model_id = model.id
    plan = copy.deepcopy(p.analysis)
    plan['segments'][0]['strategy'] = 'keyframe'
    p.analysis = plan
    db.commit()


def test_rejected_keyframe_is_saved_and_retry_does_not_repeat_image_charge(workflow, monkeypatch):
    db, p, analyze, submit, _, _ = workflow
    _, p = run(db, p, 'analyze')
    keyframe_plan(db, p)
    image = db.scalar(select(Asset).where(Asset.project_id == p.id, Asset.role == 'product')).data
    edit = Mock(return_value=image)
    monkeypatch.setattr(providers,'edit_images',edit)
    analyze.return_value = {'matches':False, 'reason':'仍有原产品把手'}
    job, p = run(db, p, 'generate')
    assert job.status == 'needs_attention', job.error
    record = db.scalar(select(Segment).where(Segment.project_id == p.id, Segment.index == 0))
    assert record.quality['keyframe_status'] == 'rejected'
    assert db.get(Asset, record.quality['keyframe_asset_id'])
    assert record.attempts == 0
    job, p = run(db, p, 'generate')
    assert job.status == 'needs_attention'
    assert edit.call_count == 1
    submit.assert_not_called()


def test_approved_keyframe_uses_scene_and_product_images_without_old_video(workflow, monkeypatch):
    db, p, analyze, submit, _, _ = workflow
    _, p = run(db, p, 'analyze')
    keyframe_plan(db, p)
    image = db.scalar(select(Asset).where(Asset.project_id == p.id, Asset.role == 'product')).data
    edit = Mock(return_value=image)
    monkeypatch.setattr(providers,'edit_images',edit)
    analyze.return_value = {'matches':True, 'reason':'结构一致', 'status':'pass', 'issues':[]}
    job, p = run(db, p, 'generate')
    assert job.status == 'succeeded', job.error
    assert len(edit.call_args.args[1]) == 2
    assert submit.call_args_list[0].args[3] is None
    assert len(submit.call_args_list[0].args[2]) == 2
    assert 'checked replacement scene' in submit.call_args_list[0].args[1]
    assert p.status == 'completed'


def test_video_attempt_limit_is_enforced_in_worker(workflow):
    db, p, _, submit, _, _ = workflow
    _, p = run(db, p, 'analyze')
    db.add(Segment(project_id=p.id,index=0,status='failed',attempts=3))
    db.add(Segment(project_id=p.id,index=1))
    db.commit()
    job, p = run(db, p, 'generate')
    assert job.status == 'needs_attention'
    submit.assert_not_called()


def test_confirmed_provider_failure_retry_archives_task_and_keeps_count(workflow):
    db, p, _, submit, query, _ = workflow
    _, p = run(db, p, 'analyze')
    submit.side_effect = ['task-failed', 'task-repair', 'task-second']
    success = query.return_value
    query.return_value = {'status':'failed', 'error':'confirmed failure'}
    job, p = run(db, p, 'generate')
    assert job.status == 'failed'
    query.return_value = success
    job, p = run(db, p, 'generate')
    assert job.status == 'succeeded', job.error
    first = db.scalar(select(Segment).where(Segment.project_id==p.id, Segment.index==0))
    assert first.attempts == 2 and first.remote_id == 'task-repair'
    assert first.history[-1]['remote_id'] == 'task-failed'
    assert first.history[-1]['error'] == 'confirmed failure'
    assert submit.call_count == 3


@pytest.mark.parametrize('problem', ['missing_views', 'missing_shots', 'gap'])
def test_analysis_cannot_silently_allow_missing_product_evidence(workflow, problem):
    db, p, analyze, submit, _, _ = workflow
    result = copy.deepcopy(analyze.return_value)
    if problem == 'missing_views':
        result['shots'][0]['missing_views'] = ['产品打开后的内部照片']
    elif problem == 'missing_shots':
        result['shots'] = []
    else:
        result['shots'][0]['end'] = 2
    analyze.return_value = result
    job, p = run(db, p, 'analyze')
    assert job.status == 'succeeded', job.error
    assert p.analysis['segments'][0]['strategy'] == 'needs_reference'
    job, p = run(db, p, 'generate')
    assert job.status == 'needs_attention'
    submit.assert_not_called()


def test_optional_photo_edit_unknown_result_does_not_repeat_charge(workflow, monkeypatch):
    db, p, _, _, _, _ = workflow
    _, p = run(db, p, 'analyze')
    image_model = ModelConfig(name='Edit',kind='image',protocol='openai',base_url='https://example.com/v1',model_id='edit')
    db.add(image_model); db.flush(); p.image_model_id = image_model.id; db.commit()
    original = db.scalar(select(Asset).where(Asset.project_id==p.id, Asset.role=='normalized_product'))
    edit = Mock(side_effect=providers.SubmissionUncertain('unknown'))
    monkeypatch.setattr(providers, 'edit_image', edit)
    plan = {'risks':[]}
    vision = db.get(ModelConfig, p.vision_model_id)
    pipeline.optimize_product(db,p,vision,original,'white background',plan)
    pipeline.optimize_product(db,p,vision,original,'white background',plan)
    assert edit.call_count == 1
    assert original.meta['optimization_status'] == 'uncertain'
    assert plan['risks']


def test_optional_photo_edit_saves_result_before_checker_failure(workflow, monkeypatch):
    db, p, analyze, _, _, _ = workflow
    _, p = run(db, p, 'analyze')
    model = ModelConfig(name='Edit',kind='image',protocol='openai',base_url='https://example.com/v1',model_id='edit')
    db.add(model);db.flush();p.image_model_id=model.id;db.commit()
    original = db.scalar(select(Asset).where(Asset.project_id==p.id, Asset.role=='normalized_product'))
    edit = Mock(return_value=original.data)
    monkeypatch.setattr(providers,'edit_image',edit)
    analyze.side_effect = providers.ProviderError('checker unavailable')
    plan={'risks':[]}
    pipeline.optimize_product(db,p,db.get(ModelConfig,p.vision_model_id),original,'white',plan)
    assert original.meta['optimization_status']=='rejected'
    candidate=db.get(Asset,original.meta['optimization_asset_id'])
    assert candidate.data and candidate.meta['qa']['matches'] is False
    assert candidate.role=='rejected_product'


def test_wan_native_generation_resume_download_and_real_ffmpeg_join(workflow, monkeypatch):
    import json
    import httpx
    db, project, _, _, _, tmp_path = workflow
    model = db.get(ModelConfig, project.video_model_id)
    model.protocol, model.model_id, model.base_url = 'dashscope', 'wan3.0-video', 'https://workspace.cn-beijing.maas.aliyuncs.com/api/v1'
    project.options = {**project.options, 'replicate_music': False, 'replicate_voice': False}
    db.commit()
    job, project = run(db, project, 'analyze')
    assert job.status == 'succeeded', job.error
    requests = []
    query_failed = False
    submitted = 0
    def handler(request):
        nonlocal query_failed, submitted
        requests.append(request)
        if request.method == 'POST':
            submitted += 1
            assert request.url.path == '/api/v1/services/aigc/video-generation/video-synthesis'
            body = json.loads(request.content)
            assert body['parameters']['duration'] == 8 and body['parameters']['audio'] is False
            assert body['parameters']['resolution'] == '480P'
            assert body['input']['media'][-1]['type'] == 'reference_video'
            assert 'Brazilian Portuguese' in body['input']['prompt']
            return httpx.Response(200, json={'output': {'task_id': f'wan-task-{submitted}', 'task_status': 'PENDING'}})
        assert request.url.path.startswith('/api/v1/tasks/')
        if not query_failed:
            query_failed = True
            return httpx.Response(503, json={'message': 'temporary query error'})
        return httpx.Response(200, json={'output': {'task_id': request.url.path.rsplit('/',1)[1], 'task_status': 'SUCCEEDED', 'video_url': 'https://example.com/output.mp4'}})
    monkeypatch.setattr(providers, '_client', lambda timeout=180: httpx.Client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(providers, 'create_video', REAL_CREATE_VIDEO)
    monkeypatch.setattr(providers, 'get_video', REAL_GET_VIDEO)
    job, project = run(db, project, 'generate')
    assert job.status == 'failed'
    record = db.scalar(select(Segment).where(Segment.project_id == project.id, Segment.index == 0))
    assert record.remote_id == 'wan-task-1' and record.attempts == 1 and submitted == 1
    job, project = run(db, project, 'generate')
    assert job.status == 'succeeded', job.error
    assert project.status == 'completed' and submitted == 2
    assert [str(r.url).rsplit('/',1)[1] for r in requests if r.method == 'GET'] == ['wan-task-1','wan-task-1','wan-task-2']
    result = tmp_path / 'wan-result.mp4'
    result.write_bytes(db.get(Asset, project.output_asset_id).data)
    assert abs(media.probe(result)['duration'] - 16) < .1
    assert not media.probe(result)['has_audio']


def test_wan_preflight_does_not_consume_attempt_for_oversized_prompt(workflow):
    db, project, _, submit, _, _ = workflow
    model = db.get(ModelConfig, project.video_model_id)
    model.protocol, model.model_id, model.base_url = 'dashscope', 'wan3.0-video', 'https://workspace.cn-beijing.maas.aliyuncs.com/api/v1'
    db.commit()
    _, project = run(db, project, 'analyze')
    plan = copy.deepcopy(project.analysis)
    plan['product_identity'] = 'x' * 16000
    plan['segments'][0]['prompt'] = 'y' * 12000
    project.analysis = plan
    db.commit()
    job, project = run(db, project, 'generate')
    assert job.status == 'failed' and '20000' in job.error
    record = db.scalar(select(Segment).where(Segment.project_id == project.id, Segment.index == 0))
    assert record.attempts == 0 and record.remote_id is None and record.status == 'pending'
    submit.assert_not_called()


def test_wan_reference_limit_retimes_whole_interval_instead_of_dropping_tail(monkeypatch, tmp_path):
    from types import SimpleNamespace
    mapped = Mock(return_value=tmp_path / 'ref.mp4')
    cut = Mock()
    monkeypatch.setattr(media, 'cut_mapped_reference', mapped)
    monkeypatch.setattr(media, 'cut_reference', cut)
    pipeline.reference_clip(tmp_path / 'source.mp4', 15, 15, SimpleNamespace(start=0,duration=15), tmp_path / 'ref.mp4', max_input_duration=14.9)
    assert mapped.call_args.args[3] == 15 and mapped.call_args.args[4] == 14.9
    cut.assert_not_called()
