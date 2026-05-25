"""Word-level транскрипция через WhisperX (faster-whisper + alignment)."""

from __future__ import annotations

import gc
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..app_config import WhisperConfig
from .hardware import (
    HardwareProfile, resolve_whisper_device, resolve_compute_type, cuda_misconfigured,
)


ProgressCb = Optional[Callable[[float, str], None]]


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: list[Word]


@dataclass
class Transcript:
    language: str
    segments: list[Segment]

    @property
    def full_text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)


def transcribe(
    audio_or_video: Path,
    cfg: WhisperConfig,
    hw: HardwareProfile,
    on_progress: ProgressCb = None,
) -> Transcript:
    """Запускает WhisperX и возвращает word-level транскрипт.

    На RTX 4070 Ti 12 GB безопасен batch_size=16 для large-v3 + alignment.
    На CPU автоматически переключается на int8.
    """
    import whisperx  # type: ignore

    device = resolve_whisper_device(cfg.device, hw)
    compute_type = resolve_compute_type(cfg.compute_type, device)

    # Громкая диагностика — пользователь должен видеть ИМЕННО где крутится модель.
    # Если устройство CPU, а железо при этом NVIDIA — это всегда CPU-only torch.
    if on_progress:
        on_progress(
            0.0,
            f"Whisper: device={device}, compute_type={compute_type}, "
            f"torch={hw.torch_version}, torch.cuda={hw.torch_cuda_version or 'НЕТ'}, "
            f"GPU={hw.gpu_name or 'нет'}",
        )

    if device == "cpu" and cuda_misconfigured(hw):
        warn = (
            "⚠ ВНИМАНИЕ: установлен PyTorch БЕЗ CUDA, но в системе есть NVIDIA "
            f"({hw.gpu_name}, драйвер {hw.nvidia_driver}). "
            "Транскрипция пойдёт на CPU и будет в 20–50 раз медленнее.\n"
            "ИСПРАВЛЕНИЕ:\n"
            "  pip uninstall -y torch torchaudio torchvision\n"
            "  pip install torch torchaudio --index-url "
            "https://download.pytorch.org/whl/cu121"
        )
        if on_progress:
            on_progress(0.0, warn)

    language = None if cfg.language == "auto" else cfg.language

    # Дополнительные ускорения на CPU: используем все потоки
    if device == "cpu":
        try:
            import torch  # type: ignore
            torch.set_num_threads(hw.cpu_threads)
        except Exception:
            pass
        # ctranslate2 тоже читает эту переменную
        os.environ.setdefault("OMP_NUM_THREADS", str(hw.cpu_threads))

    t0 = time.time()
    if on_progress:
        on_progress(0.05, f"Загрузка модели Whisper {cfg.model}…")

    # VAD-фильтр сильно ускоряет: пропускает тишину и не-речь
    asr_options = {
        "without_timestamps": False,
    }
    vad_options = {"vad_onset": 0.500, "vad_offset": 0.363}

    try:
        model = whisperx.load_model(
            cfg.model,
            device=device,
            compute_type=compute_type,
            language=language,
            asr_options=asr_options,
            vad_options=vad_options,
            threads=hw.cpu_threads if device == "cpu" else 0,
        )
    except TypeError:
        # Старые версии whisperx без threads= / vad_options=
        model = whisperx.load_model(
            cfg.model, device=device, compute_type=compute_type, language=language,
        )

    if on_progress:
        on_progress(0.15, "Декодирование аудио…")
    audio = whisperx.load_audio(str(audio_or_video))
    audio_seconds = len(audio) / 16000.0
    if on_progress:
        on_progress(0.2, f"Аудио: {audio_seconds:.0f} с")

    if on_progress:
        on_progress(0.25, f"Транскрипция (batch_size={cfg.batch_size})…")
    t_trans = time.time()
    result = model.transcribe(audio, batch_size=cfg.batch_size, language=language)
    trans_elapsed = time.time() - t_trans
    rt_factor = audio_seconds / trans_elapsed if trans_elapsed > 0 else 0
    detected_lang = result.get("language", "en")
    if on_progress:
        on_progress(
            0.55,
            f"Транскрипция: {trans_elapsed:.1f}с (×{rt_factor:.1f} от реального времени), "
            f"язык={detected_lang}",
        )

    # Чистим модель чтобы влез alignment
    del model
    gc.collect()
    try:
        import torch  # type: ignore
        if device == "cuda":
            torch.cuda.empty_cache()
    except Exception:
        pass

    if getattr(cfg, "skip_alignment", False):
        if on_progress:
            on_progress(0.9, "Alignment пропущен (skip_alignment=True)")
    else:
        if on_progress:
            on_progress(0.6, f"Word-level alignment ({detected_lang})…")
        t_align = time.time()
        try:
            align_model, metadata = whisperx.load_align_model(
                language_code=detected_lang, device=device,
            )
            result = whisperx.align(
                result["segments"], align_model, metadata, audio, device,
                return_char_alignments=False,
            )
            del align_model
            gc.collect()
            try:
                import torch  # type: ignore
                if device == "cuda":
                    torch.cuda.empty_cache()
            except Exception:
                pass
            if on_progress:
                on_progress(0.9, f"Alignment: {time.time() - t_align:.1f}с")
        except Exception as e:
            if on_progress:
                on_progress(0.7, f"Alignment недоступен ({e}) — используем segment-level")

    segments: list[Segment] = []
    for seg in result.get("segments", []):
        words = []
        for w in seg.get("words", []) or []:
            try:
                words.append(Word(
                    start=float(w.get("start", seg["start"])),
                    end=float(w.get("end", seg["end"])),
                    text=str(w.get("word", w.get("text", ""))).strip(),
                ))
            except (TypeError, ValueError, KeyError):
                continue
        segments.append(Segment(
            start=float(seg["start"]),
            end=float(seg["end"]),
            text=str(seg.get("text", "")).strip(),
            words=words,
        ))

    total_elapsed = time.time() - t0
    if on_progress:
        on_progress(
            1.0,
            f"Транскрипция готова: {len(segments)} сегментов, "
            f"всего {total_elapsed:.1f}с",
        )

    return Transcript(language=detected_lang, segments=segments)
