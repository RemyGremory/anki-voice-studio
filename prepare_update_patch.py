"""Create a small Anki Voice Studio update archive for a published release.

This maintainer tool packages only the files that changed in a built
PyInstaller folder. The resulting ZIP overlays the existing installation, so
users do not re-download the CPU or NVIDIA runtime for normal UI/code updates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_source_path(source: Path, value: str) -> Path:
    candidate = (source / value).resolve()
    if source not in (candidate, *candidate.parents):
        raise ValueError(f"Path is outside the built application folder: {value}")
    if not candidate.exists():
        raise ValueError(f"Changed file or folder was not found: {value}")
    return candidate


def checked_relative_path(value: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Removal path must stay inside the application folder: {value}")
    return path.as_posix()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a small Anki Voice Studio update ZIP.")
    parser.add_argument("--source", required=True, type=Path, help="Built PyInstaller application folder")
    parser.add_argument("--output", required=True, type=Path, help="Empty output folder for the update ZIP")
    parser.add_argument("--name", required=True, help="ZIP name without .zip")
    parser.add_argument("--from-version", required=True, help="Installed version this patch updates")
    parser.add_argument("--to-version", required=True, help="Version after this patch")
    parser.add_argument("--include", action="append", default=[], help="Changed file or folder, relative to --source; repeat as needed")
    parser.add_argument("--remove", action="append", default=[], help="Old file or folder to remove; repeat as needed")
    arguments = parser.parse_args()

    source = arguments.source.resolve()
    output = arguments.output.resolve()
    if not source.is_dir():
        raise SystemExit(f"Built application folder was not found: {source}")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Output folder must be empty: {output}")
    if not arguments.include and not arguments.remove:
        raise SystemExit("Choose at least one changed path with --include or one removed path with --remove.")
    output.mkdir(parents=True, exist_ok=True)

    files: set[Path] = set()
    for value in arguments.include:
        item = safe_source_path(source, value)
        if item.is_file():
            files.add(item)
        else:
            files.update(child for child in item.rglob("*") if child.is_file())
    archive = output / f"{arguments.name}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as package:
        # Keep the expected root even for a patch that only removes old files.
        package.writestr(f"{source.name}/", b"")
        for file in sorted(files):
            package.write(file, arcname=str(Path(source.name) / file.relative_to(source)))

    fragment = {
        "label": f"Anki Voice Studio update {arguments.to_version}",
        "from_version": arguments.from_version,
        "to_version": arguments.to_version,
        "root": source.name,
        "archives": [{"file": archive.name, "sha256": sha256(archive), "size": archive.stat().st_size}],
        "remove": [checked_relative_path(value) for value in arguments.remove],
    }
    fragment_path = output / "patch-manifest-fragment.json"
    fragment_path.write_text(json.dumps(fragment, indent=2), encoding="utf-8")
    print(f"Created {archive.name}")
    print(f"Created {fragment_path.name}; upload the ZIP and replace file with its release URL.")


if __name__ == "__main__":
    main()
