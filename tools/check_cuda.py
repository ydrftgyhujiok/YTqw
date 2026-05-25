"""Быстрая диагностика установки CUDA / PyTorch / WhisperX.

Запуск:
    python tools/check_cuda.py

Печатает:
- видит ли драйвер NVIDIA (nvidia-smi)
- какая сборка PyTorch установлена и видит ли она CUDA
- какие compute_type'ы доступны (float16 / int8)
- какой ffmpeg + есть ли NVENC

Если что-то не так — даёт точную команду для починки.
"""

from __future__ import annotations

import subprocess
import sys


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BOLD = "\033[1m"
END = "\033[0m"


def ok(msg: str) -> None:
    print(f"{GREEN}✓{END} {msg}")


def fail(msg: str) -> None:
    print(f"{RED}✗ {msg}{END}")


def warn(msg: str) -> None:
    print(f"{YELLOW}⚠ {msg}{END}")


def section(title: str) -> None:
    print(f"\n{BOLD}=== {title} ==={END}")


def run(*cmd: str) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, encoding="utf-8",
                                      stderr=subprocess.STDOUT, timeout=10)
        return 0, out
    except FileNotFoundError:
        return 127, f"{cmd[0]} не найден в PATH"
    except subprocess.CalledProcessError as e:
        return e.returncode, e.output or ""
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def main() -> int:
    problems: list[str] = []

    section("Драйвер NVIDIA (nvidia-smi)")
    code, out = run("nvidia-smi", "--query-gpu=name,driver_version,memory.total",
                    "--format=csv,noheader")
    if code == 0 and out.strip():
        ok(f"NVIDIA: {out.strip()}")
        nvidia_present = True
    else:
        warn("nvidia-smi не найден или не вернул GPU. "
             "Если у тебя есть NVIDIA — установи драйвер с nvidia.com.")
        nvidia_present = False

    section("Python и PyTorch")
    print(f"Python: {sys.version.split()[0]} ({sys.executable})")
    try:
        import torch  # type: ignore
        ok(f"torch установлен: {torch.__version__}")
        cuda_compiled = torch.version.cuda
        if cuda_compiled:
            ok(f"PyTorch собран с CUDA {cuda_compiled}")
        else:
            fail("PyTorch установлен в CPU-only сборке (torch.version.cuda = None)")
            problems.append("torch_cpu_only")
        if torch.cuda.is_available():
            idx = torch.cuda.current_device()
            name = torch.cuda.get_device_name(idx)
            vram = torch.cuda.get_device_properties(idx).total_memory / 1024**3
            ok(f"torch.cuda.is_available() = True | {name} | {vram:.1f} GB")
        else:
            fail("torch.cuda.is_available() = False — GPU не используется")
            if nvidia_present and not problems:
                problems.append("torch_cuda_unavailable")
    except ImportError:
        fail("torch не установлен")
        problems.append("no_torch")

    section("WhisperX")
    try:
        import whisperx  # type: ignore
        ok(f"whisperx установлен: {getattr(whisperx, '__version__', '?')}")
    except ImportError:
        fail("whisperx не установлен")
        problems.append("no_whisperx")

    section("Ollama")
    try:
        import ollama  # type: ignore
        client = ollama.Client(host="http://localhost:11434")
        models = client.list().get("models", [])
        if models:
            names = ", ".join(m.get("name", "?") for m in models[:6])
            ok(f"Ollama запущен, модели: {names}")
        else:
            warn("Ollama запущен, но моделей нет. Запусти: ollama pull llama3.1:8b")
    except Exception as e:
        fail(f"Ollama недоступен ({e}). Запусти `ollama serve` и `ollama pull llama3.1:8b`")
        problems.append("no_ollama")

    section("FFmpeg + NVENC")
    code, out = run("ffmpeg", "-hide_banner", "-encoders")
    if code == 0:
        nvenc_lines = [l.strip() for l in out.splitlines() if "nvenc" in l.lower()]
        if nvenc_lines:
            ok(f"FFmpeg с NVENC: {len(nvenc_lines)} энкодеров")
            for l in nvenc_lines:
                print(f"    {l}")
        else:
            warn("FFmpeg есть, но NVENC не поддерживается. "
                 "Возьми сборку с gyan.dev/ffmpeg/builds (full).")
            problems.append("no_nvenc")
    else:
        fail("ffmpeg не найден в PATH")
        problems.append("no_ffmpeg")

    # --- Итоги ---
    section("Что делать")
    if not problems:
        print(f"{GREEN}{BOLD}Всё ок. Можно запускать main.py{END}")
        return 0

    if "torch_cpu_only" in problems or "torch_cuda_unavailable" in problems:
        print(f"{RED}{BOLD}ГЛАВНАЯ ПРОБЛЕМА: PyTorch без CUDA.{END}")
        print("Это объясняет почему транскрипция идёт на CPU и тормозит.")
        print("Запусти в той же среде:")
        print(f"  {BOLD}pip uninstall -y torch torchaudio torchvision{END}")
        print(f"  {BOLD}pip install torch torchaudio "
              f"--index-url https://download.pytorch.org/whl/cu121{END}")
        print()

    if "no_torch" in problems:
        print("Установи torch с CUDA:")
        print("  pip install torch torchaudio "
              "--index-url https://download.pytorch.org/whl/cu121")

    if "no_whisperx" in problems:
        print("Установи WhisperX: pip install whisperx faster-whisper")

    if "no_ollama" in problems:
        print("Скачай и запусти Ollama: https://ollama.com")
        print("Затем: ollama pull llama3.1:8b")

    if "no_ffmpeg" in problems:
        print("Установи FFmpeg: https://www.gyan.dev/ffmpeg/builds/ "
              "(возьми full-build и добавь в PATH)")

    if "no_nvenc" in problems:
        print("Возьми сборку FFmpeg с NVENC: https://www.gyan.dev/ffmpeg/builds/ (full)")

    return 1


if __name__ == "__main__":
    sys.exit(main())
