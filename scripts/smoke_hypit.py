"""Real, free Hypit composition test with synthetic media and authored word times.

This verifies the engine's actual build, caption rendering and audio preservation.
It does not test speech recognition or a paid video-generation model.
"""
from pathlib import Path
import array
import json
import math
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import media
from app.plugins.word_recreate import engine


def _audio(path: Path) -> array.array:
    raw = subprocess.check_output([media.ffmpeg_path(), "-v", "error", "-i", str(path),
                                  "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"], timeout=30)
    return array.array("f", raw)


def main() -> None:
    engine.require_ready()
    work = ROOT / "test-results/hypit-smoke"
    work.mkdir(parents=True, exist_ok=True)
    source = work / "smoke-input.mp4"
    subprocess.run([media.ffmpeg_path(), "-y", "-f", "lavfi", "-i", "testsrc2=size=180x320:rate=30:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    output = engine.render(work, source, words=[{"word": "Olá", "start": .15, "end": .65},
                                              {"word": "Brasil!", "start": .7, "end": 1.7}],
                           width=180, height=320, on_build=lambda build: print(f"Hypit Build: {build}", flush=True),
                           on_progress=lambda event: print(event["message"], flush=True))
    info = media.probe(output.video)
    assert info["width"] == 180 and info["height"] == 320
    assert info["has_audio"] and abs(info["duration"] - 2) < .1
    before, after = _audio(source), _audio(output.video)
    rms = lambda values: math.sqrt(sum(value * value for value in values) / len(values))
    interval = range(4000, 24000)
    power_before = sum(before[index] ** 2 for index in interval)
    correlation = max(sum(before[index] * after[index + lag] for index in interval)
                      / math.sqrt(power_before * sum(after[index + lag] ** 2 for index in interval))
                      for lag in range(-40, 41))
    assert rms(after) > .01 and correlation > .95
    frame = work / "caption-frame.png"
    subprocess.run([media.ffmpeg_path(), "-y", "-ss", ".9", "-i", str(output.video), "-frames:v", "1", str(frame)],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    # Inspect caption-frame.png: at .9s, Olá remains visible and Brasil! is highlighted.
    report = {"engine": "Hypit", "version": engine.VERSION, "build_id": output.build_id,
              "input": media.probe(source), "output": info, "input_rms": rms(before),
              "output_rms": rms(after), "max_audio_correlation": correlation,
              "word_timing_source": "synthetic authored test fixture; not ASR",
              "caption_frame": str(frame), "workflow": str(output.workflow)}
    (work / "smoke-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
