"""Local server for Anki Voice Studio.

It uses the browser only as a polished local window.  All card data, voice
references, model execution and MP3 files remain on this computer.
"""

from __future__ import annotations

import ast
import base64
import cgi
import csv
import hashlib
import html
import importlib.util
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from dataclasses import asdict, dataclass, field
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from urllib.error import URLError
from urllib.request import Request, urlopen


RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
WEB_DIR = RESOURCE_DIR / "web"
if getattr(sys, "frozen", False):
    # The program folder may be read-only (for example when unpacked from a
    # shared archive), so keep each user's own work in Local AppData.
    DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "AnkiVoiceStudio"
else:
    DATA_DIR = APP_DIR
OUTPUTS_DIR = DATA_DIR / "outputs"
PREVIEWS_DIR = DATA_DIR / "previews"
STUDIO_AUDIO_DIR = DATA_DIR / "studio_audio"
REFERENCES_DIR = DATA_DIR / "voice_references"
PROFILES_PATH = DATA_DIR / "voice_profiles.json"
COMPONENT_MANIFEST_PATH = RESOURCE_DIR / "component_manifest.json"
HOST = "127.0.0.1"
# AnkiConnect uses 8765 by default, so keep this program on a different port.
PORT = 8766
ANKI_CONNECT_URL = "http://127.0.0.1:8765"

CSV_FIELDS = [
    "Front",
    "Back",
    "Description",
    "Example",
    "verb",
    "Comment",
    "Image",
    "AudioWord",
    "AudioTranslation",
    "AudioExample",
]
IMPORT_HELPER_COMMAND = "Добавить аудио в Anki.cmd"
IMPORT_HELPER_SCRIPT = "add_audio_to_anki.ps1"
MODEL_REQUIRED_FILES = (
    "model.safetensors",
    "config.json",
    "tokenizer.json",
    "audio_tokenizer/model.safetensors",
)
ANKI_AUDIO_HELPER_FILES = ("__init__.py", "manifest.json", "README.txt")


def as_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


SUPPORTED_ENGLISH_INSTRUCT_ITEMS = (
    "american accent",
    "australian accent",
    "british accent",
    "canadian accent",
    "child",
    "chinese accent",
    "elderly",
    "female",
    "high pitch",
    "indian accent",
    "japanese accent",
    "low pitch",
    "male",
    "middle-aged",
    "moderate pitch",
    "portuguese accent",
    "russian accent",
    "teenager",
    "very high pitch",
    "very low pitch",
    "whisper",
    "young adult",
)
_SUPPORTED_ENGLISH_INSTRUCT = {item.casefold(): item for item in SUPPORTED_ENGLISH_INSTRUCT_ITEMS}


def supported_instruct_items(value: Any) -> tuple[str, ...]:
    """Keep only OmniVoice's documented English instruction items.

    OmniVoice rejects otherwise reasonable descriptions such as "warm" or
    "androgynous". Filtering legacy profiles here keeps an old profile from
    making the model fail, while the interface exposes every supported item.
    """
    raw_items = value if isinstance(value, (list, tuple)) else re.split(r"\s*,\s*", as_text(value))
    result: list[str] = []
    for raw_item in raw_items:
        for part in re.split(r"\s*,\s*", as_text(raw_item)):
            canonical = _SUPPORTED_ENGLISH_INSTRUCT.get(part.casefold())
            if canonical and canonical not in result:
                result.append(canonical)
    return tuple(result)


def language_code(value: str | None) -> str | None:
    value = as_text(value)
    if not value or value == "auto":
        return None
    return value


def safe_filename(value: str, fallback: str = "card") -> str:
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return value[:38] or fallback


def without_parentheses(value: str) -> str:
    previous = None
    while previous != value:
        previous, value = value, re.sub(r"\([^()]*\)", "", value)
    return re.sub(r"\s{2,}", " ", value).strip()


def prepare_speech_text(value: str) -> str:
    """Make a short, well-terminated prompt for the voice model.

    OmniVoice is more likely to complete the final phoneme when it receives a
    closing punctuation mark. This changes only the text sent to the model,
    never the content stored in Anki.
    """
    value = re.sub(r"\s+", " ", as_text(value)).strip()
    if not value:
        return ""
    if value[-1] not in ".!?…":
        value += "."
    return value


def html_audio(filename: str) -> str:
    return f'<audio controls preload="auto" src="{filename}"></audio>'


def anki_sound_filename(value: str) -> str:
    """Return the actual media filename Anki stored in a [sound:…] tag."""
    match = re.search(r"\[sound:([^\]\r\n]+)\]", as_text(value), flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def anki_audio_player_filename(value: str) -> str:
    """Return the filename from Anki's normalized HTML audio player."""
    match = re.search(
        r"<audio\b[^>]*\bsrc\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([^\s>]+))",
        as_text(value),
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    return html.unescape(next(part for part in match.groups() if part is not None)).strip()


def plain_text(value: str) -> str:
    value = re.sub(r"<br\\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"[ \t]+", " ", value)).strip()


def example_speech_text(value: str) -> str:
    """Keep the foreign part of conventional `sentence — translation` examples."""
    spoken: list[str] = []
    for line in plain_text(value).splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.split(r"\s+(?:—|–|-)\s+", line, maxsplit=1)[0].strip()
        if line:
            spoken.append(line)
    return "\n".join(spoken)


EXAMPLE_PAUSE_OPTIONS = (0.0, 0.3, 0.5, 0.8, 1.0)


def example_pause_seconds(value: Any) -> float:
    try:
        pause = float(value or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("Пауза между предложениями должна быть выбрана из списка.") from error
    if pause not in EXAMPLE_PAUSE_OPTIONS:
        raise ValueError("Пауза между предложениями должна быть: 0, 0.3, 0.5, 0.8 или 1 секунда.")
    return pause


def split_example_sentences(value: str) -> list[str]:
    """Split examples on sentence endings, while preserving the user's text.

    A new line is always a deliberate boundary. Within a line, a boundary is
    an ending mark followed by a likely new sentence, which keeps abbreviations
    such as `e.g.` less likely to be split by accident.
    """
    sentences: list[str] = []
    lines = as_text(value).splitlines() or [as_text(value)]
    for line in lines:
        parts = re.split(r"(?<=[.!?…])\s+(?=[\"'«“(]*[A-ZА-ЯЁ])", line.strip())
        sentences.extend(part.strip() for part in parts if part.strip())
    return sentences


def model_is_complete(folder: Path) -> bool:
    return all((folder / relative).is_file() for relative in MODEL_REQUIRED_FILES)


def omnivoice_model_folder() -> Path | None:
    """Find a complete model without touching the network."""
    candidates = (
        DATA_DIR / "models" / "OmniVoice",
        APP_DIR / "models" / "OmniVoice",
        RESOURCE_DIR / "models" / "OmniVoice",
    )
    seen: set[Path] = set()
    for folder in candidates:
        folder = folder.resolve()
        if folder in seen:
            continue
        seen.add(folder)
        if model_is_complete(folder):
            return folder
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        model_cache = Path(HF_HUB_CACHE) / "models--k2-fsa--OmniVoice"
        ref = model_cache / "refs" / "main"
        if ref.is_file():
            snapshot = model_cache / "snapshots" / ref.read_text(encoding="utf-8").strip()
            if model_is_complete(snapshot):
                return snapshot
    except Exception:
        pass
    return None


def component_manifest() -> dict[str, Any]:
    """Read future release download locations. The development manifest is empty."""
    try:
        data = json.loads(COMPONENT_MANIFEST_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def component_status() -> dict[str, Any]:
    engine_modules = ("omnivoice", "torch", "numpy", "lameenc", "imageio_ffmpeg")
    missing_modules = [name for name in engine_modules if importlib.util.find_spec(name) is None]
    model_folder = omnivoice_model_folder()
    components = [
        {
            "id": "engine",
            "name": "Движок озвучки",
            "ready": not missing_modules,
            "detail": "Готов к работе." if not missing_modules else "Не найдены: " + ", ".join(missing_modules),
        },
        {
            "id": "omnivoice-model",
            "name": "Голосовая модель OmniVoice",
            "ready": model_folder is not None,
            "detail": "Модель найдена." if model_folder else "Модель ещё не установлена.",
        },
    ]
    manifest = component_manifest()
    downloads = manifest.get("downloads") if isinstance(manifest.get("downloads"), dict) else {}
    # The frozen app contains the engine. OmniVoice itself downloads its model
    # from the official source on the first real synthesis request, so an absent
    # model must not block the user with a second manual installer.
    missing_ids = [item["id"] for item in components if not item["ready"] and item["id"] != "omnivoice-model"]
    configured_ids = [item_id for item_id in missing_ids if isinstance(downloads.get(item_id), dict) and downloads[item_id].get("url")]
    return {
        "ready": not missing_ids,
        "components": components,
        "missing_ids": missing_ids,
        "download_configured": bool(missing_ids and len(configured_ids) == len(missing_ids)),
        "release_configured": bool(downloads),
    }


def safe_extract_zip(archive: Path, destination: Path) -> None:
    """Extract a release asset without allowing it to write outside its folder."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as zip_file:
        for member in zip_file.infolist():
            target = (destination / member.filename).resolve()
            if destination not in (target, *target.parents):
                raise ValueError("Архив компонента содержит недопустимый путь.")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zip_file.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)


def install_omnivoice_model(job: Job, source: dict[str, Any]) -> None:
    url = as_text(source.get("url"))
    checksum = as_text(source.get("sha256")).lower()
    if not url.startswith("https://") or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise ValueError("Для загрузки модели нужен опубликованный HTTPS-адрес и контрольная сумма.")
    download_dir = DATA_DIR / "component_downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    archive = download_dir / f"omnivoice-{uuid.uuid4().hex}.zip"
    unpacked = download_dir / f"unpacked-{uuid.uuid4().hex}"
    job.update(status="Скачиваю голосовую модель…", progress_total=100)
    digest = hashlib.sha256()
    try:
        request = Request(url, headers={"User-Agent": "AnkiVoiceStudio"})
        with urlopen(request, timeout=30) as response, archive.open("wb") as output:
            expected_size = int(response.headers.get("Content-Length", "0") or 0)
            received = 0
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                received += len(block)
                if expected_size:
                    job.update(progress_done=min(90, int(received / expected_size * 90)))
        if digest.hexdigest().lower() != checksum:
            raise ValueError("Контрольная сумма модели не совпала. Файл не был установлен.")
        job.update(status="Проверяю и устанавливаю модель…", progress_done=92)
        safe_extract_zip(archive, unpacked)
        root_name = as_text(source.get("root"))
        candidates = [unpacked / root_name] if root_name else []
        candidates.extend((unpacked, unpacked / "OmniVoice"))
        model_source = next((folder for folder in candidates if model_is_complete(folder)), None)
        if model_source is None:
            raise ValueError("В скачанном архиве не найдена полная модель OmniVoice.")
        model_target = DATA_DIR / "models" / "OmniVoice"
        if model_target.exists() and not model_is_complete(model_target):
            shutil.rmtree(model_target)
        shutil.copytree(model_source, model_target, dirs_exist_ok=True)
        if not model_is_complete(model_target):
            raise ValueError("Модель установлена не полностью. Попробуй ещё раз.")
        job.update(status="Голосовая модель установлена.", progress_done=100)
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(unpacked, ignore_errors=True)


def install_missing_components(job: Job) -> dict[str, Any]:
    status = component_status()
    if status["ready"]:
        return {"installed": [], "message": "Все компоненты уже установлены."}
    downloads = component_manifest().get("downloads") or {}
    missing = status["missing_ids"]
    unavailable = [component_id for component_id in missing if not isinstance(downloads.get(component_id), dict) or not downloads[component_id].get("url")]
    if unavailable:
        raise ValueError("Источник загрузки ещё не опубликован: " + ", ".join(unavailable))
    installed: list[str] = []
    for component_id in missing:
        if component_id == "omnivoice-model":
            install_omnivoice_model(job, downloads[component_id])
            installed.append(component_id)
        else:
            raise ValueError("Этот компонент должен входить в основную программу: " + component_id)
    return {"installed": installed, "message": "Компоненты установлены."}


def write_anki_audio_helper(output: Path) -> Path:
    """Create a portable, recipient-side helper for putting this set's MP3s into Anki."""
    command_path = output / IMPORT_HELPER_COMMAND
    script_path = output / IMPORT_HELPER_SCRIPT
    command_path.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%~dp0add_audio_to_anki.ps1\"\r\n"
        "if errorlevel 1 (\r\n"
        "  echo.\r\n"
        "  echo Audio was not copied. See the message above.\r\n"
        ")\r\n"
        "echo.\r\n"
        "pause\r\n",
        encoding="ascii",
    )
    script_path.write_text(
        r'''$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot 'audio'
if (-not (Test-Path -LiteralPath $source)) {
  throw 'Рядом со скриптом не найдена папка audio.'
}

$audioFiles = @(Get-ChildItem -LiteralPath $source -File -Filter '*.mp3')
if ($audioFiles.Count -eq 0) {
  throw 'В папке audio нет MP3-файлов.'
}

$ankiRoot = Join-Path $env:APPDATA 'Anki2'
if (-not (Test-Path -LiteralPath $ankiRoot)) {
  throw "Не найдена папка Anki: $ankiRoot. Открой Anki хотя бы один раз и повтори попытку."
}

$profiles = @(
  Get-ChildItem -LiteralPath $ankiRoot -Directory | ForEach-Object {
    $collection = Join-Path $_.FullName 'collection.anki2'
    if (Test-Path -LiteralPath $collection) {
      [PSCustomObject]@{
        Name = $_.Name
        Media = Join-Path $_.FullName 'collection.media'
      }
    }
  }
)

if ($profiles.Count -eq 0) {
  throw 'В папке Anki не найдены профили с коллекцией.'
}

if ($profiles.Count -eq 1) {
  $selected = $profiles[0]
} else {
  Write-Host ''
  Write-Host 'Выберите профиль Anki:' -ForegroundColor Cyan
  for ($i = 0; $i -lt $profiles.Count; $i++) {
    Write-Host ("  [{0}] {1}" -f ($i + 1), $profiles[$i].Name)
  }
  do {
    $answer = Read-Host 'Введите номер'
    $number = 0
    $valid = [int]::TryParse($answer, [ref]$number) -and $number -ge 1 -and $number -le $profiles.Count
    if (-not $valid) { Write-Host 'Введите номер из списка.' -ForegroundColor Yellow }
  } while (-not $valid)
  $selected = $profiles[$number - 1]
}

New-Item -ItemType Directory -Force -Path $selected.Media | Out-Null
Copy-Item -LiteralPath $audioFiles.FullName -Destination $selected.Media -Force

Write-Host ''
Write-Host ("Готово: {0} MP3 скопировано в профиль «{1}»." -f $audioFiles.Count, $selected.Name) -ForegroundColor Green
Write-Host 'Теперь импортируйте anki_cards.csv в Anki.' -ForegroundColor Cyan
''',
        encoding="utf-8-sig",
    )
    return command_path


def choose_collection_media_folder() -> str:
    """Show the native Windows folder picker without granting the browser file access."""
    if os.name != "nt":
        raise ValueError("Автоматический выбор папки доступен в версии для Windows.")
    script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = 'Выберите папку collection.media для Anki'
$dialog.ShowNewFolderButton = $false
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
  [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
  Write-Output $dialog.SelectedPath
}
"""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as error:
        raise ValueError("Не удалось открыть выбор папки. Вставь путь вручную.") from error
    if completed.returncode != 0:
        raise ValueError("Не удалось открыть выбор папки. Вставь путь вручную.")
    return completed.stdout.strip().lstrip("\ufeff")


def anki_media_targets() -> list[dict[str, str]]:
    """Return local Anki profiles that can receive generated MP3 files."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return []
    anki_root = Path(appdata) / "Anki2"
    if not anki_root.is_dir():
        return []
    try:
        profiles = sorted(anki_root.iterdir(), key=lambda item: item.name.casefold())
    except OSError:
        return []
    targets: list[dict[str, str]] = []
    for profile in profiles:
        if not profile.is_dir() or not (profile / "collection.anki2").is_file():
            continue
        targets.append({"name": profile.name, "path": str(profile / "collection.media")})
    return targets


def generated_pack_directory(pack_id: Any) -> Path:
    """Resolve only a direct child of the program's generated-pack folder."""
    raw_id = as_text(pack_id)
    if not raw_id or Path(raw_id).name != raw_id:
        raise ValueError("Не найден созданный набор MP3. Создай набор ещё раз.")
    pack = (OUTPUTS_DIR / raw_id).resolve()
    if pack.parent != OUTPUTS_DIR.resolve() or not pack.is_dir():
        raise ValueError("Не найден созданный набор MP3. Создай набор ещё раз.")
    return pack


def copy_generated_pack_to_anki(job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    """Copy a completed pack's MP3 files into one of this Windows user's profiles."""
    pack = generated_pack_directory(payload.get("pack_id"))
    audio_dir = pack / "audio"
    files = sorted(audio_dir.glob("*.mp3")) if audio_dir.is_dir() else []
    if not files:
        raise ValueError("В созданном наборе не найдены MP3-файлы.")

    targets = anki_media_targets()
    if not targets:
        raise ValueError("Не найден профиль Anki. Открой Anki Desktop хотя бы один раз и повтори попытку.")
    requested_path = as_text(payload.get("media_path"))
    available = {str(Path(item["path"]).resolve()): item for item in targets}
    if requested_path:
        target_key = str(Path(requested_path).expanduser().resolve())
        if target_key not in available:
            raise ValueError("Выбранный профиль Anki больше не найден. Обнови список профилей.")
        selected = available[target_key]
    elif len(targets) == 1:
        selected = targets[0]
        target_key = str(Path(selected["path"]).resolve())
    else:
        raise ValueError("Выбери профиль Anki, в который нужно добавить аудио.")

    target = Path(target_key)
    target.mkdir(parents=True, exist_ok=True)
    job.update(status="Копирую MP3 в Anki…", progress_total=len(files))
    for index, audio_file in enumerate(files, start=1):
        shutil.copy2(audio_file, target / audio_file.name)
        job.update(progress_done=index)
    return {
        "copied": len(files),
        "profile": selected["name"],
        "media_path": str(target),
        "pack_id": pack.name,
    }


def parse_cards(source: str) -> list[dict[str, Any]]:
    source = source.strip()
    if not source:
        raise ValueError("Вставь список карточек.")
    try:
        cards = json.loads(source)
    except json.JSONDecodeError:
        try:
            cards = ast.literal_eval(source)
        except (SyntaxError, ValueError) as error:
            raise ValueError(
                "Не удалось прочитать список. Нужен JSON или список словарей в стиле Python."
            ) from error
    if not isinstance(cards, list) or not cards:
        raise ValueError("Список должен содержать хотя бы одну карточку.")
    if not all(isinstance(card, dict) for card in cards):
        raise ValueError("Каждая карточка должна быть словарём: {\"Word\": \"…\", …}.")
    return cards


def find_value(card: dict[str, Any], *names: str) -> str:
    lowered = {str(key).strip().lower(): value for key, value in card.items()}
    for name in names:
        if name in card:
            return as_text(card[name])
        if name.lower() in lowered:
            return as_text(lowered[name.lower()])
    return ""


def normalise_card(card: dict[str, Any]) -> dict[str, str]:
    return {
        "Front": find_value(card, "Front", "Word"),
        "Back": find_value(card, "Back", "Translation"),
        "Description": find_value(card, "Description", "Explanation"),
        "Example": find_value(card, "Example", "Examples"),
        "verb": find_value(card, "verb", "Verb"),
        "Comment": find_value(card, "Comment"),
        "Image": find_value(card, "Image"),
        "AudioWord": find_value(card, "AudioWord"),
        "AudioTranslation": find_value(card, "AudioTranslation"),
        "AudioExample": find_value(card, "AudioExample"),
    }


def validated_cards(source: str) -> list[dict[str, Any]]:
    cards = parse_cards(source)
    invalid: list[str] = []
    for index, card in enumerate(cards, start=1):
        normalised = normalise_card(card)
        missing = []
        if not normalised["Front"]:
            missing.append("Word/Front")
        if not normalised["Back"]:
            missing.append("Translation/Back")
        if missing:
            invalid.append(f"№{index}: {', '.join(missing)}")
    if invalid:
        raise ValueError("В карточках не хватает обязательных полей: " + "; ".join(invalid[:5]))
    return cards


@dataclass(frozen=True)
class VoiceConfig:
    name: str = "Automatic voice"
    reference_audio: str = ""
    reference_text: str = ""
    instruction: str = ""
    tags: tuple[str, ...] = ()
    speed: float = 1.0

    @classmethod
    def from_payload(cls, payload: Any) -> "VoiceConfig":
        if not isinstance(payload, dict):
            payload = {}
        try:
            speed = float(payload.get("speed", 1.0))
        except (TypeError, ValueError) as error:
            raise ValueError("Скорость должна быть числом от 0.60 до 1.40.") from error
        if not 0.60 <= speed <= 1.40:
            raise ValueError("Скорость должна быть от 0.60 до 1.40.")
        tags = supported_instruct_items(payload.get("tags"))
        instruction = ", ".join(supported_instruct_items(payload.get("instruction")))
        return cls(
            name=as_text(payload.get("name")) or "Automatic voice",
            reference_audio=as_text(payload.get("reference_audio")),
            reference_text=as_text(payload.get("reference_text")),
            instruction=instruction,
            tags=tags,
            speed=speed,
        )

    @property
    def prompt_instruction(self) -> str:
        """Natural-language description used only for non-cloned voices."""
        parts = [*supported_instruct_items(self.tags), *supported_instruct_items(self.instruction)]
        parts = list(dict.fromkeys(parts))
        return ", ".join(parts)


def speech_cache_key(
    text: str,
    voice: VoiceConfig,
    language: str | None,
    sentence_pause: float = 0.0,
    fragment_mode: str = "",
) -> str:
    """A preview can be reused only for the exact speech request."""
    request = {
        # Compare the final prompt the model receives, not superficial
        # whitespace or an automatically added ending full stop.
        "text": prepare_speech_text(text),
        "language": language or "",
        "sentence_pause": sentence_pause,
        "fragment_mode": fragment_mode,
        "voice": {
            "reference_audio": voice.reference_audio,
            "reference_text": voice.reference_text,
            "instruction": voice.instruction,
            "tags": list(voice.tags),
            "speed": voice.speed,
        },
    }
    payload = json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class OmniVoiceEngine:
    """The model is loaded once. Saved reference prompts make a batch faster."""

    def __init__(self) -> None:
        self.model = None
        self.np = None
        self._prompts: dict[tuple[str, str, float], Any] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _model_location() -> str:
        """Prefer a bundled or already-downloaded model without an internet check."""
        local_model = omnivoice_model_folder()
        if local_model is not None:
            return str(local_model)
        # The first run needs the official name once so Hugging Face can fetch it.
        return "k2-fsa/OmniVoice"

    def ensure_loaded(self, report: Callable[[str], None]) -> None:
        with self._lock:
            if self.model is not None:
                return
            try:
                import imageio_ffmpeg
                import lameenc  # noqa: F401
                import numpy as np
                import torch
                from omnivoice import OmniVoice
            except ModuleNotFoundError as error:
                missing = error.name or "компонент"
                raise RuntimeError(
                    f"Не найден {missing}. Закрой программу и запусти setup_and_start.cmd один раз."
                ) from error

            # OmniVoice can accept WAV directly.  Including a local FFmpeg
            # binary also makes ordinary MP3/M4A voice samples work without a
            # separate system-wide FFmpeg installation.
            ffmpeg = Path(imageio_ffmpeg.get_ffmpeg_exe())
            os.environ["PATH"] = str(ffmpeg.parent) + os.pathsep + os.environ.get("PATH", "")
            has_cuda = torch.cuda.is_available()
            device = "cuda:0" if has_cuda else "cpu"
            dtype = torch.float16 if has_cuda else torch.float32
            device_name = torch.cuda.get_device_name(0) if has_cuda else "CPU"
            report(f"Загружаю OmniVoice на {device_name}…")
            try:
                self.model = OmniVoice.from_pretrained(
                    self._model_location(), device_map=device, dtype=dtype
                )
            except Exception as error:
                raise RuntimeError(
                    "OmniVoice не удалось загрузить. При первом запуске нужны интернет, "
                    "свободное место и доступ к модели."
                ) from error
            self.np = np
            report("OmniVoice готов. Создаю аудио…")

    def _prompt(self, config: VoiceConfig, report: Callable[[str], None]):
        if not config.reference_audio:
            return None
        ref = Path(config.reference_audio).resolve()
        if not ref.is_file():
            raise ValueError("Не найден файл образца голоса. Загрузи его заново.")
        key = (str(ref), config.reference_text, ref.stat().st_mtime)
        if key not in self._prompts:
            report(f"Подготавливаю голос «{config.name}»…")
            kwargs: dict[str, str] = {"ref_audio": str(ref)}
            if config.reference_text:
                kwargs["ref_text"] = config.reference_text
            self._prompts[key] = self.model.create_voice_clone_prompt(**kwargs)
        return self._prompts[key]

    def synthesize(
        self,
        text: str,
        voice: VoiceConfig,
        language: str | None,
        destination: Path,
        report: Callable[[str], None],
    ) -> None:
        samples = self._generate_samples(text, voice, language, report)
        self._save_mp3(samples, destination)

    def synthesize_translation(
        self,
        text: str,
        voice: VoiceConfig,
        language: str | None,
        destination: Path,
        report: Callable[[str], None],
    ) -> None:
        """Speak the translation as one natural phrase, including commas."""
        self.synthesize(text, voice, language, destination, report)

    def _samples_array(self, samples: Any) -> Any:
        if hasattr(samples, "detach"):
            samples = samples.detach().float().cpu().numpy()
        return self.np.asarray(samples, dtype=self.np.float32).reshape(-1)

    def _voiced_seconds(self, samples: Any) -> float:
        array = self._samples_array(samples)
        voiced = self.np.flatnonzero(self.np.abs(array) > 0.012)
        if not voiced.size:
            return 0.0
        return float(voiced[-1] - voiced[0] + 1) / 24_000.0

    def _ending_minimum_seconds(self, text: str) -> float | None:
        letters = len(re.findall(r"[\wÀ-ÿА-Яа-яЁё]", text))
        if letters < 6:
            return None
        return min(0.75, 0.20 + letters * 0.035)

    def _trim_translation_fragment(self, samples: Any) -> Any:
        """Remove model startup silence without cutting the final phoneme."""
        array = self._samples_array(samples)
        voiced = self.np.flatnonzero(self.np.abs(array) > 0.003)
        if not voiced.size:
            return array
        leading_guard = int(24_000 * 0.035)
        trailing_guard = int(24_000 * 0.14)
        start = max(0, int(voiced[0]) - leading_guard)
        end = min(array.size, int(voiced[-1]) + trailing_guard + 1)
        return array[start:end]

    def synthesize_sentences(
        self,
        sentences: list[str],
        voice: VoiceConfig,
        language: str | None,
        pause_seconds: float,
        destination: Path,
        report: Callable[[str], None],
    ) -> None:
        """Create one MP3 from individually generated example sentences."""
        if len(sentences) <= 1 or pause_seconds <= 0:
            self.synthesize(" ".join(sentences), voice, language, destination, report)
            return
        segments: list[Any] = []
        for index, sentence in enumerate(sentences, start=1):
            report(f"Озвучиваю предложение {index}/{len(sentences)}…")
            if index > 1:
                segments.append(self.np.zeros(int(24_000 * pause_seconds), dtype=self.np.float32))
            samples = self._generate_samples(sentence, voice, language, report)
            if hasattr(samples, "detach"):
                samples = samples.detach().float().cpu().numpy()
            segments.append(self.np.asarray(samples, dtype=self.np.float32).reshape(-1))
        self._save_mp3(self.np.concatenate(segments), destination)

    def _generate_samples(
        self,
        text: str,
        voice: VoiceConfig,
        language: str | None,
        report: Callable[[str], None],
        minimum_seconds: float | None = None,
    ) -> Any:
        if not text:
            raise ValueError("Нельзя создать аудио из пустого текста.")
        self.ensure_loaded(report)
        model_text = prepare_speech_text(text)
        if not model_text:
            raise ValueError("Нельзя создать аудио из пустого текста.")
        kwargs: dict[str, Any] = {"text": model_text, "speed": voice.speed}
        prompt = self._prompt(voice, report)
        if prompt is not None:
            kwargs["voice_clone_prompt"] = prompt
        elif voice.prompt_instruction:
            kwargs["instruct"] = voice.prompt_instruction
        if language:
            kwargs["language_id"] = language
        # OmniVoice can rarely return only one empty MP3 frame. Try several
        # takes, but never block the card: if all are short, keep the longest.
        word_count = max(1, len(re.findall(r"[\wÀ-ÿА-Яа-яЁё]+", model_text)))
        default_minimum = min(1.2, 0.27 + 0.15 * word_count)
        required_seconds = max(default_minimum, minimum_seconds or 0.0)
        minimum_samples = int(24_000 * required_seconds)
        longest_samples: Any = None
        longest_length = -1
        for attempt in range(3):
            output = self.model.generate(**kwargs)
            samples = output[0] if isinstance(output, (list, tuple)) else output
            array = self._samples_array(samples)
            peak = float(self.np.max(self.np.abs(array))) if array.size else 0.0
            if array.size > longest_length:
                longest_samples, longest_length = samples, array.size
            if array.size >= minimum_samples and peak >= 0.003:
                return samples
            if attempt < 2:
                report("Озвучка получилась слишком короткой — повторяю…")
        report("Сохраняю самый длинный вариант озвучки…")
        return longest_samples

    def _save_mp3(self, samples: Any, destination: Path) -> None:
        import lameenc

        if hasattr(samples, "detach"):
            samples = samples.detach().float().cpu().numpy()
        samples = self.np.asarray(samples, dtype=self.np.float32).reshape(-1)
        # A cloned voice can inherit a quiet source recording. Bring quieter
        # outputs up to a consistent safe peak, without reducing already loud
        # voices or allowing clipping. The cap avoids amplifying near-silence
        # (and any background noise in it) excessively.
        samples = self.np.nan_to_num(samples, nan=0.0, posinf=0.0, neginf=0.0)
        peak = float(self.np.max(self.np.abs(samples))) if samples.size else 0.0
        if 0.001 <= peak < 0.92:
            gain = min(0.92 / peak, 8.0)
            samples = samples * gain
        samples = self.np.clip(samples, -1.0, 1.0)
        pcm = (samples * 32767.0).astype(self.np.int16).tobytes()
        encoder = lameenc.Encoder()
        encoder.set_bit_rate(128)
        encoder.set_in_sample_rate(24000)
        encoder.set_channels(1)
        encoder.set_quality(2)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(encoder.encode(pcm) + encoder.flush())


@dataclass
class Job:
    id: str
    kind: str
    state: str = "running"
    status: str = "Подготовка…"
    progress_done: int = 0
    progress_total: int = 0
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **values: Any) -> None:
        with self.lock:
            for key, value in values.items():
                setattr(self, key, value)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "id": self.id,
                "kind": self.kind,
                "state": self.state,
                "status": self.status,
                "progress_done": self.progress_done,
                "progress_total": self.progress_total,
                "result": self.result,
                "error": self.error,
            }


class StudioState:
    def __init__(self) -> None:
        self.engine = OmniVoiceEngine()
        self.jobs: dict[str, Job] = {}
        self.jobs_lock = threading.Lock()
        self.generation_lock = threading.Lock()
        self.profiles_lock = threading.Lock()
        self.previews_lock = threading.Lock()
        self.previews: dict[str, dict[str, Any]] = {}

    def remember_preview(self, preview_id: str, path: Path, cache_key: str) -> None:
        """Keep a short-lived local index of previews that may be attached to Anki."""
        with self.previews_lock:
            cutoff = time.time() - 60 * 60 * 8
            self.previews = {
                key: value
                for key, value in self.previews.items()
                if value["created"] >= cutoff and Path(value["path"]).is_file()
            }
            self.previews[preview_id] = {
                "path": str(path.resolve()),
                "cache_key": cache_key,
                "created": time.time(),
            }
            # Keep the index small; files are left intact so a playing preview
            # is never interrupted in the browser.
            if len(self.previews) > 80:
                oldest = sorted(self.previews, key=lambda key: self.previews[key]["created"])[:-80]
                for key in oldest:
                    self.previews.pop(key, None)

    def preview_file(self, preview_id: str, cache_key: str) -> Path | None:
        if not preview_id or not cache_key:
            return None
        with self.previews_lock:
            item = self.previews.get(preview_id)
            if not item or item.get("cache_key") != cache_key:
                return None
            path = Path(as_text(item.get("path")))
            try:
                is_preview = path.resolve().is_relative_to(PREVIEWS_DIR.resolve())
            except (OSError, ValueError):
                is_preview = False
            return path if is_preview and path.is_file() else None

    def profiles(self) -> dict[str, dict[str, Any]]:
        with self.profiles_lock:
            try:
                data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except (OSError, json.JSONDecodeError):
                return {}

    def save_profile(self, name: str, config: VoiceConfig) -> dict[str, Any]:
        name = as_text(name)
        if not name:
            raise ValueError("У профиля должно быть название.")
        with self.profiles_lock:
            profiles = self.profiles_unlocked()
            profiles[name] = asdict(config)
            PROFILES_PATH.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"name": name, "profile": profiles[name]}

    def delete_profile(self, name: str) -> None:
        name = as_text(name)
        with self.profiles_lock:
            profiles = self.profiles_unlocked()
            if name not in profiles:
                raise ValueError("Голосовой профиль не найден.")
            del profiles[name]
            PROFILES_PATH.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")

    def delete_reference(self, source: str) -> int:
        path = Path(as_text(source)).resolve()
        references_root = REFERENCES_DIR.resolve()
        if not path.is_file() or references_root not in (path.parent, *path.parents):
            raise ValueError("Можно удалить только образец, добавленный в эту программу.")
        with self.profiles_lock:
            profiles = self.profiles_unlocked()
            affected = 0
            for profile in profiles.values():
                if as_text(profile.get("reference_audio")) == str(path):
                    profile["reference_audio"] = ""
                    profile["reference_text"] = ""
                    affected += 1
            PROFILES_PATH.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
        path.unlink()
        self.engine._prompts = {
            key: value for key, value in self.engine._prompts.items() if key[0] != str(path)
        }
        return affected

    def profiles_unlocked(self) -> dict[str, dict[str, Any]]:
        try:
            data = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def start(self, kind: str, work: Callable[[Job], dict[str, Any]]) -> Job:
        with self.generation_lock:
            active = next((job for job in self.jobs.values() if job.state == "running"), None)
            if active:
                raise ValueError("Сейчас уже идёт создание аудио. Дождись его завершения.")
            job = Job(id=uuid.uuid4().hex, kind=kind)
            self.jobs[job.id] = job

        def runner() -> None:
            try:
                result = work(job)
                job.update(state="done", status="Готово", result=result)
            except Exception as error:
                print(traceback.format_exc())
                job.update(state="error", status="Не удалось завершить", error=str(error))

        threading.Thread(target=runner, daemon=True).start()
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def has_active_job(self) -> bool:
        return any(job.state == "running" for job in self.jobs.values())


STATE = StudioState()


def run_preview(job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    text = as_text(payload.get("text"))
    if payload.get("strip_brackets"):
        text = without_parentheses(text)
    voice = VoiceConfig.from_payload(payload.get("voice"))
    language = language_code(payload.get("language"))
    sentence_pause = example_pause_seconds(payload.get("example_pause"))
    fragment_mode = as_text(payload.get("fragment_mode"))
    filename = f"preview-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:5]}.mp3"
    destination = PREVIEWS_DIR / filename
    job.update(status="Создаю предпрослушивание…", progress_total=1)
    if fragment_mode == "translation":
        STATE.engine.synthesize_translation(text, voice, language, destination, lambda message: job.update(status=message))
    else:
        synthesize_example_audio(
            text, voice, language, sentence_pause, destination,
            lambda message: job.update(status=message),
        )
    job.update(progress_done=1)
    preview_id = uuid.uuid4().hex
    cache_key = speech_cache_key(text, voice, language, sentence_pause, fragment_mode)
    STATE.remember_preview(preview_id, destination, cache_key)
    return {
        "url": f"/previews/{filename}",
        "file": filename,
        "text": text,
        "preview_id": preview_id,
        "cache_key": cache_key,
    }


def synthesize_example_audio(
    text: str,
    voice: VoiceConfig,
    language: str | None,
    sentence_pause: float,
    destination: Path,
    report: Callable[[str], None],
) -> None:
    """Generate a regular MP3, or one MP3 with deliberate sentence pauses."""
    sentences = split_example_sentences(text)
    if sentence_pause > 0 and len(sentences) > 1:
        STATE.engine.synthesize_sentences(
            sentences, voice, language, sentence_pause, destination, report
        )
    else:
        STATE.engine.synthesize(text, voice, language, destination, report)


def anki_connect(action: str, params: dict[str, Any] | None = None) -> Any:
    body = json.dumps({"action": action, "version": 6, "params": params or {}}).encode("utf-8")
    request = Request(ANKI_CONNECT_URL, data=body, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=8) as response:
            answer = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError) as error:
        raise ValueError(
            "Не удаётся подключиться к Anki. Открой Anki Desktop и установи AnkiConnect."
        ) from error
    if answer.get("error"):
        raise ValueError(f"Anki ответил ошибкой: {answer['error']}")
    return answer.get("result")


def anki_audio_helper_source() -> Path:
    """Find the helper bundled with the app, or its sibling in source mode."""
    candidates = (
        RESOURCE_DIR / "anki_audio_drag_helper",
        APP_DIR.parent / "anki_audio_drag_helper",
    )
    for folder in candidates:
        if all((folder / name).is_file() for name in ANKI_AUDIO_HELPER_FILES):
            return folder
    raise RuntimeError("В папке программы не найден помощник MP3 audio fields helper.")


def anki_audio_helper_destination() -> Path:
    roaming = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    return roaming / "Anki2" / "addons21" / "anki_audio_drag_helper"


def install_anki_audio_helper() -> dict[str, Any]:
    """Copy the bundled helper over the user's installed Anki add-on."""
    source = anki_audio_helper_source()
    destination = anki_audio_helper_destination()
    destination.mkdir(parents=True, exist_ok=True)
    for name in ANKI_AUDIO_HELPER_FILES:
        shutil.copy2(source / name, destination / name)
    return {"path": str(destination), "restart_anki": True}


def anki_status() -> dict[str, Any]:
    try:
        version = anki_connect("version")
        decks = sorted(anki_connect("deckNames"), key=lambda item: item.casefold())
        reflected = anki_connect(
            "apiReflect", {"scopes": ["actions"], "actions": ["ankiVoiceConvertAudioFields"]}
        )
        helper_ready = "ankiVoiceConvertAudioFields" in reflected.get("actions", [])
        return {"connected": True, "version": version, "decks": decks, "audio_helper_ready": helper_ready}
    except ValueError as error:
        return {"connected": False, "message": str(error), "decks": [], "audio_helper_ready": False}


def anki_notes_by_ids(note_ids: list[Any]) -> list[dict[str, Any]]:
    """Read a stable set of notes chosen in Anki's Browse window."""
    cleaned_ids: list[int] = []
    seen: set[int] = set()
    for value in note_ids:
        try:
            note_id = int(value)
        except (TypeError, ValueError):
            continue
        if note_id > 0 and note_id not in seen:
            seen.add(note_id)
            cleaned_ids.append(note_id)
    if not cleaned_ids:
        raise ValueError("В окне Browse Anki выдели одну или несколько заметок и нажми «Выбранные в Browse».")
    notes: list[dict[str, Any]] = []
    for start in range(0, len(cleaned_ids), 100):
        notes.extend(anki_connect("notesInfo", {"notes": cleaned_ids[start:start + 100]}))
    return notes


def anki_notes(deck: str) -> list[dict[str, Any]]:
    deck = as_text(deck)
    if not deck:
        raise ValueError("Выбери колоду Anki.")
    escaped = deck.replace("\\", "\\\\").replace('"', '\\"')
    note_ids = anki_connect("findNotes", {"query": f'deck:"{escaped}"'})
    notes: list[dict[str, Any]] = []
    for start in range(0, len(note_ids), 100):
        notes.extend(anki_connect("notesInfo", {"notes": note_ids[start:start + 100]}))
    return notes


def anki_notes_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if as_text(payload.get("scope")) == "selected":
        selected = payload.get("note_ids")
        return anki_notes_by_ids(selected if isinstance(selected, list) else [])
    return anki_notes(as_text(payload.get("deck")))


def anki_selected_notes() -> dict[str, Any]:
    note_ids = anki_connect("guiSelectedNotes")
    notes = anki_notes_by_ids(note_ids if isinstance(note_ids, list) else [])
    result: dict[str, Any] = {"note_ids": [int(note["noteId"]) for note in notes], "selected": len(notes)}
    if len(notes) == 1:
        result["speech_texts"] = anki_speech_texts(notes[0])
    return result


def anki_field(note: dict[str, Any], name: str) -> str:
    field_data = (note.get("fields") or {}).get(name) or {}
    return as_text(field_data.get("value"))


def anki_speech_texts(note: dict[str, Any]) -> dict[str, str]:
    """Text offered to the single-note pronunciation editor."""
    return {
        "word": plain_text(anki_field(note, "Front")),
        "translation": plain_text(anki_field(note, "Back")),
        "example": example_speech_text(anki_field(note, "Example")),
    }


def scan_anki_cards(payload: dict[str, Any]) -> dict[str, Any]:
    notes = anki_notes_from_payload(payload)
    requested = [
        field_name for enabled, field_name in (
            (bool(payload.get("make_word")), "AudioWord"),
            (bool(payload.get("make_translation")), "AudioTranslation"),
            (bool(payload.get("make_examples")), "AudioExample"),
        ) if enabled
    ]
    if not requested:
        raise ValueError("Выбери слово, перевод или примеры.")
    # Replacing the chosen role is the normal, predictable action in this
    # mode.  The UI can still explicitly request the conservative behaviour.
    only_empty = bool(payload.get("only_empty", False))
    eligible = 0
    missing_fields: set[str] = set()
    sample: dict[str, Any] | None = None
    for note in notes:
        fields = note.get("fields") or {}
        if "Front" not in fields or "Back" not in fields:
            continue
        current_missing = {field_name for field_name in requested if field_name not in fields}
        missing_fields.update(current_missing)
        if current_missing:
            continue
        sources = {
            "AudioWord": anki_field(note, "Front"),
            "AudioTranslation": anki_field(note, "Back"),
            "AudioExample": example_speech_text(anki_field(note, "Example")),
        }
        selected = [field_name for field_name in requested if sources[field_name]]
        if only_empty:
            selected = [field_name for field_name in selected if not anki_field(note, field_name)]
        if selected:
            eligible += 1
            if sample is None:
                sample = {"front": plain_text(anki_field(note, "Front")), "back": plain_text(anki_field(note, "Back")), "example": sources["AudioExample"]}
    return {
        "notes": len(notes),
        "eligible": eligible,
        "missing_fields": sorted(missing_fields),
        "sample": sample,
    }


def run_studio_audio(job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    text = as_text(payload.get("text"))
    if bool(payload.get("strip_brackets")):
        text = without_parentheses(text)
    if not text:
        raise ValueError("Введи текст для озвучивания.")
    filename = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{safe_filename(text, 'recording')}-{uuid.uuid4().hex[:5]}.mp3"
    destination = STUDIO_AUDIO_DIR / filename
    job.update(status="Создаю MP3…", progress_total=1)
    STATE.engine.synthesize(text, VoiceConfig.from_payload(payload.get("voice")), language_code(payload.get("language")), destination, lambda message: job.update(status=message))
    job.update(progress_done=1)
    return {"url": f"/studio-audio/{filename}", "file": filename, "text": text, "output": str(STUDIO_AUDIO_DIR)}


def run_anki_generation(job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    notes = anki_notes_from_payload(payload)
    make_word = bool(payload.get("make_word"))
    make_translation = bool(payload.get("make_translation"))
    make_examples = bool(payload.get("make_examples"))
    if not (make_word or make_translation or make_examples):
        raise ValueError("Выбери слово, перевод или примеры.")
    # Replacing audio is the expected action here. The interface can still
    # explicitly request the conservative "only empty fields" behaviour.
    only_empty = bool(payload.get("only_empty", False))
    example_pause = example_pause_seconds(payload.get("example_pause"))
    roles = (
        ("word", "AudioWord", "Front", make_word, VoiceConfig.from_payload(payload.get("word_voice")), language_code(payload.get("word_language"))),
        ("translation", "AudioTranslation", "Back", make_translation, VoiceConfig.from_payload(payload.get("translation_voice")), language_code(payload.get("translation_language"))),
        ("example", "AudioExample", "Example", make_examples, VoiceConfig.from_payload(payload.get("example_voice")), language_code(payload.get("example_language"))),
    )
    tasks: list[tuple[dict[str, Any], tuple[Any, ...], str, Path | None]] = []
    missing: set[str] = set()
    raw_overrides = payload.get("speech_overrides")
    speech_overrides = raw_overrides if isinstance(raw_overrides, dict) else {}
    raw_preview_audio = payload.get("preview_audio")
    # A preview belongs to one deliberately selected card, never to a deck
    # batch. This avoids accidentally applying a sample recording elsewhere.
    can_reuse_preview = as_text(payload.get("scope")) == "selected" and len(notes) == 1
    preview_audio = raw_preview_audio if can_reuse_preview and isinstance(raw_preview_audio, dict) else {}
    for note in notes:
        fields = note.get("fields") or {}
        note_id = int(note["noteId"])
        note_overrides = speech_overrides.get(str(note_id), speech_overrides.get(note_id, {}))
        note_overrides = note_overrides if isinstance(note_overrides, dict) else {}
        for role in roles:
            role_name, audio_field, source_field, enabled, _voice, _language = role
            if not enabled:
                continue
            if audio_field not in fields:
                missing.add(audio_field)
                continue
            override = as_text(note_overrides.get(role_name))
            if override:
                # The editor contains the exact pronunciation text. In
                # particular, it keeps the user's capitals and punctuation.
                text = plain_text(override)
            else:
                source = anki_field(note, source_field)
                text = example_speech_text(source) if source_field == "Example" else plain_text(source)
            if bool(payload.get("strip_brackets")):
                text = without_parentheses(text)
            if text and (not only_empty or not anki_field(note, audio_field)):
                pause = example_pause if role_name == "example" else 0.0
                fragment_mode = "translation" if role_name == "translation" else ""
                expected_key = speech_cache_key(text, _voice, _language, pause, fragment_mode)
                cached_details = preview_audio.get(role_name)
                cached_preview = None
                if isinstance(cached_details, dict):
                    cached_preview = STATE.preview_file(
                        as_text(cached_details.get("preview_id")),
                        as_text(cached_details.get("cache_key")),
                    )
                    if as_text(cached_details.get("cache_key")) != expected_key:
                        cached_preview = None
                tasks.append((note, role, text, cached_preview))
    if missing:
        raise ValueError("В типе заметок нет полей: " + ", ".join(sorted(missing)) + ". Добавь их в Anki перед запуском.")
    if not tasks:
        return {"notes": 0, "audio_files": 0, "output": "", "skipped": len(notes)}
    # Do not reuse a media filename for the same note/text. Anki's media
    # layer and embedded players may retain an older file with that name.
    # A fresh generation must always point to a fresh recording.
    generation_id = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4().hex[:8]}"
    output = OUTPUTS_DIR / f"anki_{generation_id}"
    audio_dir = output / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    job.update(status="Подготавливаю модель…", progress_total=len(tasks))
    updates: list[dict[str, Any]] = []
    media_by_note: dict[int, list[dict[str, Any]]] = {}
    expected_audio: dict[int, dict[str, str]] = {}
    reused_previews = 0
    for index, (note, role, text, cached_preview) in enumerate(tasks, start=1):
        role_name, audio_field, _source_field, _enabled, voice, language = role
        note_id = int(note["noteId"])
        digest = hashlib.sha1(f"{note_id}|{role_name}|{text}".encode("utf-8")).hexdigest()[:8]
        filename = f"anki-{generation_id}-{note_id}-{role_name}-{digest}.mp3"
        destination = audio_dir / filename
        if cached_preview is not None:
            job.update(status=f"Использую предпрослушивание {index}/{len(tasks)}: заметка {note_id}, {role_name}")
            shutil.copy2(cached_preview, destination)
            reused_previews += 1
        else:
            job.update(status=f"Аудио {index}/{len(tasks)}: заметка {note_id}, {role_name}")
            if role_name == "example":
                synthesize_example_audio(
                    text, voice, language, example_pause, destination,
                    lambda message: job.update(status=message),
                )
            elif role_name == "translation":
                STATE.engine.synthesize_translation(text, voice, language, destination, lambda message: job.update(status=message))
            else:
                STATE.engine.synthesize(text, voice, language, destination, lambda message: job.update(status=message))
        previous = anki_field(note, audio_field)
        # Let AnkiConnect attach media through its own API.  Supplying an
        # <audio> element as a field value looks fine in a browser but Anki's
        # field sanitizer strips it on update; the `audio` payload produces
        # the native [sound:filename.mp3] entry instead.
        media_by_note.setdefault(note_id, []).append({
            "filename": filename,
            "data": base64.b64encode(destination.read_bytes()).decode("ascii"),
            "fields": [audio_field],
        })
        expected_audio.setdefault(note_id, {})[audio_field] = filename
        updates.append({"note_id": note_id, "field": audio_field, "previous": previous, "audio": filename})
        job.update(progress_done=index)
    # Send every selected field for a note together.  Clearing only these
    # fields first makes the "replace existing audio" option honest, while
    # AnkiConnect appends its native sound markup straight afterwards.
    for note_id, media in media_by_note.items():
        fields = {field_name: "" for field_name in expected_audio[note_id]}
        anki_connect("updateNoteFields", {"note": {"id": note_id, "fields": fields, "audio": media}})
    # AnkiConnect is the safe way to import media, and it may add a hash to
    # filenames. Read that final filename before asking our tiny Anki helper
    # to convert [sound:…] into <audio>. Native sound tags autoplay outside
    # the template's queue, while HTML players give the template full control.
    verified_notes = {int(note["noteId"]): note for note in anki_notes_by_ids(list(expected_audio))}
    failed_fields: list[str] = []
    expected_players: dict[int, dict[str, str]] = {}
    for note_id, fields in expected_audio.items():
        note = verified_notes.get(note_id)
        for field_name, filename in fields.items():
            stored = anki_field(note, field_name) if note else ""
            expected_stem = Path(filename).stem
            actual_filename = anki_sound_filename(stored)
            if not actual_filename or not actual_filename.startswith(expected_stem):
                failed_fields.append(f"{note_id}: {field_name}")
                continue
            expected_players.setdefault(note_id, {})[field_name] = actual_filename
    if failed_fields:
        raise RuntimeError("Anki не прикрепил аудио к полям: " + ", ".join(failed_fields))
    try:
        anki_connect(
            "ankiVoiceConvertAudioFields",
            {"noteIds": list(expected_audio), "fields": ["AudioWord", "AudioTranslation", "AudioExample"]},
        )
    except ValueError as error:
        raise RuntimeError(
            "MP3 сохранены, но помощник MP3 audio fields helper не обновлён. "
            "Установи его новую версию и перезапусти Anki, затем запусти добавление ещё раз."
        ) from error
    player_notes = {int(note["noteId"]): note for note in anki_notes_by_ids(list(expected_audio))}
    failed_players: list[str] = []
    for note_id, fields in expected_players.items():
        note = player_notes.get(note_id)
        for field_name, expected_filename in fields.items():
            stored_filename = anki_audio_player_filename(anki_field(note, field_name)) if note else ""
            if stored_filename != expected_filename:
                failed_players.append(f"{note_id}: {field_name}")
    if failed_players:
        raise RuntimeError("Помощник не превратил MP3 в плееры: " + ", ".join(failed_players))
    (output / "changes.json").write_text(json.dumps(updates, ensure_ascii=False, indent=2), encoding="utf-8")
    updated_note_ids = {int(note["noteId"]) for note, _role, _text, _preview in tasks}
    return {
        "notes": len(updated_note_ids),
        "audio_files": len(tasks),
        "reused_previews": reused_previews,
        "output": str(output),
        "skipped": len(notes) - len(updated_note_ids),
    }


def run_generation(job: Job, payload: dict[str, Any]) -> dict[str, Any]:
    cards = validated_cards(as_text(payload.get("cards")))
    make_word = bool(payload.get("make_word"))
    make_translation = bool(payload.get("make_translation"))
    make_examples = bool(payload.get("make_examples"))
    if not make_word and not make_translation and not make_examples:
        raise ValueError("Выбери, что озвучивать: слово, перевод или примеры.")
    word_voice = VoiceConfig.from_payload(payload.get("word_voice"))
    translation_voice = VoiceConfig.from_payload(payload.get("translation_voice"))
    example_voice = VoiceConfig.from_payload(payload.get("example_voice"))
    strip_brackets = bool(payload.get("strip_brackets"))
    example_pause = example_pause_seconds(payload.get("example_pause"))
    # Every set owns its audio names. In particular, repeated test cards
    # must not accidentally reuse an earlier MP3 in Anki's media cache.
    batch_id = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}-{uuid.uuid4().hex[:8]}"
    output = OUTPUTS_DIR / batch_id
    audio_dir = output / "audio"
    output.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)

    job_count = len(cards) * (int(make_word) + int(make_translation) + int(make_examples))
    job.update(status="Подготавливаю модель…", progress_total=job_count)
    rows: list[dict[str, str]] = []
    done = 0
    roles = (
        ("word", "AudioWord", "Front", make_word, word_voice, language_code(payload.get("word_language"))),
        ("translation", "AudioTranslation", "Back", make_translation, translation_voice, language_code(payload.get("translation_language"))),
        ("example", "AudioExample", "Example", make_examples, example_voice, language_code(payload.get("example_language"))),
    )

    for index, original in enumerate(cards, start=1):
        row = normalise_card(original)
        slug = safe_filename(row["Front"], f"card-{index}")
        digest = hashlib.sha1(f"{index}|{row['Front']}|{row['Back']}".encode("utf-8")).hexdigest()[:8]
        for role, audio_field, text_field, enabled, voice, language in roles:
            if not enabled:
                continue
            text = row[text_field]
            if role == "example":
                text = example_speech_text(text)
            if strip_brackets:
                text = without_parentheses(text)
            if not text:
                raise ValueError(f"Карточка №{index}: пустое поле {text_field}.")
            filename = f"{batch_id}-{index:04d}-{slug}-{role}-{digest}.mp3"
            job.update(status=f"Аудио {done + 1}/{job_count}: карточка {index}, {role}")
            if role == "example":
                synthesize_example_audio(
                    text, voice, language, example_pause, audio_dir / filename,
                    lambda message: job.update(status=message),
                )
            elif role == "translation":
                STATE.engine.synthesize_translation(text, voice, language, audio_dir / filename, lambda message: job.update(status=message))
            else:
                STATE.engine.synthesize(text, voice, language, audio_dir / filename, lambda message: job.update(status=message))
            row[audio_field] = html_audio(filename)
            done += 1
            job.update(progress_done=done)
        rows.append(row)

    csv_path = output / "anki_cards.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS, delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    helper_path = write_anki_audio_helper(output)

    copied = 0
    collection_media = as_text(payload.get("collection_media"))
    if collection_media:
        target = Path(collection_media).expanduser()
        if not target.is_dir():
            raise ValueError("Указанная папка collection.media не существует.")
        for audio_file in audio_dir.glob("*.mp3"):
            shutil.copy2(audio_file, target / audio_file.name)
            copied += 1
    return {
        "output": str(output),
        "pack_id": output.name,
        "csv": str(csv_path),
        "audio_files": done,
        "copied_to_media": copied,
        "helper": str(helper_path),
    }


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "AnkiVoiceStudio/0.1"

    def log_message(self, *_args: Any) -> None:
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/profiles":
            return self.send_json({"profiles": STATE.profiles()})
        if parsed.path == "/api/components":
            return self.send_json(component_status())
        if parsed.path == "/api/anki/status":
            return self.send_json(anki_status())
        if parsed.path == "/api/anki/media-targets":
            return self.send_json({"targets": anki_media_targets()})
        if parsed.path.startswith("/api/jobs/"):
            job = STATE.get_job(parsed.path.rsplit("/", 1)[-1])
            if not job:
                return self.send_error_json(HTTPStatus.NOT_FOUND, "Задача не найдена.")
            return self.send_json(job.snapshot())
        if parsed.path.startswith("/previews/"):
            return self.serve_file(PREVIEWS_DIR / Path(unquote(parsed.path)).name, "audio/mpeg")
        if parsed.path.startswith("/studio-audio/"):
            return self.serve_file(STUDIO_AUDIO_DIR / Path(unquote(parsed.path)).name, "audio/mpeg")
        if parsed.path == "/" or parsed.path == "/index.html":
            return self.serve_file(WEB_DIR / "index.html", "text/html; charset=utf-8")
        if parsed.path == "/app.css":
            return self.serve_file(WEB_DIR / "app.css", "text/css; charset=utf-8")
        if parsed.path == "/app.js":
            return self.serve_file(WEB_DIR / "app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/assets/anki-voice-studio.svg":
            return self.serve_file(WEB_DIR / "assets" / "anki-voice-studio.svg", "image/svg+xml")
        return self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/validate":
                data = self.read_json()
                cards = validated_cards(as_text(data.get("cards")))
                return self.send_json({"count": len(cards), "sample": normalise_card(cards[0])})
            if parsed.path == "/api/components/install":
                job = STATE.start("components", install_missing_components)
                return self.send_json({"job_id": job.id}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/preview":
                data = self.read_json()
                job = STATE.start("preview", lambda task: run_preview(task, data))
                return self.send_json({"job_id": job.id}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/generate":
                data = self.read_json()
                job = STATE.start("generation", lambda task: run_generation(task, data))
                return self.send_json({"job_id": job.id}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/pack/copy-to-anki":
                data = self.read_json()
                job = STATE.start("pack-copy", lambda task: copy_generated_pack_to_anki(task, data))
                return self.send_json({"job_id": job.id}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/studio-generate":
                data = self.read_json()
                job = STATE.start("studio", lambda task: run_studio_audio(task, data))
                return self.send_json({"job_id": job.id}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/promote-generated-reference":
                return self.send_json(self.promote_generated_reference(self.read_json()))
            if parsed.path == "/api/anki/scan":
                return self.send_json(scan_anki_cards(self.read_json()))
            if parsed.path == "/api/anki/selected":
                return self.send_json(anki_selected_notes())
            if parsed.path == "/api/anki/helper/install":
                return self.send_json(install_anki_audio_helper())
            if parsed.path == "/api/anki/generate":
                data = self.read_json()
                job = STATE.start("anki", lambda task: run_anki_generation(task, data))
                return self.send_json({"job_id": job.id}, HTTPStatus.ACCEPTED)
            if parsed.path == "/api/pick-collection-media":
                return self.send_json({"path": choose_collection_media_folder()})
            if parsed.path == "/api/profile":
                data = self.read_json()
                saved = STATE.save_profile(as_text(data.get("name")), VoiceConfig.from_payload(data.get("profile")))
                return self.send_json(saved)
            if parsed.path == "/api/delete-profile":
                data = self.read_json()
                STATE.delete_profile(as_text(data.get("name")))
                return self.send_json({"ok": True})
            if parsed.path == "/api/delete-reference":
                data = self.read_json()
                return self.send_json({"affected_profiles": STATE.delete_reference(as_text(data.get("path")))})
            if parsed.path == "/api/upload-reference":
                return self.upload_reference()
            if parsed.path == "/api/open-folder":
                data = self.read_json()
                folder = Path(as_text(data.get("path"))).resolve()
                permitted_roots = (OUTPUTS_DIR.resolve(), STUDIO_AUDIO_DIR.resolve())
                if not folder.is_dir() or not any(root in (folder, *folder.parents) for root in permitted_roots):
                    raise ValueError("Можно открыть только папку результата этой программы.")
                os.startfile(str(folder))
                return self.send_json({"ok": True})
            if parsed.path == "/api/close":
                if STATE.has_active_job():
                    raise ValueError("Wait until audio creation finishes before closing Anki Voice Studio.")
                threading.Timer(0.2, self.server.shutdown).start()
                return self.send_json({"ok": True})
            return self.send_error_json(HTTPStatus.NOT_FOUND, "Неизвестная команда.")
        except ValueError as error:
            return self.send_error_json(HTTPStatus.BAD_REQUEST, str(error))
        except Exception as error:
            print(traceback.format_exc())
            return self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))

    def read_json(self) -> dict[str, Any]:
        size = int(self.headers.get("Content-Length", "0"))
        if size > 8_000_000:
            raise ValueError("Слишком большой запрос.")
        raw = self.rfile.read(size)
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Ожидались настройки в формате JSON.")
        return data

    def upload_reference(self) -> None:
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("Не найден аудиофайл.")
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
        )
        item = form["audio"] if "audio" in form else None
        if item is None or not getattr(item, "filename", ""):
            raise ValueError("Выбери файл с образцом голоса.")
        extension = Path(item.filename).suffix.lower()
        if extension not in {".wav", ".mp3", ".m4a", ".flac", ".ogg"}:
            raise ValueError("Подойдут WAV, MP3, M4A, FLAC или OGG.")
        content = item.file.read()
        if not content or len(content) > 60 * 1024 * 1024:
            raise ValueError("Файл пустой или превышает 60 МБ.")
        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}{extension}"
        path = REFERENCES_DIR / filename
        path.write_bytes(content)
        self.send_json({"path": str(path), "name": Path(item.filename).name})

    def promote_generated_reference(self, data: dict[str, Any]) -> dict[str, str]:
        """Promote one freshly generated take into a clone reference safely."""
        text = as_text(data.get("text")).strip()
        if not text:
            raise ValueError("У записи нет текста для образца голоса.")
        kind = as_text(data.get("kind"))
        if kind == "preview":
            source = STATE.preview_file(as_text(data.get("preview_id")), as_text(data.get("cache_key")))
            if source is None:
                raise ValueError("Предпрослушивание уже недоступно. Создай его ещё раз.")
        elif kind == "studio":
            source = STUDIO_AUDIO_DIR / Path(as_text(data.get("file"))).name
        else:
            raise ValueError("Неизвестный источник записи.")
        if not source.is_file():
            raise ValueError("Запись для образца не найдена.")
        REFERENCES_DIR.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-generated-{uuid.uuid4().hex[:8]}.mp3"
        destination = REFERENCES_DIR / filename
        shutil.copy2(source, destination)
        return {"path": str(destination), "name": filename, "reference_text": text}

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.is_file():
            return self.send_error(HTTPStatus.NOT_FOUND)
        content = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, data: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_error_json(self, status: HTTPStatus, message: str) -> None:
        self.send_json({"error": message}, status)


def main() -> None:
    for directory in (OUTPUTS_DIR, PREVIEWS_DIR, STUDIO_AUDIO_DIR, REFERENCES_DIR):
        directory.mkdir(exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), RequestHandler)
    url = f"http://{HOST}:{PORT}"
    print(f"Anki Voice Studio is ready at {url}")
    # Used by the release smoke test. Normal users never set this variable and
    # still get the browser window automatically.
    if getattr(sys, "frozen", False) and not os.environ.get("ANKI_VOICE_NO_BROWSER"):
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
