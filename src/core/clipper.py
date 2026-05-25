"""Финальный рендер клипа через FFmpeg. NVENC если доступен, иначе libx264."""

from __future__ import annotations

import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..app_config import VideoConfig, PathsConfig, SubtitlesConfig
from .hardware import HardwareProfile, resolve_encoder
from .reframer import build_reframe_filter


ProgressCb = Optional[Callable[[float, str], None]]


@dataclass
class ClipJob:
    source: Path
    start: float
    duration: float
    subs_path: Path | None
    out_path: Path
    title: str


def _encoder_args(encoder: str, video: VideoConfig) -> list[str]:
    """Аргументы кодировщика — NVENC или libx264."""
    if encoder.endswith("_nvenc"):
        return [
            "-c:v", encoder,
            "-preset", video.nvenc_preset,
            "-tune", "hq",
            "-rc", "vbr",
            "-cq", str(video.cq),
            "-b:v", "0",
            "-maxrate", video.max_bitrate,
            "-bufsize", "20M",
            "-pix_fmt", "yuv420p",
            "-profile:v", "high",
            "-bf", "3",
            "-spatial-aq", "1",
            "-temporal-aq", "1",
        ]
    return [
        "-c:v", encoder,
        "-preset", "medium",
        "-crf", str(video.cq),
        "-pix_fmt", "yuv420p",
        "-profile:v", "high",
    ]


def _escape_subs_path(p: Path) -> str:
    """В фильтре subtitles=PATH спецсимволы (двоеточие, обратный слэш на Windows)
    нужно экранировать."""
    s = str(p.resolve())
    if sys.platform.startswith("win"):
        s = s.replace("\\", "/").replace(":", "\\:")
    else:
        s = s.replace(":", "\\:")
    return s


def render_clip(
    job: ClipJob,
    video: VideoConfig,
    subs_cfg: SubtitlesConfig,
    paths: PathsConfig,
    hw: HardwareProfile,
    on_progress: ProgressCb = None,
) -> Path:
    """Рендерим один клип: трим -> 9:16 -> субтитры -> NVENC/libx264."""
    encoder = resolve_encoder(video.encoder, hw)
    job.out_path.parent.mkdir(parents=True, exist_ok=True)

    reframe = build_reframe_filter(video)

    # Если есть субтитры — добавляем фильтр subtitles= после reframe
    if job.subs_path and job.subs_path.exists():
        subs_esc = _escape_subs_path(job.subs_path)
        filter_complex = f"{reframe};[v]subtitles='{subs_esc}'[vout]"
        video_label = "[vout]"
    else:
        filter_complex = reframe
        video_label = "[v]"

    # Используем -ss перед -i для быстрого input seek + -ss после для точного среза
    # Точный seek работает с реэнкодом, что у нас и так есть
    hw_decode = []
    if encoder.endswith("_nvenc") and hw.cuda_available:
        # CUDA hardware-decoding входного видео для разгрузки CPU
        # NB: некоторые форматы могут не поддерживаться — фоллбэк ниже
        hw_decode = ["-hwaccel", "cuda"]

    cmd = [
        paths.ffmpeg, "-y", "-hide_banner",
        *hw_decode,
        "-ss", f"{max(job.start - 0.5, 0):.3f}",
        "-i", str(job.source),
        "-ss", f"{0.5 if job.start > 0.5 else 0:.3f}",
        "-t", f"{job.duration:.3f}",
        "-filter_complex", filter_complex,
        "-map", video_label,
        "-map", "0:a?",
        *_encoder_args(encoder, video),
        "-r", str(video.fps),
        "-c:a", "aac",
        "-b:a", "192k",
        "-ar", "48000",
        "-movflags", "+faststart",
        str(job.out_path),
    ]

    if on_progress:
        on_progress(0.0, f"Рендер: {job.out_path.name}")

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        # Пробуем без hwaccel — часть проблем уйдёт
        if hw_decode:
            cmd_no_hw = [c for c in cmd if c not in ("-hwaccel", "cuda")]
            proc = subprocess.run(cmd_no_hw, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"FFmpeg failed (code {proc.returncode}):\n"
                f"CMD: {shlex.join(cmd)}\n"
                f"STDERR:\n{proc.stderr[-2000:]}"
            )

    if on_progress:
        on_progress(1.0, f"Готов: {job.out_path.name}")
    return job.out_path
