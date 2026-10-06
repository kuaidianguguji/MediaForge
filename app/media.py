"""Local media processing; durable storage belongs to the caller.

``probe`` returns duration (seconds), width, height and has_audio. ``normalize_image``
returns JPEG bytes and an explanation of deterministic, non-generative processing.
``split_timeline`` returns zero-based indices, exact source start/duration in seconds,
and integer model generation durations between 4 and 15 seconds. Generated clips
must be trimmed to the source durations before concatenation. All other operations
return their output Path; callers may remove temporary inputs after persisting bytes.
FFmpeg is resolved locally or from the installed imageio-ffmpeg dependency; no binary
is downloaded at runtime. External processes never use a shell.
"""

from __future__ import annotations

import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError


class MediaError(RuntimeError):
    """A media file or local transcoding operation could not be processed."""


def ffmpeg_path() -> str:
    configured = os.getenv("FFMPEG_PATH")
    if configured:
        resolved = shutil.which(configured)
        if resolved:
            return str(Path(resolved).resolve())
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate.resolve())
        raise MediaError("FFMPEG_PATH 指向的 FFmpeg 不存在，请检查管理员配置。")
    installed = shutil.which("ffmpeg")
    if installed:
        return installed
    try:
        import imageio_ffmpeg

        candidate = imageio_ffmpeg.get_ffmpeg_exe()
        if not Path(candidate).is_file():
            raise OSError("Missing bundled executable")
        return candidate
    except (ImportError, OSError, RuntimeError) as exc:
        raise MediaError("找不到 FFmpeg，请安装项目依赖或设置 FFMPEG_PATH。") from exc


def _run(args: list[str], *, cwd: Path | None = None, timeout: int = 900,
         allow_failure: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, shell=False, timeout=timeout,
            cwd=str(cwd) if cwd else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"媒体处理超过 {timeout} 秒，请缩短视频后重试。") from exc
    except OSError as exc:
        raise MediaError(f"无法运行媒体处理程序：{exc}") from exc
    if result.returncode and not allow_failure:
        detail = result.stderr.decode("utf-8", errors="replace")[-3000:]
        raise MediaError(f"媒体处理失败（退出码 {result.returncode}）：{detail}")
    return result


def _input(path: Path) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise MediaError(f"媒体文件不存在：{path.name}")
    return path


def _output(path: Path) -> Path:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _ffmpeg(*args: str, cwd: Path | None = None) -> None:
    # Files come from uploads. Never let a disguised playlist trigger network reads.
    safe_args = []
    for arg in args:
        if arg == "-i":
            safe_args.extend(["-protocol_whitelist", "file,pipe"])
        safe_args.append(arg)
    _run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin", "-y", *safe_args], cwd=cwd)


def _seconds(value: float) -> str:
    return f"{value:.9f}"


def probe(path: Path) -> dict:
    path = _input(path)
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        result = _run([ffprobe, "-v", "error", "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,mp3,wav", "-show_streams", "-show_format", "-of", "json", str(path)], timeout=60)
        try:
            payload = json.loads(result.stdout)
            streams = payload.get("streams", [])
            video = next((stream for stream in streams if stream.get("codec_type") == "video"), {})
            duration = float(payload.get("format", {}).get("duration") or video.get("duration") or 0)
            width, height = int(video.get("width", 0)), int(video.get("height", 0))
            rotation = float(video.get("tags", {}).get("rotate", 0))
            for side in video.get("side_data_list", []):
                if "rotation" in side:
                    rotation = float(side["rotation"])
            if abs(rotation) % 180 == 90:
                width, height = height, width
            return {"duration": duration, "width": width, "height": height,
                    "has_audio": any(stream.get("codec_type") == "audio" for stream in streams)}
        except (ValueError, TypeError, KeyError) as exc:
            raise MediaError("无法读取媒体文件的时长和尺寸。") from exc
    result = _run([ffmpeg_path(), "-hide_banner", "-nostdin", "-protocol_whitelist", "file,pipe", "-format_whitelist", "mov,matroska,webm,mp3,wav", "-i", str(path)], timeout=60, allow_failure=True)
    output = result.stderr.decode("utf-8", errors="replace")
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    video_line = next((line for line in output.splitlines() if re.search(r"Stream #.*Video:", line)), "")
    size_match = re.search(r"(?:^|[,\s])(\d{2,6})x(\d{2,6})(?=[,\s\[])" , video_line)
    if not duration_match:
        raise MediaError(f"无法读取媒体时长：{output[-1200:]}")
    h, m, s = duration_match.groups()
    width, height = (int(size_match[1]), int(size_match[2])) if size_match else (0, 0)
    rotation_match = re.search(r"rotation of\s+(-?\d+(?:\.\d+)?)\s+degrees", output)
    if rotation_match and abs(float(rotation_match[1])) % 180 == 90:
        width, height = height, width
    return {"duration": int(h) * 3600 + int(m) * 60 + float(s), "width": width,
            "height": height, "has_audio": bool(re.search(r"Stream #.*Audio:", output))}


def normalize_image(data: bytes) -> tuple[bytes, dict]:
    """Fix EXIF orientation and alpha; resize conservatively, never invent detail."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                source.load()
                original = source.size
                oriented = ImageOps.exif_transpose(source)
                had_alpha = "A" in oriented.getbands() or "transparency" in oriented.info
                if had_alpha:
                    rgba = oriented.convert("RGBA")
                    white = Image.new("RGBA", rgba.size, "white")
                    white.alpha_composite(rgba)
                    image = white.convert("RGB")
                else:
                    image = oriented.convert("RGB")
                scale = min(1.0, 2048 / max(image.size))
                if min(image.size) < 720:
                    scale = min(2.0, 720 / min(image.size), 2048 / max(image.size))
                size = tuple(max(1, round(dimension * scale)) for dimension in image.size)
                if image.size != size:
                    image = image.resize(size, Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=92, optimize=True)
                return buffer.getvalue(), {
                    "original_width": original[0], "original_height": original[1],
                    "width": image.width, "height": image.height,
                    "upscaled": scale > 1, "scale": round(scale, 4),
                    "alpha_on_white": had_alpha, "method": "deterministic",
                    "note": "已校正方向、将透明区域铺白并保守缩放；未做 AI 超分或主体抠图，不会补充真实细节。",
                }
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise MediaError("图片无法解码或像素过大，请提供有效的 JPG、PNG 或 WebP 图片。") from exc


def extract_frames(path: Path, directory: Path, count: int = 12) -> list[Path]:
    path = _input(path)
    duration = probe(path)["duration"]
    if duration <= 0 or not 1 <= count <= 120:
        raise MediaError("抽帧需要正数视频时长，帧数应在 1 到 120 之间。")
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    outputs = []
    for index in range(count):
        position = duration * (index + 0.5) / count
        output = directory / f"frame_{index + 1:03d}_{round(position * 1000):09d}ms.jpg"
        _ffmpeg("-ss", _seconds(position), "-i", str(path), "-map", "0:v:0", "-frames:v", "1",
                "-vf", "scale=w='min(1280,iw)':h=-2", "-q:v", "2", str(output))
        if not output.exists():
            raise MediaError("视频抽帧失败，文件可能没有可解码画面。")
        outputs.append(output)
    return outputs


def _review_times(duration: float, boundaries: list[float], count: int) -> tuple[list[float], bool]:
    """Reserve coverage across the entire clip, then cover scene middles and edges."""
    coverage = min(count, max(2, math.ceil(count / 4)))
    chosen = [duration * (index + .5) / coverage for index in range(coverage)]
    # Include the first decoded frame even for single-frame/very-low-fps inputs.
    chosen[0] = 0.0
    edges = [0.0, *boundaries, duration]
    scenes = list(zip(edges, edges[1:]))
    middles = [(start + end) / 2 for start, end in scenes]
    endpoints = []
    for start, end in scenes:
        inset = min(.12, (end - start) / 4)
        endpoints.extend((start + inset, end - inset))
    limited = False
    for candidates in (middles, endpoints):
        # Cover the least represented scene next, instead of spending all of the
        # budget on the opening seconds of a densely edited video.
        while candidates:
            value = max(candidates, key=lambda t: min(abs(t - existing) for existing in chosen))
            candidates.remove(value)
            if any(abs(value - existing) < .05 for existing in chosen):
                continue
            if len(chosen) >= count:
                limited = True
            else:
                chosen.append(value)
    for index in range(count):
        value = duration * (index + .5) / count
        if len(chosen) < count and all(abs(value - existing) >= .05 for existing in chosen):
            chosen.append(value)
    return sorted(chosen), limited


def _showinfo_times(stderr: bytes) -> list[float]:
    return [float(value) for value in re.findall(
        r"\bpts_time:([\d.eE+-]+)", stderr.decode("utf-8", errors="replace"))]


def extract_review_frames(path: Path, output_dir: Path, max_frames: int = 36) -> dict:
    """Return timestamped scene/coverage frames using at most two decode processes.

    ``time`` is the actual selected frame PTS in seconds from the video start,
    not the requested seek position. Scene boundaries are approximate visual cuts,
    not semantic shot annotations. ``limited`` signals omitted candidate frames or
    a reached scene-detection cap; even a non-limited sample is not frame-by-frame
    inspection. Detection timeout/failure falls back to uniform coverage.
    """
    path = _input(path)
    duration = probe(path)["duration"]
    if (not math.isfinite(duration) or not 0 < duration <= 300 or
            not isinstance(max_frames, int) or isinstance(max_frames, bool) or
            not 1 <= max_frames <= 120):
        raise MediaError("镜头抽帧支持 300 秒以内的视频，帧数应在 1 到 120 之间。")
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    base = [ffmpeg_path(), "-hide_banner", "-loglevel", "info", "-nostdin", "-y",
            "-protocol_whitelist", "file,pipe", "-i", str(path), "-map", "0:v:0", "-an"]
    scene_cap = 180
    limited = False
    boundaries = []
    method = "scene+uniform"
    try:
        result = _run(base + ["-vf", "setpts=PTS-STARTPTS,scale=320:320:force_original_aspect_ratio=decrease,select='gt(scene,0.28)',showinfo",
                             "-frames:v", str(scene_cap), "-fps_mode", "vfr", "-f", "null", "-"], timeout=90)
        detected = _showinfo_times(result.stderr)
        limited = len(detected) >= scene_cap
        for value in detected:
            if .05 < value < duration - .05 and (not boundaries or value - boundaries[-1] >= .12):
                boundaries.append(value)
    except MediaError:
        method = "uniform_fallback"
        limited = True
    if method == "uniform_fallback":
        positions = [duration * (index + .5) / max_frames for index in range(max_frames)]
        positions[0] = 0.0
    else:
        positions, budget_limited = _review_times(duration, boundaries, max_frames)
        limited = limited or budget_limited
    # Select the first decoded frame at or after each requested time in one pass.
    # Multiple requested positions falling on one low-fps frame collapse naturally.
    clauses = [f"gte(t,{_seconds(value)})*lt(prev_selected_t,{_seconds(value)})" for value in positions]
    selection = f"if(isnan(prev_selected_t),gte(t,{_seconds(positions[0])}),{'+'.join(clauses)})"
    with tempfile.TemporaryDirectory(prefix="review_", dir=output_dir) as temporary:
        pattern = Path(temporary) / "frame_%03d.jpg"
        result = _run(base + ["-vf", "setpts=PTS-STARTPTS,select='" + selection + "',"
                             "scale=w='min(960,iw)':h='min(960,ih)':force_original_aspect_ratio=decrease,showinfo",
                             "-frames:v", str(max_frames), "-fps_mode", "vfr", "-q:v", "2", str(pattern)], timeout=120)
        files = sorted(Path(temporary).glob("frame_*.jpg"))
        timestamps = _showinfo_times(result.stderr)
        if not files or len(files) > len(timestamps):
            raise MediaError("视频抽帧失败，文件可能没有可解码画面。")
        frames = []
        for index, (file, timestamp) in enumerate(zip(files, timestamps)):
            target = output_dir / f"review_{index + 1:03d}_{round(timestamp * 1000):09d}ms.jpg"
            file.replace(target)
            frames.append({"path": target, "time": timestamp})
    return {"frames": frames, "scene_boundaries": boundaries, "method": method, "limited": limited}


def reference_image(data: bytes) -> bytes:
    """Pad tiny/extreme-aspect product photos to the model's input bounds without cropping."""
    with Image.open(io.BytesIO(data)) as original:
        image = original.convert("RGB")
        width = max(300, image.width, math.ceil(image.height / 2.5))
        height = max(300, image.height, math.ceil(image.width / 2.5))
        canvas = Image.new("RGB", (width, height), "white")
        canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
        output = io.BytesIO()
        canvas.save(output, "JPEG", quality=92)
        return output.getvalue()


def extract_audio(path: Path, output: Path) -> Path:
    path, output = _input(path), _output(output)
    if not probe(path)["has_audio"]:
        raise MediaError("参考视频没有音轨，无法提取口播。")
    codec = "libmp3lame" if output.suffix.lower() == ".mp3" else "pcm_s16le"
    fmt = "mp3" if codec == "libmp3lame" else "wav"
    _ffmpeg("-i", str(path), "-map", "0:a:0", "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", codec, "-f", fmt, str(output))
    return output


def cut_reference(path: Path, output: Path, start: float, duration: float, keep_audio: bool = True) -> Path:
    path, output = _input(path), _output(output)
    if not math.isfinite(start) or not math.isfinite(duration) or start < 0 or duration <= 0:
        raise MediaError("参考片段起点和时长无效。")
    length = min(duration, 15.0, probe(path)["duration"] - start)
    if length <= 0:
        raise MediaError("参考片段起点超过源视频时长。")
    audio = ["-map", "0:a:0?", "-c:a", "aac", "-ar", "48000", "-ac", "2"] if keep_audio else ["-an"]
    _ffmpeg("-ss", _seconds(start), "-i", str(path), "-t", _seconds(length), "-map", "0:v:0",
            "-vf", "scale='if(gte(iw,ih),-2,720)':'if(gte(iw,ih),720,-2)',setsar=1,fps=30", "-c:v", "libx264",
            "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", *audio,
            "-movflags", "+faststart", str(output))
    return output


def cut_mapped_reference(path: Path, output: Path, start: float, source_duration: float,
                         target_duration: float, keep_audio: bool = True) -> Path:
    """Keep the entire source interval while fitting the provider's 2–15s input limit."""
    path, output = _input(path), _output(output)
    if (not all(math.isfinite(v) for v in (start, source_duration, target_duration)) or
            start < 0 or source_duration <= 0 or not 2 <= target_duration <= 15):
        raise MediaError("参考区间映射时长无效。")
    source_duration = min(source_duration, probe(path)["duration"] - start)
    if source_duration <= 0:
        raise MediaError("参考片段起点超过源视频时长。")
    speed = source_duration / target_duration
    tempo = speed
    filters = []
    while tempo > 2:
        filters.append("atempo=2")
        tempo /= 2
    while tempo < .5:
        filters.append("atempo=0.5")
        tempo *= 2
    filters.append(f"atempo={tempo:.9f}")
    audio = ["-map", "0:a:0?", "-af", ",".join(filters), "-c:a", "aac", "-ar", "48000", "-ac", "2"] if keep_audio else ["-an"]
    _ffmpeg("-ss", _seconds(start), "-i", str(path), "-t", _seconds(target_duration), "-map", "0:v:0",
            "-vf", f"trim=duration={_seconds(source_duration)},setpts=(PTS-STARTPTS)/{speed:.9f},"
            "scale='if(gte(iw,ih),-2,720)':'if(gte(iw,ih),720,-2)',setsar=1,fps=30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", *audio,
            "-movflags", "+faststart", str(output))
    return output


def split_timeline(duration: float, max_duration: int = 15, min_duration: int = 4) -> list[dict]:
    if (not math.isfinite(duration) or duration <= 0 or
            not isinstance(max_duration, int) or not isinstance(min_duration, int) or
            not 1 <= min_duration <= max_duration <= 15):
        raise MediaError("分段时长无效；视频时长必须为正，生成片段最长 15 秒。")
    count = math.ceil(duration / max_duration)
    result = []
    for index in range(count):
        start = duration * index / count
        end = duration if index == count - 1 else duration * (index + 1) / count
        length = end - start
        result.append({"index": index, "start": start, "duration": length,
                       "generation_duration": max(min_duration, min(max_duration, math.ceil(length - 1e-9)))})
    return result


def split_scene_timeline(duration: float, source_duration: float, scene_boundaries: list[float],
                         max_duration: int = 15) -> list[dict]:
    """Pack shots into generation clips, preferring real cuts over arbitrary cuts.

    Boundaries use source seconds and are proportionally mapped to the target
    duration. The returned fields use target seconds, matching ``split_timeline``.
    Tiny shots are grouped; long unbroken shots are divided into balanced pieces.
    Invalid/out-of-range boundary values are ignored. No scene information retains
    the existing balanced-split behavior.
    """
    if (not math.isfinite(source_duration) or source_duration <= 0 or
            not isinstance(max_duration, int) or isinstance(max_duration, bool) or
            not 4 <= max_duration <= 15):
        raise MediaError("镜头分段需要有效源视频时长，生成片段时长范围为 4 到 15 秒。")
    fallback = split_timeline(duration, max_duration=max_duration)
    boundaries = []
    for boundary in scene_boundaries:
        try:
            source_time = float(boundary)
        except (TypeError, ValueError):
            continue
        if math.isfinite(source_time) and 0 < source_time < source_duration:
            boundaries.append(source_time * duration / source_duration)
    boundaries = sorted(set(boundaries))
    if not boundaries:
        return fallback
    result = []
    start = 0.0
    while duration - start > max_duration + 1e-9:
        candidates = [value for value in boundaries
                      if start + 4 <= value <= start + max_duration and duration - value >= 4]
        if candidates:
            end = candidates[-1]
        else:
            next_cut = next((value for value in boundaries if value > start + max_duration), duration)
            end = start + split_timeline(next_cut - start, max_duration=max_duration)[0]["duration"]
        length = end - start
        result.append({"index": len(result), "start": start, "duration": length,
                       "generation_duration": max(4, min(max_duration, math.ceil(length - 1e-9)))})
        start = end
    length = duration - start
    result.append({"index": len(result), "start": start, "duration": length,
                   "generation_duration": max(4, min(max_duration, math.ceil(length - 1e-9)))})
    return result


def _target_size(ratio: str, resolution: str) -> tuple[int, int]:
    ratios = {"9:16": (9, 16), "16:9": (16, 9), "1:1": (1, 1), "4:3": (4, 3), "3:4": (3, 4), "21:9": (21, 9)}
    levels = {"480p": 480, "720p": 720, "1080p": 1080}
    if ratio not in ratios or resolution.lower() not in levels:
        raise MediaError("不支持的视频比例或分辨率。")
    w, h = ratios[ratio]
    short = levels[resolution.lower()]
    return (round(short * w / min(w, h) / 2) * 2, round(short * h / min(w, h) / 2) * 2)


def _ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    hours, remain = divmod(centis, 360000)
    minutes, remain = divmod(remain, 6000)
    seconds, centis = divmod(remain, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centis:02d}"


def _write_ass(path: Path, subtitles: list[dict], duration: float, width: int, height: int) -> None:
    # User text only enters ASS dialogue text, never filter expressions or filenames.
    # Remove ASS override syntax, control characters, and physical line breaks.
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
             "WrapStyle: 0", "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             f"Style: Default,Arial,{round(min(width, height) * 0.055)},&H00FFFFFF,&H00FFFFFF,&H00191919,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,2,40,40,{round(height * .075)},1",
             "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for item in subtitles:
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaError("字幕需要有效的 start、end 秒数。") from exc
        if not math.isfinite(start) or not math.isfinite(end):
            raise MediaError("字幕时间必须为有限数值。")
        start, end = max(0, start), min(duration, end)
        if end <= start:
            continue
        text = str(item.get("text", "")).replace("\\", "＼").replace("{", "｛").replace("}", "｝")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = "".join(char for char in text if char == "\n" or ord(char) >= 32)
        text = text.replace("\n", r"\N")
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")


def join_clips(paths: list[Path], output: Path, durations: list[float], ratio: str = "9:16",
               resolution: str = "720p", subtitles: list[dict] | None = None, mute: bool = False) -> Path:
    """Normalize each clip, pad short outputs, concatenate and optionally burn subtitles.

    Output is H.264/yuv420p/30 fps with stereo AAC (or no audio when mute=True).
    Requested durations determine the timeline; video precision is one 30 fps frame.
    Clips without audio receive silence, so concat never drops a later clip's audio.
    """
    if not paths or len(paths) != len(durations):
        raise MediaError("拼接的视频数量与时长数量不一致。")
    if any(not math.isfinite(duration) or duration <= 0 for duration in durations):
        raise MediaError("拼接片段时长必须是有限正数。")
    paths = [_input(path) for path in paths]
    output = _output(output)
    width, height = _target_size(ratio, resolution)
    total = sum(durations)
    with tempfile.TemporaryDirectory(prefix="vio_join_") as directory:
        work = Path(directory)
        normalized = []
        for index, (path, duration) in enumerate(zip(paths, durations)):
            info = probe(path)
            if not info["width"] or not info["height"]:
                raise MediaError("拼接输入中包含没有画面的视频。")
            target = work / f"clip_{index:05d}.mp4"
            args = ["-i", str(path)]
            if not info["has_audio"] and not mute:
                args += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
            args += ["-map", "0:v:0", "-vf",
                     f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,tpad=stop_mode=clone:stop_duration={_seconds(duration)}",
                     "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
            if mute:
                args += ["-an"]
            else:
                args += ["-map", "0:a:0" if info["has_audio"] else "1:a:0", "-af", "aresample=48000,apad",
                         "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]
            args += ["-t", _seconds(duration), "-video_track_timescale", "90000", str(target)]
            _ffmpeg(*args)
            normalized.append(target)
        # Relative generated names make concat paths independent of user input and OS escaping.
        (work / "clips.txt").write_text("\n".join(f"file '{path.name}'\nduration {_seconds(duration)}" for path, duration in zip(normalized, durations)), encoding="utf-8")
        args = ["-f", "concat", "-safe", "1", "-i", "clips.txt", "-map", "0:v:0"]
        if subtitles:
            _write_ass(work / "captions.ass", subtitles, total, width, height)
            args += ["-vf", "subtitles=filename=captions.ass", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p"]
        else:
            args += ["-c:v", "copy"]
        if mute:
            args += ["-an"]
        else:
            # Re-encoding audio removes per-segment AAC encoder padding at boundaries.
            args += ["-map", "0:a:0", "-af", "aresample=async=1:first_pts=0", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "160k"]
        args += ["-t", _seconds(total), "-movflags", "+faststart", str(output)]
        _ffmpeg(*args, cwd=work)
    return output


def last_frame(path: Path, out: Path) -> Path:
    path, out = _input(path), _output(out)
    info = probe(path)
    # Decode only the tail and overwrite the same image; the final write is the
    # actual last decoded frame, including very short final cuts and low fps.
    position = max(0, info["duration"] - 2.0)
    _ffmpeg("-ss", _seconds(position), "-i", str(path), "-map", "0:v:0",
            "-update", "1", "-fps_mode", "passthrough", "-q:v", "2", str(out))
    if not out.exists():
        raise MediaError("无法取得视频末帧。")
    return out
