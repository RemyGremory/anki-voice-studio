"""Check that the frozen setup launcher starts its local setup page."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen


PROJECT_DIR = Path(__file__).resolve().parents[1]
SETUP_EXE = PROJECT_DIR / "dist" / "AnkiVoiceStudioSetup.exe"


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex(("127.0.0.1", port)) != 0


def wait_for_setup(process: subprocess.Popen[bytes], timeout: float = 20) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if process.poll() is not None:
            raise RuntimeError(f"The setup launcher exited early (code {process.returncode}).")
        try:
            with urlopen("http://127.0.0.1:8767/", timeout=2) as response:
                page = response.read().decode("utf-8")
            with urlopen("http://127.0.0.1:8767/api/status", timeout=2) as response:
                status = json.loads(response.read().decode("utf-8"))
            assert "Choose installation mode" in page
            assert isinstance(status["release_ready"], bool)
            assert isinstance(status["message"], str) and status["message"]
            return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError("The setup launcher did not open its local page in time.")


def run() -> None:
    if not SETUP_EXE.is_file():
        raise RuntimeError("Build the setup launcher before this test.")
    if not port_is_free(8767):
        raise RuntimeError("Port 8767 is already in use. Close Anki Voice Studio Setup before the smoke test.")
    environment = os.environ.copy()
    environment["ANKI_VOICE_NO_BROWSER"] = "1"
    process = subprocess.Popen([str(SETUP_EXE)], cwd=str(SETUP_EXE.parent), env=environment)
    try:
        wait_for_setup(process)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


if __name__ == "__main__":
    run()
    print("Setup launcher startup smoke test passed")
