"""Конфигурация приложения. Загружается из YAML, перезаписывается из GUI."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"
USER_CONFIG_PATH = Path.home() / ".ai_clip_gen" / "config.yaml"


@dataclass
class PathsConfig:
    output_dir: str = "./output"
    work_dir: str = "./work"
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"


@dataclass
class WhisperConfig:
    model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "float16"
    batch_size: int = 16
    language: str = "auto"
    # Если True — пропускаем word-level alignment (вдвое быстрее, но субтитры
    # будут на уровне сегментов, без подсветки текущего слова)
    skip_alignment: bool = False


@dataclass
class OllamaConfig:
    host: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    temperature: float = 0.4
    num_predict: int = 4096
    num_ctx: int = 16384


@dataclass
class AnalysisConfig:
    chunk_seconds: int = 600
    min_clip_seconds: int = 20
    max_clip_seconds: int = 75
    max_clips_per_video: int = 12
    min_score: float = 6.5


@dataclass
class VideoConfig:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    encoder: str = "h264_nvenc"
    nvenc_preset: str = "p5"
    cq: int = 21
    max_bitrate: str = "12M"
    reframe_mode: str = "center_blur"
    blur_strength: int = 25


@dataclass
class SubtitlesConfig:
    style: str = "word_by_word"
    font: str = "Arial"
    font_size: int = 18
    primary_color: str = "&H00FFFFFF"
    highlight_color: str = "&H0000FFFF"
    outline_color: str = "&H00000000"
    outline_thickness: int = 3
    shadow: int = 1
    bottom_margin: int = 360
    max_chars_per_line: int = 22
    uppercase: bool = False


@dataclass
class ProcessingConfig:
    parallel_clips: int = 3
    parallel_videos: int = 1


@dataclass
class AppConfig:
    paths: PathsConfig = field(default_factory=PathsConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    video: VideoConfig = field(default_factory=VideoConfig)
    subtitles: SubtitlesConfig = field(default_factory=SubtitlesConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        def merge(dc_cls, raw):
            if raw is None:
                return dc_cls()
            return dc_cls(**{k: v for k, v in raw.items() if k in dc_cls.__dataclass_fields__})

        return cls(
            paths=merge(PathsConfig, data.get("paths")),
            whisper=merge(WhisperConfig, data.get("whisper")),
            ollama=merge(OllamaConfig, data.get("ollama")),
            analysis=merge(AnalysisConfig, data.get("analysis")),
            video=merge(VideoConfig, data.get("video")),
            subtitles=merge(SubtitlesConfig, data.get("subtitles")),
            processing=merge(ProcessingConfig, data.get("processing")),
        )


def load_config() -> AppConfig:
    """Грузим пользовательский конфиг если есть, иначе дефолтный."""
    if USER_CONFIG_PATH.exists():
        path = USER_CONFIG_PATH
    elif DEFAULT_CONFIG_PATH.exists():
        path = DEFAULT_CONFIG_PATH
    else:
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return AppConfig.from_dict(raw)


def save_config(cfg: AppConfig) -> Path:
    USER_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(USER_CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg.to_dict(), f, allow_unicode=True, sort_keys=False)
    return USER_CONFIG_PATH
