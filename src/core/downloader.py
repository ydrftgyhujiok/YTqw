"""Загрузка видео — локальные файлы или URL через yt-dlp."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional
import re


ProgressCb = Optional[Callable[[float, str], None]]


def is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s.strip(), flags=re.IGNORECASE))


def download_video(source: str, work_dir: Path, on_progress: ProgressCb = None) -> Path:
    """Если source — URL, качаем через yt-dlp в work_dir. Иначе возвращаем как есть."""
    if not is_url(source):
        p = Path(source).expanduser().resolve()
        if not p.exists():
            raise FileNotFoundError(f"Файл не найден: {p}")
        if on_progress:
            on_progress(1.0, f"Локальный файл: {p.name}")
        return p

    work_dir.mkdir(parents=True, exist_ok=True)
    # Импортируем лениво — yt-dlp может не быть установлен в dev-окружении
    import yt_dlp  # type: ignore

    def hook(d):
        if not on_progress:
            return
        if d.get("status") == "downloading":
            pct_str = d.get("_percent_str", "0%").strip().replace("%", "")
            try:
                pct = float(pct_str) / 100.0
            except ValueError:
                pct = 0.0
            on_progress(pct, f"Скачивание {d.get('_percent_str','?')} @ {d.get('_speed_str','?')}")
        elif d.get("status") == "finished":
            on_progress(1.0, "Скачивание завершено")

    ydl_opts = {
        "outtmpl": str(work_dir / "%(id)s.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b[height<=1080]/best",
        "merge_output_format": "mp4",
        "progress_hooks": [hook],
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(source, download=True)
        path = Path(ydl.prepare_filename(info))
        # yt-dlp может поменять расширение при merge
        if not path.exists():
            for ext in ("mp4", "mkv", "webm"):
                candidate = path.with_suffix(f".{ext}")
                if candidate.exists():
                    path = candidate
                    break
        return path
