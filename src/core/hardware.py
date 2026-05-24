"""Определение возможностей железа (GPU, NVENC, CPU)."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass
class HardwareProfile:
    cuda_available: bool
    gpu_name: str
    vram_gb: float
    cpu_threads: int
    nvenc_available: bool
    nvenc_encoders: tuple[str, ...]


def _probe_cuda() -> tuple[bool, str, float]:
    try:
        import torch  # type: ignore
        if not torch.cuda.is_available():
            return False, "", 0.0
        idx = torch.cuda.current_device()
        name = torch.cuda.get_device_name(idx)
        props = torch.cuda.get_device_properties(idx)
        vram_gb = props.total_memory / (1024 ** 3)
        return True, name, round(vram_gb, 1)
    except Exception:
        return False, "", 0.0


def _probe_nvenc(ffmpeg: str = "ffmpeg") -> tuple[bool, tuple[str, ...]]:
    """Парсим `ffmpeg -hide_banner -encoders` и ищем nvenc."""
    try:
        out = subprocess.check_output(
            [ffmpeg, "-hide_banner", "-encoders"],
            encoding="utf-8", stderr=subprocess.STDOUT,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False, ()
    encs = []
    for line in out.splitlines():
        line = line.strip()
        if "nvenc" in line.lower():
            parts = line.split()
            if len(parts) >= 2:
                encs.append(parts[1])
    return bool(encs), tuple(encs)


def detect_hardware(ffmpeg: str = "ffmpeg") -> HardwareProfile:
    cuda, gpu_name, vram = _probe_cuda()
    nvenc, encs = _probe_nvenc(ffmpeg)
    return HardwareProfile(
        cuda_available=cuda,
        gpu_name=gpu_name,
        vram_gb=vram,
        cpu_threads=os.cpu_count() or 4,
        nvenc_available=nvenc,
        nvenc_encoders=encs,
    )


def resolve_whisper_device(requested: str, hw: HardwareProfile) -> str:
    """auto -> cuda/cpu в зависимости от наличия CUDA."""
    if requested == "auto":
        return "cuda" if hw.cuda_available else "cpu"
    return requested


def resolve_compute_type(requested: str, device: str) -> str:
    """На CPU float16 невозможен — даунгрейдим."""
    if device == "cpu" and requested in {"float16", "fp16"}:
        return "int8"
    return requested


def resolve_encoder(requested: str, hw: HardwareProfile) -> str:
    """Если NVENC недоступен — фоллбэк на libx264."""
    if requested.endswith("_nvenc") and not hw.nvenc_available:
        return "libx264"
    return requested
