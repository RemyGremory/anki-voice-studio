"""Install and start the real CPU release in a disposable local sandbox.

Run only after creating build/release-smoke with prepare_release_assets.py.
The test uses localhost instead of GitHub, keeps AppData in a temporary folder,
opens no browser, and terminates only the process that it started.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_DIR = Path(__file__).resolve().parents[1]
SETUP_PATH = PROJECT_DIR / "anki_voice_setup.py"
ASSETS_DIR = PROJECT_DIR / "build" / "release-smoke"
SPEC = importlib.util.spec_from_file_location("anki_voice_setup_smoke", SETUP_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load the setup launcher.")
setup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup
SPEC.loader.exec_module(setup)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def wait_for_app(process: subprocess.Popen[bytes], timeout: float = 45) -> dict[str, object]:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"The installed app exited before startup (code {process.returncode}).")
        try:
            with urlopen("http://127.0.0.1:8766/api/components", timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
            if isinstance(data, dict):
                return data
        except OSError:
            time.sleep(0.5)
    raise TimeoutError("The installed app did not open its local page in time.")


def close_app() -> None:
    request = Request(
        "http://127.0.0.1:8766/api/close",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        assert json.loads(response.read().decode("utf-8")) == {"ok": True}


def run() -> None:
    if not ASSETS_DIR.is_dir():
        raise RuntimeError("Create build/release-smoke before this test.")
    fragment = json.loads((ASSETS_DIR / "manifest-fragment.json").read_text(encoding="utf-8"))
    zip_files = list(ASSETS_DIR.glob("*.zip"))
    if len(zip_files) != 1:
        raise RuntimeError("This smoke test expects one compact CPU archive.")
    if not port_is_free(8766):
        raise RuntimeError("Port 8766 is already in use. Close Anki Voice Studio before the smoke test.")

    original_data = setup.LOCAL_DATA
    original_app = setup.APP_INSTALL_DIR
    original_state = setup.STATE_PATH
    original_url_check = setup.valid_https_url
    process: subprocess.Popen[bytes] | None = None
    server: http.server.ThreadingHTTPServer | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="anki-voice-cpu-smoke-") as temporary_name:
            temporary = Path(temporary_name)
            handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(ASSETS_DIR), **kwargs)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            archive = dict(fragment["archives"][0])
            archive["url"] = f"http://127.0.0.1:{server.server_port}/{archive['file']}"
            asset = dict(fragment)
            asset["archives"] = [archive]
            manifest = {"version": "0.0.1-smoke", "assets": {"cpu": asset}}

            # Production accepts HTTPS only. Localhost is allowed just for this
            # isolated test because no real release URL exists yet.
            setup.valid_https_url = lambda value: str(value)
            setup.LOCAL_DATA = temporary / "installed"
            setup.APP_INSTALL_DIR = setup.LOCAL_DATA / "app"
            setup.STATE_PATH = setup.LOCAL_DATA / "setup_state.json"
            result = setup.Installer(lambda *_: None).install(manifest, "cpu")
            executable = Path(result["executable"])
            if not executable.is_file():
                raise AssertionError("Installer did not create the main executable.")
            if (setup.APP_INSTALL_DIR / "models").exists():
                raise AssertionError("The OmniVoice model was unexpectedly included in the CPU release.")

            environment = os.environ.copy()
            sandbox_data = temporary / "user-data"
            (sandbox_data / "AnkiVoiceStudio").mkdir(parents=True)
            environment["LOCALAPPDATA"] = str(sandbox_data)
            environment["ANKI_VOICE_NO_BROWSER"] = "1"
            process = subprocess.Popen([str(executable)], cwd=str(executable.parent), env=environment)
            try:
                status = wait_for_app(process)
                components = status.get("components") if isinstance(status.get("components"), list) else []
                engine = next((item for item in components if item.get("id") == "engine"), {})
                if not engine.get("ready") or not status.get("ready"):
                    raise AssertionError(f"The installed CPU runtime is not ready: {status}")
                close_app()
                process.wait(timeout=10)
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                process = None
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        if server is not None:
            server.shutdown()
            server.server_close()
        setup.LOCAL_DATA = original_data
        setup.APP_INSTALL_DIR = original_app
        setup.STATE_PATH = original_state
        setup.valid_https_url = original_url_check


if __name__ == "__main__":
    run()
    print("CPU release installation and startup smoke test passed")
