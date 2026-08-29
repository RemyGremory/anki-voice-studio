"""Small Windows setup and updater for Anki Voice Studio.

This tool is intentionally independent of OmniVoice, PyTorch, and Anki.  It
uses only Python's standard library so a compact PyInstaller build can deliver
it as the one user-facing shortcut.  A future GitHub release only needs to
fill in bootstrap_manifest.json with HTTPS URLs and SHA-256 checksums.
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
import zipfile
import certifi
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen


APP_NAME = "Anki Voice Studio"
LOCAL_DATA = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "AnkiVoiceStudio"
APP_INSTALL_DIR = LOCAL_DATA / "app"
STATE_PATH = LOCAL_DATA / "setup_state.json"
SETUP_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
BOOTSTRAP_MANIFEST_PATH = SETUP_DIR / "bootstrap_manifest.json"
SETUP_WEB_DIR = SETUP_DIR / "setup_web"
HOST = "127.0.0.1"
PORT = 8767


def as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else (default or {})
    except (OSError, json.JSONDecodeError):
        return default or {}


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def valid_https_url(value: Any) -> str:
    url = as_text(value)
    if not url.startswith("https://"):
        raise ValueError("The download source must use HTTPS.")
    return url


def sha256_is_valid(value: Any) -> str:
    digest = as_text(value).lower()
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("The file does not have a valid SHA-256 checksum.")
    return digest


def open_https(request: Request, timeout: int) -> Any:
    """Open an HTTPS request with a bundled, current certificate store."""
    context = ssl.create_default_context(cafile=certifi.where())
    return urlopen(request, timeout=timeout, context=context)


def find_nvidia_gpu() -> str:
    """Return a detected NVIDIA card name, without requiring PyTorch."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0:
            name = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
            if name:
                return name
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def safe_extract_zip(archive: Path, destination: Path) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as package:
        for item in package.infolist():
            target = (destination / item.filename).resolve()
            if destination not in (target, *target.parents):
                raise ValueError("The archive contains an unsafe file path.")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.open(item) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def file_size(value: Any) -> str:
    try:
        size = int(value)
    except (TypeError, ValueError):
        return ""
    if size <= 0:
        return ""
    if size >= 1024**3:
        return f"{size / 1024**3:.1f} GB"
    if size >= 1024**2:
        return f"{size / 1024**2:.0f} MB"
    return f"{size / 1024:.0f} KB"


def version_key(value: str) -> tuple[tuple[int, ...], int]:
    """Enough ordering for releases like 1.0.0-beta and 1.0.0."""
    parts = tuple(int(item) for item in re.findall(r"\d+", as_text(value))[:4]) or (0,)
    stable = 1 if "beta" not in as_text(value).casefold() else 0
    return parts, stable


def is_newer(remote: str, local: str) -> bool:
    return version_key(remote) > version_key(local)


@dataclass(frozen=True)
class Asset:
    key: str
    label: str
    root: str
    executable: str
    archives: tuple[dict[str, Any], ...]

    @property
    def configured(self) -> bool:
        return bool(self.archives) and all(as_text(item.get("url")) for item in self.archives)


def parse_asset(key: str, value: Any) -> Asset:
    data = value if isinstance(value, dict) else {}
    archives = data.get("archives") if isinstance(data.get("archives"), list) else []
    return Asset(
        key=key,
        label=as_text(data.get("label")) or key,
        root=as_text(data.get("root")),
        executable=as_text(data.get("executable")),
        archives=tuple(item for item in archives if isinstance(item, dict)),
    )


class Installer:
    def __init__(self, report: Callable[[str, int | None], None]) -> None:
        self.report = report

    def bootstrap(self) -> dict[str, Any]:
        config = read_json(BOOTSTRAP_MANIFEST_PATH)
        url = as_text(config.get("release_manifest_url"))
        fallback = config.get("release_manifest")
        fallback = fallback if isinstance(fallback, dict) and isinstance(fallback.get("assets"), dict) else None
        if url:
            request = Request(valid_https_url(url), headers={"User-Agent": "AnkiVoiceStudioSetup"})
            try:
                with open_https(request, timeout=20) as response:
                    data = json.loads(response.read().decode("utf-8"))
                if not isinstance(data, dict) or not isinstance(data.get("assets"), dict):
                    raise ValueError("The release manifest has an invalid format.")
                return data
            except (URLError, TimeoutError, OSError, json.JSONDecodeError, ValueError) as error:
                if fallback is None:
                    raise ValueError("Unable to check release information.") from error
        if fallback is not None:
            return fallback
        raise ValueError("Release links are not published yet. The setup app has nothing to download.")

    def install(self, manifest: dict[str, Any], edition: str) -> dict[str, str]:
        assets = manifest.get("assets") if isinstance(manifest.get("assets"), dict) else {}
        app_asset = parse_asset(edition, assets.get(edition))
        if not app_asset.configured:
            raise ValueError("The selected edition is not published yet.")

        local_state = read_json(STATE_PATH)
        remote_version = as_text(manifest.get("version"))
        app_needed = not self.app_is_installed(local_state, edition) or local_state.get("version") != remote_version

        if app_needed:
            self.report("Downloading Anki Voice Studio…", 0)
            self.install_asset(app_asset, APP_INSTALL_DIR, self.app_is_valid)

        executable = self.find_executable(app_asset)
        state = {
            "version": remote_version,
            "edition": edition,
            "executable": str(executable),
            "installed_at": int(time.time()),
        }
        write_json(STATE_PATH, state)
        self.ensure_setup_shortcut()
        self.report("Ready.", 100)
        return {"version": remote_version, "edition": edition, "executable": str(executable)}

    def app_is_installed(self, state: dict[str, Any], edition: str) -> bool:
        executable = Path(as_text(state.get("executable")))
        return state.get("edition") == edition and executable.is_file() and APP_INSTALL_DIR.is_dir()

    def app_is_valid(self, folder: Path) -> bool:
        return any(path.is_file() and path.suffix.casefold() == ".exe" for path in folder.rglob("*.exe"))

    def find_executable(self, asset: Asset) -> Path:
        if asset.executable:
            candidate = APP_INSTALL_DIR / asset.executable
            if candidate.is_file():
                return candidate
        candidates = sorted(APP_INSTALL_DIR.rglob("*.exe"))
        if not candidates:
            raise ValueError("The app executable was not found after installation.")
        return candidates[0]

    def ensure_setup_shortcut(self) -> None:
        """Keep a stable desktop launcher after the user removes Downloads.

        The launcher checks the release manifest before opening the main app,
        so normal updates do not require the user to download a fresh archive.
        Failing to create a shortcut must never make installation fail.
        """
        if not getattr(sys, "frozen", False):
            return
        try:
            setup_copy = LOCAL_DATA / "Anki Voice Studio Setup.exe"
            current_setup = Path(sys.executable).resolve()
            if current_setup != setup_copy.resolve():
                temporary = setup_copy.with_suffix(".new.exe")
                shutil.copy2(current_setup, temporary)
                temporary.replace(setup_copy)
            environment = os.environ.copy()
            environment["AVS_SETUP_PATH"] = str(setup_copy)
            environment["AVS_SETUP_DIR"] = str(LOCAL_DATA)
            script = (
                "$desktop=[Environment]::GetFolderPath('Desktop');"
                "$link=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $desktop 'Anki Voice Studio.lnk'));"
                "$link.TargetPath=$env:AVS_SETUP_PATH;"
                "$link.WorkingDirectory=$env:AVS_SETUP_DIR;"
                "$link.Description='Open and update Anki Voice Studio';"
                "$link.Save()"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                check=False,
                capture_output=True,
                timeout=12,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                env=environment,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    def install_asset(self, asset: Asset, target: Path, validator: Callable[[Path], bool]) -> None:
        LOCAL_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="anki-voice-setup-", dir=LOCAL_DATA) as temporary_name:
            temporary = Path(temporary_name)
            unpacked = temporary / "unpacked"
            unpacked.mkdir()
            archive_count = len(asset.archives)
            for index, source in enumerate(asset.archives, start=1):
                label = asset.label if archive_count == 1 else f"{asset.label}, part {index}/{archive_count}"
                archive = temporary / f"asset-{index}.zip"
                self.download_archive(source, archive, label, index - 1, archive_count)
                safe_extract_zip(archive, unpacked)

            source_root = unpacked / asset.root if asset.root else unpacked
            if not source_root.is_dir() or not validator(source_root):
                raise ValueError("The downloaded files are incomplete or have an invalid structure.")
            staged = target.with_name(target.name + "-new")
            backup = target.with_name(target.name + "-previous")
            shutil.rmtree(staged, ignore_errors=True)
            shutil.rmtree(backup, ignore_errors=True)
            shutil.copytree(source_root, staged)
            if not validator(staged):
                shutil.rmtree(staged, ignore_errors=True)
                raise ValueError("The installed files did not pass validation.")
            if target.exists():
                target.replace(backup)
            staged.replace(target)
            shutil.rmtree(backup, ignore_errors=True)

    def download_archive(self, source: dict[str, Any], destination: Path, label: str, offset: int, total: int) -> None:
        url = valid_https_url(source.get("url"))
        expected_hash = sha256_is_valid(source.get("sha256"))
        expected_size = int(source.get("size") or 0)
        digest = hashlib.sha256()
        received = 0
        request = Request(url, headers={"User-Agent": "AnkiVoiceStudioSetup"})
        try:
            with open_https(request, timeout=30) as response, destination.open("wb") as output:
                response_size = int(response.headers.get("Content-Length", "0") or 0)
                total_size = expected_size or response_size
                while True:
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    output.write(block)
                    digest.update(block)
                    received += len(block)
                    fraction = received / total_size if total_size else 0
                    progress = int(((offset + min(fraction, 1)) / total) * 92)
                    size_note = f" {file_size(received)}" if received else ""
                    self.report(f"{label}{size_note}", progress)
        except (URLError, TimeoutError, OSError) as error:
            raise ValueError("Unable to download a component. Check your internet connection and try again.") from error
        if expected_size and received != expected_size:
            raise ValueError("The downloaded file size does not match the expected size.")
        if digest.hexdigest().lower() != expected_hash:
            raise ValueError("The downloaded file checksum does not match.")


class SetupState:
    """Small local API shared by the setup page and background installer."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.nvidia_name = find_nvidia_gpu()
        self.manifest: dict[str, Any] | None = None
        self.message = "Checking release information…"
        self.progress: int | None = None
        self.working = False
        self.server: ThreadingHTTPServer | None = None

    def report(self, message: str, progress: int | None = None) -> None:
        with self.lock:
            self.message = message
            self.progress = None if progress is None else max(0, min(100, progress))

    def refresh(self) -> None:
        with self.lock:
            if self.working:
                return
            self.working = True
            self.message = "Checking release information…"
            self.progress = None

        def worker() -> None:
            try:
                manifest = Installer(self.report).bootstrap()
                with self.lock:
                    self.manifest = manifest
                    self.message = "Ready to install the recommended edition."
                    self.progress = None
            except Exception as error:
                with self.lock:
                    self.manifest = None
                    self.message = str(error)
                    self.progress = None
            finally:
                with self.lock:
                    self.working = False

        threading.Thread(target=worker, daemon=True).start()

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            manifest = self.manifest
            message = self.message
            progress = self.progress
            working = self.working
        installed = read_json(STATE_PATH)
        edition = as_text(installed.get("edition"))
        executable = Path(as_text(installed.get("executable")))
        installed_ok = bool(edition) and executable.is_file()
        remote_version = as_text(manifest.get("version")) if manifest else ""
        installed_version = as_text(installed.get("version"))
        assets = manifest.get("assets") if isinstance(manifest, dict) and isinstance(manifest.get("assets"), dict) else {}
        available = {key: parse_asset(key, assets.get(key)).configured for key in ("cpu", "nvidia")}
        update_available = bool(installed_ok and remote_version and is_newer(remote_version, installed_version))
        current = bool(installed_ok and remote_version and remote_version == installed_version)
        return {
            "message": message,
            "progress": progress,
            "working": working,
            "release_ready": manifest is not None,
            "version": remote_version,
            "available": available,
            "nvidia": self.nvidia_name,
            "recommended": "nvidia" if self.nvidia_name else "cpu",
            "installed": installed_ok,
            "installed_edition": edition,
            "installed_version": installed_version,
            "current": current,
            "update_available": update_available,
        }

    def install(self, edition: str) -> None:
        edition = as_text(edition).casefold()
        if edition not in {"cpu", "nvidia"}:
            raise ValueError("Choose the CPU or NVIDIA edition.")
        with self.lock:
            if self.working:
                raise ValueError("The setup is already working.")
            manifest = self.manifest
            if not manifest:
                raise ValueError("Release information is not available yet.")
            self.working = True
            self.progress = 0
            self.message = "Preparing installation…"

        def worker() -> None:
            try:
                Installer(self.report).install(manifest, edition)
                with self.lock:
                    self.message = "Installation is complete. Open Anki Voice Studio."
                    self.progress = 100
            except Exception as error:
                with self.lock:
                    self.message = str(error)
                    self.progress = None
            finally:
                with self.lock:
                    self.working = False

        threading.Thread(target=worker, daemon=True).start()

    def launch(self) -> None:
        executable = Path(as_text(read_json(STATE_PATH).get("executable")))
        if not executable.is_file():
            raise ValueError("Anki Voice Studio is not installed yet.")
        os.startfile(str(executable))
        self.close()

    def close(self) -> None:
        if self.server:
            threading.Timer(0.2, self.server.shutdown).start()


STATE = SetupState()


class SetupHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/status":
            return self.send_json(STATE.snapshot())
        if path in {"", "/"}:
            path = "/index.html"
        target = (SETUP_WEB_DIR / path.lstrip("/")).resolve()
        if SETUP_WEB_DIR.resolve() not in (target, *target.parents) or not target.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        content = target.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = self.read_json()
            if path == "/api/install":
                STATE.install(as_text(data.get("edition")))
                return self.send_json({"ok": True})
            if path == "/api/refresh":
                STATE.refresh()
                return self.send_json({"ok": True})
            if path == "/api/launch":
                STATE.launch()
                return self.send_json({"ok": True})
            if path == "/api/close":
                STATE.close()
                return self.send_json({"ok": True})
            return self.send_error(HTTPStatus.NOT_FOUND)
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except Exception:
            traceback.print_exc()
            self.send_json({"error": "The setup could not complete this action."}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > 32_000:
            raise ValueError("The setup request is too large.")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8"))
        return data if isinstance(data, dict) else {}

    def send_json(self, data: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    try:
        server = ThreadingHTTPServer((HOST, PORT), SetupHandler)
    except OSError as error:
        raise RuntimeError("The setup is already open. Close its previous window and try again.") from error
    STATE.server = server
    STATE.refresh()
    url = f"http://{HOST}:{PORT}"
    print(f"Anki Voice Studio Setup is ready at {url}")
    if not os.environ.get("ANKI_VOICE_NO_BROWSER"):
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
