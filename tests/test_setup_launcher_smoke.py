"""Check that the frozen setup launcher starts its local setup page."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import Request, urlopen


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
            with urlopen("http://127.0.0.1:8767/assets/anki-voice-studio.svg", timeout=2) as response:
                setup_logo = response.read()
            with urlopen("http://127.0.0.1:8767/assets/anki-voice-studio.ico", timeout=2) as response:
                setup_icon = response.read()
            if not status.get("release_ready"):
                time.sleep(0.25)
                continue
            assert "Choose installation mode" in page
            assert "Choose folder" in page
            assert "generation is slow" in page
            assert setup_logo.startswith(b"<svg")
            assert setup_icon.startswith(b"\x00\x00\x01\x00")
            assert status["release_ready"] is True
            assert status["version"] == "0.1.1"
            return
        except OSError:
            time.sleep(0.25)
    raise TimeoutError("The setup launcher did not open its local page in time.")


def close_setup() -> None:
    request = Request(
        "http://127.0.0.1:8767/api/close",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=2) as response:
        assert json.loads(response.read().decode("utf-8")) == {"ok": True}


def wait_for_port_to_close(timeout: float = 5) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if port_is_free(8767):
            return
        time.sleep(0.1)
    raise TimeoutError("The setup launcher did not close its local server.")


def stop_setup_server() -> None:
    """Stop the child server created by a one-file Windows build."""
    result = subprocess.run(["netstat", "-ano"], text=True, capture_output=True, check=False)
    match = re.search(
        r"^\s*TCP\s+127\.0\.0\.1:8767\s+0\.0\.0\.0:0\s+LISTENING\s+(\d+)\s*$",
        result.stdout,
        re.MULTILINE,
    )
    if match:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", f"Stop-Process -Id {match.group(1)} -Force"],
            capture_output=True,
            timeout=10,
        )


def run() -> None:
    if not SETUP_EXE.is_file():
        raise RuntimeError("Build the setup launcher before this test.")
    if not port_is_free(8767):
        raise RuntimeError("Port 8767 is already in use. Close Anki Voice Studio Setup before the smoke test.")
    environment = os.environ.copy()
    environment["ANKI_VOICE_NO_BROWSER"] = "1"
    environment["ANKI_VOICE_SKIP_SHORTCUT"] = "1"
    process = subprocess.Popen([str(SETUP_EXE)], cwd=str(SETUP_EXE.parent), env=environment)
    try:
        wait_for_setup(process)
        close_setup()
        wait_for_port_to_close()
    finally:
        # A one-file Windows build starts a child process after unpacking.
        # Stop the local server first, then close the launcher wrapper.
        stop_setup_server()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)


if __name__ == "__main__":
    run()
    print("Setup launcher startup smoke test passed")
