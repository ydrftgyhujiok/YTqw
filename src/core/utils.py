"""Утилиты общего назначения."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def sanitize_filename(name: str, max_len: int = 120) -> str:
    """Заменяем недопустимые в имени файла символы."""
    name = re.sub(r"[^\w\-\. ]", "_", name, flags=re.UNICODE)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:max_len] or "clip"


def format_timestamp(seconds: float, ass: bool = False) -> str:
    """Форматируем время для SRT или ASS субтитров."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds - h * 3600 - m * 60
    if ass:
        # ASS: H:MM:SS.cs (центисекунды)
        cs = int(round((s - int(s)) * 100))
        return f"{h}:{m:02d}:{int(s):02d}.{cs:02d}"
    # SRT: HH:MM:SS,mmm
    ms = int(round((s - int(s)) * 1000))
    return f"{h:02d}:{m:02d}:{int(s):02d},{ms:03d}"


def ffprobe_duration(ffprobe: str, file: Path) -> float:
    """Длительность файла через ffprobe."""
    cmd = [
        ffprobe, "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json", str(file),
    ]
    out = subprocess.check_output(cmd, encoding="utf-8")
    return float(json.loads(out)["format"]["duration"])


def ffprobe_resolution(ffprobe: str, file: Path) -> tuple[int, int]:
    """Возвращает (width, height) первой видео-дорожки."""
    cmd = [
        ffprobe, "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json", str(file),
    ]
    out = subprocess.check_output(cmd, encoding="utf-8")
    data = json.loads(out)
    s = data["streams"][0]
    return int(s["width"]), int(s["height"])


def check_binary(binary: str) -> bool:
    """Доступен ли бинарь в PATH."""
    return shutil.which(binary) is not None


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
