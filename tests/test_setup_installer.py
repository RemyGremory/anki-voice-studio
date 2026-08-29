"""Local, lightweight test for the future Anki Voice Studio installer.

It never touches Anki, AppData, user profiles, or the real app. A temporary
web server serves two tiny fake releases so the test covers a real download,
SHA-256 verification, safe unpacking, install, update, and failed-download
protection without building the multi-gigabyte application.
"""

from __future__ import annotations

import hashlib
import http.server
import importlib.util
import json
import shutil
import sys
import tempfile
import threading
import zipfile
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
SETUP_PATH = PROJECT_DIR / "anki_voice_setup.py"
SPEC = importlib.util.spec_from_file_location("anki_voice_setup_test", SETUP_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load the setup launcher.")
setup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup
SPEC.loader.exec_module(setup)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        pass


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def make_release(root: Path, version: str) -> tuple[Path, dict[str, object]]:
    app_root = root / "AnkiVoiceStudio-CPU"
    shutil.rmtree(app_root, ignore_errors=True)
    app_root.mkdir(parents=True)
    (app_root / "AnkiVoiceStudio-CPU.exe").write_text(f"test release {version}", encoding="utf-8")
    (app_root / "web.txt").write_text("small test asset", encoding="utf-8")
    archive = root / f"release-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as package:
        for file in app_root.rglob("*"):
            if file.is_file():
                package.write(file, file.relative_to(root))
    return archive, {
        "label": "Test CPU release",
        "root": "AnkiVoiceStudio-CPU",
        "executable": "AnkiVoiceStudio-CPU.exe",
        "archives": [{"url": "", "sha256": checksum(archive), "size": archive.stat().st_size}],
    }


def run() -> None:
    original_data = setup.LOCAL_DATA
    original_app = setup.APP_INSTALL_DIR
    original_state = setup.STATE_PATH
    original_url_check = setup.valid_https_url
    try:
        with tempfile.TemporaryDirectory(prefix="anki-voice-installer-test-") as temporary_name:
            temporary = Path(temporary_name)
            server_root = temporary / "server"
            server_root.mkdir()
            first_archive, first_asset = make_release(server_root, "1")
            second_archive, second_asset = make_release(server_root, "2")

            handler = lambda *args, **kwargs: QuietHandler(*args, directory=str(server_root), **kwargs)
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"

            # HTTPS remains mandatory in the released installer. Localhost HTTP
            # is enabled only inside this isolated test.
            setup.valid_https_url = lambda value: str(value)
            setup.LOCAL_DATA = temporary / "installed-data"
            setup.APP_INSTALL_DIR = setup.LOCAL_DATA / "app"
            setup.STATE_PATH = setup.LOCAL_DATA / "setup_state.json"
            custom_parent = temporary / "chosen-location"
            custom_parent.mkdir()
            custom_target, saved_parent = setup.install_target(str(custom_parent))
            assert custom_target == custom_parent / "Anki Voice Studio"
            assert saved_parent == str(custom_parent.resolve())
            reports: list[tuple[str, int | None]] = []
            installer = setup.Installer(lambda message, progress: reports.append((message, progress)))

            first_asset["archives"][0]["url"] = f"{base_url}/{first_archive.name}"
            first_manifest = {"version": "0.0.1-test", "assets": {"cpu": first_asset}}
            first_result = installer.install(first_manifest, "cpu")
            executable = Path(first_result["executable"])
            assert executable.read_text(encoding="utf-8") == "test release 1"
            first_state = json.loads(setup.STATE_PATH.read_text(encoding="utf-8"))
            assert first_state["version"] == "0.0.1-test"
            assert first_state["install_path"] == str(setup.APP_INSTALL_DIR.resolve())
            assert any(progress and progress > 0 for _, progress in reports)

            second_asset["archives"][0]["url"] = f"{base_url}/{second_archive.name}"
            second_manifest = {"version": "0.0.2-test", "assets": {"cpu": second_asset}}
            second_result = installer.install(second_manifest, "cpu")
            assert Path(second_result["executable"]).read_text(encoding="utf-8") == "test release 2"
            assert not (setup.APP_INSTALL_DIR.with_name("app-previous")).exists()

            wrong_hash = dict(second_asset)
            wrong_archive = dict(second_asset["archives"][0])
            wrong_archive["sha256"] = "0" * 64
            wrong_hash["archives"] = [wrong_archive]
            try:
                installer.install({"version": "0.0.3-test", "assets": {"cpu": wrong_hash}}, "cpu")
            except ValueError as error:
                assert "checksum" in str(error).casefold()
            else:
                raise AssertionError("Installer accepted an archive with the wrong SHA-256.")
            assert executable.read_text(encoding="utf-8") == "test release 2"

            unsafe = temporary / "unsafe.zip"
            with zipfile.ZipFile(unsafe, "w") as package:
                package.writestr("../outside.txt", "no")
            try:
                setup.safe_extract_zip(unsafe, temporary / "safe")
            except ValueError:
                pass
            else:
                raise AssertionError("Installer accepted an unsafe ZIP path.")

            server.shutdown()
            server.server_close()
    finally:
        setup.LOCAL_DATA = original_data
        setup.APP_INSTALL_DIR = original_app
        setup.STATE_PATH = original_state
        setup.valid_https_url = original_url_check


if __name__ == "__main__":
    run()
    print("Installer local test passed")
