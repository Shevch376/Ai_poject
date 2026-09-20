import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN_FILE = ROOT / "main.py"
WATCH_SUFFIXES = {".py", ".kv"}
IGNORE_NAMES = {".dev_session.json"}
IGNORE_DIR_NAMES = {
    ".buildozer",
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    ".idea",
    ".vscode",
}
POLL_INTERVAL = 0.8


def snapshot():
    state = {}
    for path in ROOT.rglob("*"):
        try:
            if any(part in IGNORE_DIR_NAMES for part in path.parts):
                continue
            if not path.is_file():
                continue
            if path.name in IGNORE_NAMES:
                continue
            if path.suffix.lower() not in WATCH_SUFFIXES:
                continue
            state[str(path)] = path.stat().st_mtime
        except OSError:
            continue
    return state


def launch():
    return subprocess.Popen([sys.executable, str(MAIN_FILE)], cwd=str(ROOT))


def main():
    print("Dev runner started. Watching .py and .kv files for changes...")
    proc = launch()
    previous = snapshot()
    try:
        while True:
            time.sleep(POLL_INTERVAL)
            current = snapshot()
            if current != previous:
                previous = current
                print("Change detected. Restarting app...")
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                proc = launch()
            elif proc.poll() is not None:
                print("App exited. Restarting...")
                proc = launch()
    except KeyboardInterrupt:
        print("Stopping dev runner...")
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)


if __name__ == "__main__":
    main()
