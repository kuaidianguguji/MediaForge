"""Install only the optional Hypit renderer inside this checkout, never globally."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.plugins.word_recreate import engine


def main() -> None:
    node = shutil.which(os.getenv("VIO_HYPIT_NODE", "node"))
    if not node:
        raise SystemExit("请先安装 Node.js 22.15 或以上版本。")
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if tuple(map(int, version.lstrip("v").split("."))) < (22, 15, 0):
        raise SystemExit("请先升级 Node.js 到 22.15 或以上版本。")
    node_path = Path(node).resolve()
    candidates = [node_path.parent / "node_modules/npm/bin/npm-cli.js",
                  node_path.parent.parent / "lib/node_modules/npm/bin/npm-cli.js"]
    npm = next((path for path in candidates if path.is_file()), None)
    if npm is None:
        raise SystemExit("未找到 Node.js 附带的 npm，请安装包含 npm 的 Node.js。")
    env = dict(os.environ, HYPIT_STATE_HOME=str(engine.STATE), PUPPETEER_SKIP_DOWNLOAD="true")
    print(f"安装独立 Hypit {engine.VERSION}；npm 将下载固定版本的项目依赖。", flush=True)
    subprocess.run([node, str(npm), "ci", "--prefix", str(engine.INSTALL), "--ignore-scripts", "--no-audit", "--no-fund"],
                   cwd=ROOT, env=env, check=True, shell=False, creationflags=engine._hidden())
    shutil.copyfile(engine.INSTALL / "node_modules/@hypit/hypit/LICENSE", engine.INSTALL / "LICENSE.Hypit")
    # Keep Hypit's exact-version machine-home layout while also pinning its transitive
    # graph. Runtime 'up' reuses these installations instead of resolving newer ranges.
    locks = engine.INSTALL / "runtime-locks"
    for lock in sorted(locks.rglob("package-lock.json")):
        relative = lock.parent.relative_to(locks)
        target = engine.STATE / "packages" / relative
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(lock, target / "package-lock.json")
        shutil.copyfile(lock.parent / "package.json", target / "package.json")
        print(f"准备固定渲染依赖 {relative.as_posix()}", flush=True)
        subprocess.run([node, str(npm), "ci", "--prefix", str(target), "--ignore-scripts", "--omit=dev", "--no-audit", "--no-fund"],
                       cwd=ROOT, env=env, check=True, shell=False, creationflags=engine._hidden())
    print("准备本地 HyperFrames、FFmpeg 和浏览器；不会调用付费生成或读取模型密钥。", flush=True)
    engine.prepare_runtime()
    print(json.dumps(engine.status(), ensure_ascii=False))


if __name__ == "__main__":
    main()
