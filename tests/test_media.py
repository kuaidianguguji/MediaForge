import io
import math
from pathlib import Path
import subprocess
import wave
from array import array

import pytest
from PIL import Image

from app import media


@pytest.mark.parametrize("duration", [0.1, 2, 3.2, 4, 15, 16, 30, 31, 59.98, 180.25])
def test_timeline_covers_exact_source_without_short_tail(duration):
    parts = media.split_timeline(duration)
    assert sum(part["duration"] for part in parts) == pytest.approx(duration)
    assert parts[0]["start"] == 0
    assert parts[-1]["start"] + parts[-1]["duration"] == pytest.approx(duration)
    for index, part in enumerate(parts):
        assert part["index"] == index
        assert 0 < part["duration"] <= 15
        assert isinstance(part["generation_duration"], int)
        assert 4 <= part["generation_duration"] <= 15
        assert part["generation_duration"] + 1e-8 >= part["duration"]
        if index:
            assert part["start"] == pytest.approx(parts[index - 1]["start"] + parts[index - 1]["duration"])
    assert media.split_timeline(16) == [
        {"index": 0, "start": 0, "duration": 8, "generation_duration": 8},
        {"index": 1, "start": 8, "duration": 8, "generation_duration": 8},
    ]


@pytest.mark.parametrize("duration", [0, -1, float("nan"), float("inf")])
def test_timeline_rejects_invalid_duration(duration):
    with pytest.raises(media.MediaError):
        media.split_timeline(duration)


def test_normalize_transparency_is_white_and_upscale_is_limited():
    image = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    image.putpixel((50, 25), (255, 0, 0, 255))
    source = io.BytesIO()
    image.save(source, "PNG")
    result, info = media.normalize_image(source.getvalue())
    with Image.open(io.BytesIO(result)) as normalized:
        assert normalized.format == "JPEG"
        assert normalized.mode == "RGB"
        assert normalized.size == (200, 100)
        assert all(channel >= 250 for channel in normalized.getpixel((0, 0)))
    assert info["scale"] == 2
    assert info["alpha_on_white"]
    assert info["method"] == "deterministic"


def test_normalize_orientation_and_large_limit():
    image = Image.new("RGB", (80, 40), "red")
    exif = Image.Exif()
    exif[274] = 6
    source = io.BytesIO()
    image.save(source, "JPEG", exif=exif)
    result, _ = media.normalize_image(source.getvalue())
    with Image.open(io.BytesIO(result)) as normalized:
        assert normalized.size == (80, 160)
        assert not normalized.getexif().get(274)
    source = io.BytesIO()
    Image.new("RGB", (3200, 2400), "white").save(source, "PNG")
    result, info = media.normalize_image(source.getvalue())
    assert (info["width"], info["height"]) == (2048, 1536)
    with pytest.raises(media.MediaError):
        media.normalize_image(b"not an image")


def _make_video(path: Path, *, audio: bool, odd: bool = False):
    args = [media.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i"]
    args += ["testsrc=size=321x241:rate=30" if odd else "color=c=blue:s=160x120:r=30"]
    if audio:
        args += ["-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000"]
    args += ["-t", "1.2", "-c:v", "ffv1" if odd else "libx264", "-pix_fmt", "bgr0" if odd else "yuv420p"]
    if audio:
        args += ["-c:a", "pcm_s16le" if odd else "aac"]
    args += [str(path)]
    subprocess.run(args, check=True, capture_output=True, timeout=60, shell=False)


@pytest.fixture(scope="module")
def source_clips(tmp_path_factory):
    directory = tmp_path_factory.mktemp("mídia com espaço")
    silent = directory / "produto 'ímpar'.mkv"
    audible = directory / "com voz.mp4"
    _make_video(silent, audio=False, odd=True)
    _make_video(audible, audio=True)
    return silent, audible


def test_probe_fallback_handles_odd_dimensions_and_audio(source_clips, monkeypatch):
    original_which = media.shutil.which
    monkeypatch.setattr(media.shutil, "which", lambda name: None if name == "ffprobe" else original_which(name))
    silent, audible = source_clips
    assert media.probe(silent) == {"duration": 1.2, "width": 321, "height": 241, "has_audio": False}
    assert media.probe(audible)["has_audio"]


def test_extract_frames_audio_cut_and_last_frame(source_clips, tmp_path):
    silent, audible = source_clips
    frames = media.extract_frames(audible, tmp_path / "frames", count=3)
    assert len(frames) == 3
    assert "ms" in frames[0].name
    for frame in frames:
        with Image.open(frame) as image:
            assert image.width > 0 and image.height > 0
    audio = media.extract_audio(audible, tmp_path / "voice.wav")
    with wave.open(str(audio)) as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
    with pytest.raises(media.MediaError, match="没有音轨"):
        media.extract_audio(silent, tmp_path / "empty.wav")
    cut = media.cut_reference(audible, tmp_path / "cut.mp4", 0.2, 0.7, keep_audio=False)
    info = media.probe(cut)
    assert info["duration"] == pytest.approx(0.7, abs=0.04)
    assert not info["has_audio"]
    assert media.last_frame(audible, tmp_path / "last.jpg").is_file()


def _rms(samples):
    return math.sqrt(sum(sample * sample for sample in samples) / max(len(samples), 1))


def test_real_concat_mixed_audio_padding_odd_sizes_and_portuguese_subtitles(source_clips, tmp_path):
    silent, audible = source_clips
    output = media.join_clips(
        [silent, audible], tmp_path / "resultado português.mp4", [1.3, 1.7],
        ratio="9:16", resolution="480p",
        subtitles=[{"start": 0.1, "end": 2.9, "text": "Promoção! Não perca: ação, você e R$ 99.\n'safe'; {\\pos(0,0)}"}],
    )
    info = media.probe(output)
    assert (info["width"], info["height"]) == (480, 854)
    assert info["duration"] == pytest.approx(3.0, abs=0.07)
    assert info["has_audio"]
    audio = media.extract_audio(output, tmp_path / "mixed.wav")
    with wave.open(str(audio)) as wav:
        samples = array("h", wav.readframes(wav.getnframes()))
    assert _rms(samples[int(0.2 * 16000):int(0.7 * 16000)]) < 20
    assert _rms(samples[int(1.6 * 16000):int(2.1 * 16000)]) > 500
    # Blue source is letterboxed: the bottom area would be black without captions.
    frames = media.extract_frames(output, tmp_path / "result_frames", count=3)
    with Image.open(frames[1]).convert("RGB") as image:
        lower = image.crop((40, int(image.height * .72), image.width - 40, int(image.height * .94)))
        pixels = lower.load()
        bright_pixels = sum(1 for y in range(lower.height) for x in range(lower.width)
                            if all(channel > 200 for channel in pixels[x, y]))
        assert bright_pixels > 50


def test_single_clip_is_normalized_and_mute_removes_audio(source_clips, tmp_path):
    output = media.join_clips([source_clips[1]], tmp_path / "single.mp4", [0.8], "1:1", "480P", mute=True)
    info = media.probe(output)
    assert (info["width"], info["height"]) == (480, 480)
    assert info["duration"] == pytest.approx(0.8, abs=0.04)
    assert not info["has_audio"]


def test_fractional_timeline_has_at_most_one_frame_rounding(source_clips, tmp_path):
    output = media.join_clips([source_clips[0]] * 3, tmp_path / "fractional.mp4", [.713] * 3)
    info = media.probe(output)
    assert (info["width"], info["height"]) == (720, 1280)
    assert info["duration"] == pytest.approx(2.139, abs=1 / 30)
    assert info["has_audio"]  # A complete silent AAC track is added when every input is silent.


def test_subtitle_text_cannot_add_ass_events_or_overrides(tmp_path):
    output = tmp_path / "captions.ass"
    media._write_ass(output, [{"start": 0, "end": 1, "text": "{\\pos(1,2)}\r\nDialogue: 9,injected\x00' ; [x]"}], 1, 720, 1280)
    text = output.read_text(encoding="utf-8-sig")
    assert sum(line.startswith("Dialogue:") for line in text.splitlines()) == 1
    assert "{\\pos" not in text
    assert "\x00" not in text
    assert "\\NDialogue: 9,injected" in text


def test_bad_ffmpeg_path_has_clear_error(monkeypatch):
    monkeypatch.setenv("FFMPEG_PATH", "missing-vio-ffmpeg-binary")
    with pytest.raises(media.MediaError, match="FFMPEG_PATH"):
        media.ffmpeg_path()


def test_mapped_reference_keeps_late_source_content_when_shortening(tmp_path):
    source = tmp_path / 'long-reference.mp4'
    subprocess.run([media.ffmpeg_path(), '-hide_banner','-loglevel','error','-y',
        '-f','lavfi','-i','color=c=red:s=160x160:r=10:d=16',
        '-f','lavfi','-i','color=c=blue:s=160x160:r=10:d=4',
        '-f','lavfi','-i','sine=frequency=440:duration=20',
        '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]', '-map','[v]','-map','2:a',
        '-c:v','libx264','-c:a','aac','-pix_fmt','yuv420p',str(source)],check=True,capture_output=True)
    mapped = media.cut_mapped_reference(source,tmp_path/'mapped.mp4',0,20,10,keep_audio=True)
    info = media.probe(mapped)
    assert info['duration'] == pytest.approx(10,abs=.15) and info['has_audio']
    last = media.last_frame(mapped,tmp_path/'last.jpg')
    with Image.open(last) as frame:
        red,green,blue = frame.convert('RGB').getpixel((frame.width//2,frame.height//2))
    assert blue > 200 and red < 50  # The last 4 source seconds must not be silently omitted.


@pytest.fixture(scope="module")
def scene_clip(tmp_path_factory):
    output = tmp_path_factory.mktemp("scene review") / "three scenes.mp4"
    args = [media.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y"]
    for color in ("red", "blue", "white"):
        args += ["-f", "lavfi", "-i", f"color=c={color}:s=600x1200:r=10:d=1"]
    args += ["-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output)]
    subprocess.run(args, check=True, capture_output=True, timeout=60, shell=False)
    return output


def test_review_frames_detect_cuts_and_record_actual_pts(scene_clip, tmp_path):
    result = media.extract_review_frames(scene_clip, tmp_path, max_frames=12)
    assert result["method"] == "scene+uniform"
    assert result["scene_boundaries"] == pytest.approx([1, 2], abs=.01)
    frames = result["frames"]
    assert 3 <= len(frames) <= 12
    times = [frame["time"] for frame in frames]
    assert times == sorted(set(times))
    assert all(0 <= time < 3 and abs(time * 10 - round(time * 10)) < 1e-7 for time in times)
    assert all(any(start <= time < start + 1 for time in times) for start in (0, 1, 2))
    for frame in frames:
        with Image.open(frame["path"]) as image:
            assert image.size == (480, 960)


def test_review_frames_budget_covers_later_scenes(scene_clip, tmp_path):
    result = media.extract_review_frames(scene_clip, tmp_path, max_frames=3)
    assert len(result["frames"]) == 3
    assert result["limited"] is True
    assert max(frame["time"] for frame in result["frames"]) >= 2


def test_review_frames_detection_failure_falls_back_in_two_processes(scene_clip, tmp_path, monkeypatch):
    original_run = media._run
    decodes = []

    def fail_detection(args, **kwargs):
        if "-vf" in args:
            decodes.append(args)
            if "gt(scene," in args[args.index("-vf") + 1]:
                raise media.MediaError("scene detection timed out")
        return original_run(args, **kwargs)

    monkeypatch.setattr(media, "_run", fail_detection)
    result = media.extract_review_frames(scene_clip, tmp_path, max_frames=4)
    assert result["method"] == "uniform_fallback"
    assert result["limited"] is True
    assert result["scene_boundaries"] == []
    assert len(result["frames"]) == 4
    assert len(decodes) == 2
    assert [frame["time"] for frame in result["frames"]] == pytest.approx([0, 1.2, 1.9, 2.7])


def test_review_handles_single_frame_video(scene_clip, tmp_path):
    single = tmp_path / "single-frame.mp4"
    media._ffmpeg("-i", str(scene_clip), "-frames:v", "1", "-c:v", "libx264", str(single))
    result = media.extract_review_frames(single, tmp_path / "frames")
    assert len(result["frames"]) == 1
    assert result["frames"][0]["time"] == 0


def test_review_rejects_overlong_input_before_decode(source_clips, tmp_path, monkeypatch):
    monkeypatch.setattr(media, "probe", lambda path: {"duration": 301})
    with pytest.raises(media.MediaError, match="300"):
        media.extract_review_frames(source_clips[0], tmp_path)


def test_scene_timeline_prefers_cuts_and_maps_source_times():
    parts = media.split_scene_timeline(30, 60, [12, 24, 36, 48])
    assert [part["start"] for part in parts] == [0, 12, 24]
    assert [part["duration"] for part in parts] == [12, 12, 6]
    assert media.split_scene_timeline(31, 31, []) == media.split_timeline(31)
    assert media.split_scene_timeline(31, 31, [None, "bad", -1, float("nan"), 40]) == media.split_timeline(31)


@pytest.mark.parametrize("duration,source,boundaries,maximum", [
    (.1, .1, [], 15), (16, 16, [1, 2, 12], 15), (40, 40, [12, 24, 36], 15),
    (59.98, 42, [2, 3, 9, 24, 35, 39], 15), (31, 31, [20], 15),
    (180.25, 300, list(range(1, 300)), 15), (21.3, 20, [3, 8, 17], 8),
])
def test_scene_timeline_continuous_and_bounded(duration, source, boundaries, maximum):
    parts = media.split_scene_timeline(duration, source, boundaries, maximum)
    assert sum(part["duration"] for part in parts) == pytest.approx(duration)
    previous_end = 0
    for index, part in enumerate(parts):
        assert part["index"] == index
        assert part["start"] == pytest.approx(previous_end)
        assert 0 < part["duration"] <= maximum
        assert isinstance(part["generation_duration"], int)
        assert 4 <= part["generation_duration"] <= maximum
        assert part["generation_duration"] + 1e-8 >= part["duration"]
        previous_end = part["start"] + part["duration"]
    assert previous_end == pytest.approx(duration)


@pytest.mark.parametrize("source,maximum", [(0, 15), (float("nan"), 15), (1, 3), (1, 16), (1, 4.5)])
def test_scene_timeline_rejects_invalid_limits(source, maximum):
    with pytest.raises(media.MediaError):
        media.split_scene_timeline(10, source, [], maximum)
