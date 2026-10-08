"""Isolated, local-only Hypit renderer for trusted application templates.

Video generation and speech recognition remain in the host project. This adapter
executes the pinned Hypit CLI and its real HyperFrames compositor, never agent
authored executable code. All user-controlled prose enters as escaped data.
"""
from __future__ import annotations

from dataclasses import dataclass
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from typing import Callable
from xml.sax.saxutils import escape
import zipfile

from app import media

ROOT = Path(__file__).resolve().parents[3]
INSTALL = ROOT / "integrations" / "hypit"
STATE = ROOT / ".integrations" / "hypit-state"
VERSION = "0.2.17"
UPSTREAM_COMMIT = "7f730abf72fa1e4a543eed8cd1807319d9f18196"
BUILD_ID = re.compile(r"^bld_[A-Za-z0-9_-]{10,100}$")


class EngineError(ValueError):
    """A safe, actionable Hypit error suitable for a project task."""


@dataclass(frozen=True)
class EngineResult:
    video: Path
    workflow: Path
    alignment: Path
    evidence: Path
    build_id: str


def _executable(value: str | None) -> Path | None:
    if not value:
        return None
    found = shutil.which(value)
    candidate = Path(found or value).expanduser().resolve()
    return candidate if candidate.is_file() else None


def _tools() -> dict[str, Path]:
    node = _executable(os.getenv("VIO_HYPIT_NODE") or shutil.which("node"))
    probe = _executable(os.getenv("VIO_HYPIT_FFPROBE") or shutil.which("ffprobe"))
    if probe is None and os.name == "nt":
        probe = _executable(str(INSTALL / "node_modules/@ffprobe-installer/win32-x64/ffprobe.exe"))
    chrome = _executable(os.getenv("VIO_HYPIT_CHROME"))
    if chrome is None:
        for candidate in (shutil.which("google-chrome"), shutil.which("chromium"),
                          r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
            chrome = _executable(candidate)
            if chrome:
                break
    try:
        ffmpeg = _executable(media.ffmpeg_path())
    except media.MediaError as exc:
        raise EngineError("词-复刻视频缺少 FFmpeg，请先准备项目媒体处理依赖。") from exc
    result = {"node": node, "ffmpeg": ffmpeg, "ffprobe": probe, "chrome": chrome}
    for name, tool in result.items():
        if tool is None:
            raise EngineError(f"词-复刻视频缺少 {name}，请运行独立引擎安装脚本。")
    return result  # type: ignore[return-value]


def _environment() -> dict[str, str]:
    # Do not pass provider credentials or the host application's database settings.
    allowed = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP",
               "USERPROFILE", "LOCALAPPDATA", "APPDATA", "HOME", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(HYPIT_STATE_HOME=str(STATE), NO_COLOR="1", PUPPETEER_SKIP_DOWNLOAD="true")
    return env


def _receipt_fingerprint(tools: dict[str, Path]) -> dict:
    component = INSTALL / "vio-word-caption/activation.js"
    return {"version": VERSION, "tools": {key: str(path) for key, path in tools.items()},
            "component_sha256": hashlib.sha256(component.read_bytes()).hexdigest()}


def status() -> dict:
    result = {"installed": False, "ready": False, "version": VERSION, "reason": "请先安装词-复刻视频独立引擎。"}
    try:
        manifest = INSTALL / "node_modules/@hypit/hypit/package.json"
        if not manifest.is_file():
            return result
        version = json.loads(manifest.read_text(encoding="utf-8"))["version"]
        result["installed"] = True
        result["version"] = version
        if version != VERSION:
            result["reason"] = f"Hypit 版本不匹配，需要 {VERSION}。"
            return result
        tools = _tools()
        _font()
        required = [INSTALL / "vio-word-caption/activation.js", INSTALL / "vio-word-caption/package.json",
                    INSTALL / "LICENSE.Hypit", INSTALL / "node_modules/@hypit/hypit/bin/hypit.mjs"]
        required += [STATE / f"packages/@hyperframes/{package}/0.7.101/node_modules/@hyperframes/{package}/package.json"
                     for package in ("engine", "producer")]
        if not all(path.is_file() for path in required):
            result["reason"] = "引擎组件或渲染依赖缺失，请重新运行独立安装脚本。"
            return result
        version_output = subprocess.run([str(tools["node"]), "--version"], capture_output=True,
            text=True, timeout=5, shell=False, creationflags=_hidden()).stdout.strip()
        match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", version_output)
        if not match or tuple(map(int, match.groups())) < (22, 15, 0):
            result["reason"] = "词-复刻视频需要 Node.js 22.15 或以上版本。"
            return result
        receipt = STATE / "ready.json"
        if not receipt.is_file() or json.loads(receipt.read_text(encoding="utf-8")) != _receipt_fingerprint(tools):
            result["reason"] = "引擎已安装；请运行安装脚本准备本地渲染依赖。"
            return result
        result.update(ready=True, reason="Hypit 本地渲染引擎已就绪。")
    except (EngineError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        result["reason"] = str(exc) if isinstance(exc, EngineError) else "引擎检查失败，请重新运行独立安装脚本。"
    return result


def require_ready() -> None:
    current = status()
    if not current["ready"]:
        raise EngineError(current["reason"])


preflight = require_ready


def _hidden() -> int:
    return subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _cli(work: Path, args: list[str], *, timeout: int = 120,
         cancelled: Callable[[], bool] | None = None, allow_failure: bool = False) -> dict:
    tools = _tools()
    argv = [str(tools["node"]), str(INSTALL / "node_modules/@hypit/hypit/bin/hypit.mjs"),
            *args, "--workspace", str(work)]
    if args[0] not in {"check", "get", "inspect", "history", "builds"}:
        argv += ["--runtime", str(work / "hypit.runtime.json")]
    argv += ["--json"]
    logs = work / ".hypit" / "commands"
    logs.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        proc = subprocess.Popen(argv, cwd=work, env=_environment(), stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, shell=False, creationflags=_hidden())
        start = time.monotonic()
        try:
            while proc.poll() is None:
                if cancelled and cancelled():
                    raise EngineError("词-复刻视频任务已取消。")
                if time.monotonic() - start > timeout:
                    raise EngineError("Hypit 本地处理超时，已保存现有素材，可稍后重试。")
                time.sleep(.2)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)
        stdout.seek(0)
        stderr.seek(0)
        out, err = stdout.read(4 * 1024 * 1024).decode("utf-8", "replace"), stderr.read(1024 * 1024).decode("utf-8", "replace")
    if proc.returncode and not allow_failure:
        # No credentials reach this process; bound logs still stay in its work area.
        (logs / "last-error.log").write_text((out + "\n" + err)[-32000:], encoding="utf-8")
        raise EngineError("Hypit 本地渲染失败，已保存引擎诊断，请管理员检查后重试。")
    try:
        parsed = json.loads(out)
    except ValueError as exc:
        if allow_failure:
            return {"exit_code": proc.returncode}
        (logs / "last-error.log").write_text(err[-16000:] or out[-16000:], encoding="utf-8")
        raise EngineError("Hypit 未返回有效执行回执，已保存诊断。") from exc
    return parsed if isinstance(parsed, dict) else {"items": parsed}


def runtime_profile(work: Path) -> dict:
    tools = _tools()
    return {"format": "hypit.runtime-local@1", "dataRoot": ".hypit/runtime-data",
        "credentials": {}, "endpoints": {
            "media.local": {"use": "@hypit/provider-media-local", "config": {
                "ffmpegPath": str(tools["ffmpeg"]), "ffprobePath": str(tools["ffprobe"]), "defaultConcurrency": 1}},
            "hyperframes.local": {"use": "@hypit/provider-hyperframes-local", "config": {
                "ffmpegPath": str(tools["ffmpeg"]), "ffprobePath": str(tools["ffprobe"]),
                "nodePath": str(tools["node"]), "chromePath": str(tools["chrome"]),
                "workers": 1, "browserCapacity": 1, "defaultConcurrency": 1,
                "browserGpu": "software", "processTimeoutMs": 7200000}}}, "bindings": {}}


def prepare_runtime() -> None:
    """Explicit installer step; no installation ever occurs during a video job."""
    STATE.mkdir(parents=True, exist_ok=True)
    work = STATE / "installation-check"
    work.mkdir(parents=True, exist_ok=True)
    (work / "package.json").write_text('{"name":"vio-hypit-install-check","private":true}', encoding="utf-8")
    (work / "hypit.runtime.json").write_text(json.dumps(runtime_profile(work), indent=2), encoding="utf-8")
    try:
        _cli(work, ["runtime", "up", "--max-wait-ms", "120000"], timeout=1800)
        _cli(work, ["doctor"], timeout=120)
        (STATE / "ready.json").write_text(json.dumps(_receipt_fingerprint(_tools())), encoding="utf-8")
    finally:
        _cli(work, ["runtime", "down"], timeout=30, allow_failure=True)


def _groups(words: list[dict], cues: list[dict], duration: float) -> tuple[list[dict], str]:
    if len(words) > 20000 or len(cues) > 2000:
        raise EngineError("字幕数据过多，请缩短视频。")
    result, previous = [], -1.0
    for item in words:
        text = item.get("word")
        start, end = item.get("start"), item.get("end")
        if (not isinstance(text, str) or not text.strip() or len(text) > 300
                or isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or start > duration or end < start or end > duration + .12 or start < previous):
            raise EngineError("实测词级字幕时间无效，请检查语音转写结果。")
        previous = start
        word = {"word": text, "start": start, "end": min(end, duration)}
        # Zero-duration words keep their measured times and share an adjacent
        # cue. They never receive an invented highlight interval.
        split = result and end > start and result[-1]["end"] > result[-1]["start"] and (
            len(result[-1]["items"]) >= 6 or start - result[-1]["end"] > .55
            or result[-1]["items"][-1]["word"].endswith((".", "!", "?", "。", "！", "？")))
        if not result or split:
            result.append({"start": start, "end": word["end"], "items": [word]})
        else:
            result[-1]["items"].append(word)
            result[-1]["end"] = max(result[-1]["end"], word["end"])
    if words:
        if not any(item["end"] > item["start"] for item in words):
            raise EngineError("实测词级字幕全部为零时长，无法合成。")
        return result, "measured-word"
    for item in cues:
        text, start, end = item.get("text"), item.get("start"), item.get("end")
        if (not isinstance(text, str) or not text.strip() or len(text) > 2000
                or isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or end > duration + .12 or start < previous):
            raise EngineError("场景字幕时间无效，请检查分镜。")
        previous = start
        result.append({"start": start, "end": min(end, duration),
            "items": [{"word": text, "start": start, "end": min(end, duration)}]})
    return result, "scene" if cues else "none"


def _font() -> Path:
    configured = _executable(os.getenv("VIO_HYPIT_FONT"))
    if configured:
        return configured
    for filename in (r"C:\Windows\Fonts\arialbd.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        candidate = Path(filename)
        if candidate.is_file():
            return candidate
    raise EngineError("缺少字幕字体，请设置 VIO_HYPIT_FONT 为支持巴西葡语的字体文件。")


def _write_workflow(work: Path, video: Path, words: list[dict], cues: list[dict], width: int,
                    height: int, caption_style: str) -> tuple[Path, dict]:
    info = media.probe(video)
    duration = float(info["duration"])
    groups, alignment_kind = _groups(words, cues, duration)
    frame_count = max(1, round(duration * 30))
    assets = work / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(video, assets / "input.mp4")
    if groups:
        shutil.copyfile(_font(), assets / "caption-font.ttf")
    package = work / "packages/vio-word-caption"
    shutil.copytree(INSTALL / "vio-word-caption", package, dirs_exist_ok=True)
    alignment = {"kind": alignment_kind, "frame_rate": 30, "duration": duration,
        "words": words, "cues": cues, "groups": groups, "style": caption_style}
    alignment_path = work / "alignment.json"
    alignment_path.write_text(json.dumps(alignment, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "package.json").write_text('{"name":"vio-word-recreate","private":true,"type":"module"}', encoding="utf-8")
    (work / "hypit.runtime.json").write_text(json.dumps(runtime_profile(work), indent=2), encoding="utf-8")
    (work / "style.svs").write_text('<?svml using="@hypit/svs@1"?><sheet version="1">media.full {stack-order: 0; fit: contain;} film.main {background: #000000;}</sheet>', encoding="utf-8")
    escaped_groups = escape(json.dumps(groups, ensure_ascii=False), {'"': '&quot;'})
    caption_import = '<import as="captions" from="@vio/vio-word-caption@1"/>' if groups else ''
    caption_source = (f'<media:Font id="font" src="./assets/caption-font.ttf" weight="700" style="normal"/>'
        f'<captions:Track id="captions" timeline={{program.timeline}} canvas={{canvas}} font={{font}} '
        f'groups="{escaped_groups}" style="{caption_style}"/>') if groups else ''
    audio_source = '<audio:Track id="sound" timeline={program.timeline}><audio:Item source={normalized.media} during="program"/></audio:Track>' if info["has_audio"] else ''
    source = f'''<?svml using="@hypit/markup@1"?>
<svml>
  <import as="media" from="@hypit/media@1"/>
  <import as="pipeline" from="@hypit/media-pipeline@1"/>
  <import as="time" from="@hypit/timeline-author@1"/>
  <import as="space" from="@hypit/spatial@1"/>
  <import as="picture" from="@hypit/media-track@1"/>
  <import as="audio" from="@hypit/audio-track@1"/>
  <import as="film" from="@hypit/film@1"/>
  <import as="render" from="@hypit/render-hyperframes@1"/>
  <import as="style" source="./style.svs"/>
  {caption_import}
  <time:Clock id="clock" frame-rate="30"/>
  <time:Timeline id="program" clock={{clock}} end="{frame_count}f"/>
  <space:Canvas id="canvas" width="{width}" height="{height}"/>
  <space:Frame id="full" within={{canvas}} left="0%" top="0%" right="100%" bottom="100%"/>
  <media:Video id="input" src="./assets/input.mp4"/>
  <pipeline:Normalize id="normalized" source={{input}} clock={{clock}} video="primary-moving" audio="{'default' if info['has_audio'] else 'none'}" span-authority="video"/>
  <picture:Track id="footage" timeline={{program.timeline}} canvas={{canvas}}>
    <picture:Item media={{normalized.media}} frame={{full}} during="program" appearance={{style.media.full}}/>
  </picture:Track>
  {caption_source}
  {audio_source}
  <film:Film id="main" canvas={{canvas}} timeline={{program.timeline}} appearance={{style.film.main}}>
    <film:Track source={{footage.visual}}/>
    {'<film:Track source={captions.track}/>' if groups else ''}
    {'<film:Track source={sound.audio}/>' if info['has_audio'] else ''}
  </film:Film>
  <render:Video id="final" composition={{main.composition}} timeline={{program.timeline}}/>
</svml>
'''
    (work / "main.svml").write_text(source, encoding="utf-8")
    (work / "build.svrun").write_text('<?svml using="@hypit/run-markup@1"?><svrun version="1"><author source="./main.svml"/><target output="final.video"/></svrun>', encoding="utf-8")
    return alignment_path, alignment


def _find_build_id(value: dict) -> str | None:
    for key in ("buildId", "build_id", "id"):
        candidate = value.get(key)
        if isinstance(candidate, str) and BUILD_ID.fullmatch(candidate):
            return candidate
    for nested in value.values():
        if isinstance(nested, dict):
            found = _find_build_id(nested)
            if found:
                return found
    return None


def _result_manifest(work: Path, build_id: str) -> Path | None:
    for path in (work / ".hypit/results").glob(f"*/{build_id}/result.json"):
        return path
    return None


def render(work: Path, video: Path, *, words: list[dict], cues: list[dict] | None = None,
           width: int, height: int, caption_style: str = "highlight",
           cancelled: Callable[[], bool] | None = None,
           on_progress: Callable[[dict], None] | None = None,
           on_build: Callable[[str], None] | None = None,
           resume_build_id: str | None = None) -> EngineResult:
    require_ready()
    work, video = Path(work).resolve(), Path(video).resolve()
    if not video.is_file():
        raise EngineError("词-复刻视频的生成素材不存在。")
    if (type(width) is not int or type(height) is not int or min(width, height) < 64
            or max(width, height) > 4096 or width % 2 or height % 2):
        raise EngineError("词-复刻视频的画布尺寸无效。")
    if caption_style not in {"highlight", "plain"}:
        raise EngineError("字幕样式无效。")
    work.mkdir(parents=True, exist_ok=True)
    build_id = resume_build_id
    if build_id and not BUILD_ID.fullmatch(build_id):
        raise EngineError("保存的 Hypit 执行编号无效。")
    prior_build_id = build_id
    if build_id:
        alignment_path = work / "alignment.json"
        prior_manifest = _result_manifest(work, build_id)
        if (not alignment_path.is_file() or not (work / "main.svml").is_file()
                or (prior_manifest is None and not (work / ".hypit/runtime-data/runtime.sqlite").is_file())):
            # Local-only rendering can safely be repeated from the host's durable media.
            build_id = None
        elif prior_manifest and json.loads(prior_manifest.read_text(encoding="utf-8")).get("outcome") in {"failed", "cancelled"}:
            build_id = None
        else:
            saved = _cli(work, ["status", build_id], timeout=60, allow_failure=True)
            saved_work = saved.get("build", {}).get("work", {})
            if _find_build_id(saved) != build_id or saved_work.get("outcome") in {"failed", "cancelled"}:
                build_id = None
            else:
                alignment = json.loads(alignment_path.read_text(encoding="utf-8"))
    if not build_id:
        alignment_path, alignment = _write_workflow(work, video, words, cues or [], width, height, caption_style)
    try:
        if not build_id:
            if on_progress:
                on_progress({"phase": "compile", "message": "Hypit 正在编译词级工作流"})
            _cli(work, ["check", "main.svml"], timeout=120, cancelled=cancelled)
            receipt = _cli(work, ["build", "build.svrun", "--max-wait-ms", "120000"], timeout=180, cancelled=cancelled)
            build_id = _find_build_id(receipt)
            if not build_id:
                raise EngineError("Hypit 提交结果未知，请检查本地执行记录后继续。")
            (work / "build-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            if on_build:
                on_build(build_id)
        deadline = time.monotonic() + 7200
        while True:
            if cancelled and cancelled():
                raise EngineError("词-复刻视频任务已取消。")
            snapshot = _cli(work, ["status", build_id], timeout=60, cancelled=cancelled)
            (work / "last-status.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
            if on_progress:
                on_progress({"phase": "render", "message": "Hypit 正在合成画面、词级字幕与音轨", "snapshot": snapshot})
            manifest_path = _result_manifest(work, build_id)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path else {}
            outcome = manifest.get("outcome")
            if outcome:
                if outcome != "complete":
                    raise EngineError("Hypit 渲染未完成，已保存执行证据，可使用现有片段重试。")
                break
            if time.monotonic() > deadline:
                raise EngineError("Hypit 本地渲染超时，生成片段已保留。")
            for _ in range(10):
                if cancelled and cancelled():
                    raise EngineError("词-复刻视频任务已取消。")
                time.sleep(.2)
        output = work / "video-final.mp4"
        if output.exists():
            output.unlink()
        _cli(work, ["get", build_id, "--output", "final.video", "--to", str(output)], timeout=120, cancelled=cancelled)
        if not output.is_file() or output.stat().st_size == 0:
            raise EngineError("Hypit 未导出成片，执行记录已保存。")
        result_info = media.probe(output)
        if result_info["width"] != width or result_info["height"] != height:
            raise EngineError("Hypit 成片尺寸与设置不一致，已保存结果供管理员检查。")
        evidence = work / "hypit-evidence.json"
        evidence.write_text(json.dumps({"engine": "Hypit", "version": VERSION, "upstream_commit": UPSTREAM_COMMIT,
            "build_id": build_id, "previous_build_id": prior_build_id, "alignment_kind": alignment["kind"], "result": manifest,
            "input_sha256": hashlib.sha256(video.read_bytes()).hexdigest(), "output": result_info}, ensure_ascii=False, indent=2), encoding="utf-8")
        archive = work / "word-workflow.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for name in ("main.svml", "build.svrun", "style.svs", "package.json", "alignment.json", "build-receipt.json", "hypit-evidence.json"):
                if (work / name).is_file():
                    bundle.write(work / name, name)
            for folder in ("assets", "packages"):
                for path in (work / folder).rglob("*"):
                    if path.is_file():
                        bundle.write(path, path.relative_to(work).as_posix())
            bundle.write(INSTALL / "LICENSE.Hypit", "LICENSE.Hypit")
            bundle.writestr("README.txt", "Hypit 0.2.17 / VideoImageOperation 词-复刻视频\n此归档包含素材、实测时间、可信组件及作者工作流。重新运行时选择本机 local-only Runtime Profile，然后 hypit build build.svrun。原始 Hypit result 已保留在 hypit-evidence.json。")
        return EngineResult(output, archive, alignment_path, evidence, build_id)
    except BaseException:
        if build_id:
            try:
                _cli(work, ["cancel", build_id], timeout=30, allow_failure=True)
            except Exception:
                pass
        raise
    finally:
        try:
            _cli(work, ["runtime", "down"], timeout=30, allow_failure=True)
        except Exception:
            pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare_runtime()
    print(json.dumps(status(), ensure_ascii=False))
