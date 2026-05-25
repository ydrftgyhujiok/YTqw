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
    # Физически есть NVIDIA GPU (по nvidia-smi), даже если torch.cuda не видит
    nvidia_present: bool
    nvidia_driver: str
    torch_version: str
    torch_cuda_version: str


def _probe_nvidia_smi() -> tuple[bool, str, str]:
    """Видит ли драйвер NVIDIA GPU. Независимо от torch."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name,driver_version",
             "--format=csv,noheader"],
            encoding="utf-8", stderr=subprocess.STDOUT, timeout=5,
        )
        line = out.strip().splitlines()[0] if out.strip() else ""
        parts = [p.strip() for p in line.split(",")]
        name = parts[0] if parts else ""
        drv = parts[1] if len(parts) > 1 else ""
        return bool(name), name, drv
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False, "", ""


def _probe_torch() -> tuple[str, str]:
    """Возвращает (torch_version, cuda_version_compiled_against)."""
    try:
        import torch  # type: ignore
        return torch.__version__, (torch.version.cuda or "")
    except Exception:
        return "", ""


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
    nvidia_present, nvidia_name, nvidia_drv = _probe_nvidia_smi()
    torch_ver, torch_cuda = _probe_torch()

    # Если nvidia-smi видит GPU, но torch — нет, заполним имя для отчётов
    if not gpu_name and nvidia_name:
        gpu_name = nvidia_name

    return HardwareProfile(
        cuda_available=cuda,
        gpu_name=gpu_name,
        vram_gb=vram,
        cpu_threads=os.cpu_count() or 4,
        nvenc_available=nvenc,
        nvenc_encoders=encs,
        nvidia_present=nvidia_present,
        nvidia_driver=nvidia_drv,
        torch_version=torch_ver,
        torch_cuda_version=torch_cuda,
    )


def cuda_misconfigured(hw: HardwareProfile) -> bool:
    """NVIDIA GPU физически есть, но torch его не видит — почти всегда
    значит что PyTorch установлен в CPU-only сборке."""
    return hw.nvidia_present and not hw.cuda_available


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
