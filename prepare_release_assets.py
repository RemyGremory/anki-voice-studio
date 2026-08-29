"""Split a built Anki Voice Studio folder into GitHub-safe ZIP archives.

This is a release-maintainer tool, never something an end user runs. Each ZIP
contains ordinary files under the same root directory. The small installer can
download all parts, check each SHA-256, and put the directory back together.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path


DEFAULT_PART_SIZE = 1800 * 1024 * 1024  # safely below GitHub's 2 GB asset limit


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chunks(files: list[Path], limit: int) -> list[list[Path]]:
    result: list[list[Path]] = []
    current: list[Path] = []
    size = 0
    for file in files:
        file_size = file.stat().st_size
        if file_size > limit:
            raise ValueError(f"One file is larger than the selected ZIP limit: {file}")
        if current and size + file_size > limit:
            result.append(current)
            current, size = [], 0
        current.append(file)
        size += file_size
    if current:
        result.append(current)
    return result


def archive_name(name: str, index: int, total: int) -> str:
    return f"{name}-part-{index:02d}.zip" if total > 1 else f"{name}.zip"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create GitHub-safe Anki Voice Studio release ZIPs.")
    parser.add_argument("--source", required=True, type=Path, help="Built PyInstaller folder")
    parser.add_argument("--output", required=True, type=Path, help="Empty output folder for ZIP files")
    parser.add_argument("--name", required=True, help="Archive base name, for example AnkiVoiceStudio-CPU")
    parser.add_argument("--part-size", type=int, default=DEFAULT_PART_SIZE, help="Maximum uncompressed bytes in one ZIP")
    arguments = parser.parse_args()

    source = arguments.source.resolve()
    output = arguments.output.resolve()
    if not source.is_dir():
        raise SystemExit(f"Built program folder was not found: {source}")
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"Output folder must be empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    files = sorted(item for item in source.rglob("*") if item.is_file())
    if not files:
        raise SystemExit("The built program folder contains no files.")
    groups = chunks(files, arguments.part_size)
    assets: list[dict[str, object]] = []
    for index, group in enumerate(groups, start=1):
        archive = output / archive_name(arguments.name, index, len(groups))
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as package:
            for file in group:
                package.write(file, arcname=str(Path(source.name) / file.relative_to(source)))
        assets.append({"file": archive.name, "sha256": sha256(archive), "size": archive.stat().st_size})
        print(f"Created {archive.name}")

    fragment = {
        "label": arguments.name,
        "root": source.name,
        "executable": next((item.name for item in source.glob("*.exe")), ""),
        "archives": assets,
    }
    fragment_path = output / "manifest-fragment.json"
    fragment_path.write_text(json.dumps(fragment, indent=2), encoding="utf-8")
    print(f"Created {fragment_path.name}; upload the ZIP files and replace each file name with its release URL.")


if __name__ == "__main__":
    main()
