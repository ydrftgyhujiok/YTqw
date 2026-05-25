"""Профили каналов: настройки рендера и папки-источники под конкретный канал."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .app_config import (
    AnalysisConfig, SubtitlesConfig, VideoConfig,
)


PROFILES_DIR = Path.home() / ".ai_clip_gen" / "profiles"


@dataclass
class Profile:
    """Все настройки, специфичные для одного канала.

    Глобальные настройки (Whisper, Ollama, FFmpeg-путь и т.д.) остаются в AppConfig.
    """
    name: str = "Default"
    source_dir: str = ""              # Папка с исходными видео для этого канала
    output_dir: str = "./output/default"
    video: VideoConfig = field(default_factory=VideoConfig)
    subtitles: SubtitlesConfig = field(default_factory=SubtitlesConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        def merge(dc_cls, raw):
            if raw is None:
                return dc_cls()
            return dc_cls(**{k: v for k, v in raw.items() if k in dc_cls.__dataclass_fields__})

        return cls(
            name=str(data.get("name", "Default")),
            source_dir=str(data.get("source_dir", "")),
            output_dir=str(data.get("output_dir", "./output/default")),
            video=merge(VideoConfig, data.get("video")),
            subtitles=merge(SubtitlesConfig, data.get("subtitles")),
            analysis=merge(AnalysisConfig, data.get("analysis")),
        )

    @property
    def slug(self) -> str:
        return slugify(self.name)


def slugify(name: str) -> str:
    """Безопасное имя файла из имени профиля."""
    s = re.sub(r"[^\w\-]+", "_", name.strip(), flags=re.UNICODE)
    s = re.sub(r"_+", "_", s).strip("_")
    return s.lower() or "profile"


def _path_for(slug: str) -> Path:
    return PROFILES_DIR / f"{slug}.yaml"


def list_profiles() -> list[Profile]:
    """Все профили на диске. Если их нет — создаёт Default."""
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    profiles: list[Profile] = []
    for p in sorted(PROFILES_DIR.glob("*.yaml")):
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            profiles.append(Profile.from_dict(data))
        except Exception:
            continue
    if not profiles:
        default = Profile(name="Default")
        save_profile(default)
        profiles.append(default)
    return profiles


def load_profile(slug_or_name: str) -> Profile | None:
    slug = slugify(slug_or_name)
    p = _path_for(slug)
    if not p.exists():
        # Fallback: ищем по name среди всех
        for prof in list_profiles():
            if prof.slug == slug:
                return prof
        return None
    with open(p, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Profile.from_dict(data)


def save_profile(profile: Profile) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = _path_for(profile.slug)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(profile.to_dict(), f, allow_unicode=True, sort_keys=False)
    return path


def delete_profile(slug_or_name: str) -> bool:
    p = _path_for(slugify(slug_or_name))
    if p.exists():
        p.unlink()
        return True
    return False


def rename_profile(old_name: str, new_name: str) -> Profile | None:
    """Переименование = удалить старый файл, сохранить с новым slug'ом."""
    prof = load_profile(old_name)
    if not prof:
        return None
    delete_profile(old_name)
    prof.name = new_name
    save_profile(prof)
    return prof


def duplicate_profile(source_name: str, new_name: str) -> Profile | None:
    prof = load_profile(source_name)
    if not prof:
        return None
    prof.name = new_name
    save_profile(prof)
    return prof
