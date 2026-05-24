"""Word-level транскрипция через WhisperX (faster-whisper + alignment)."""

from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..app_config import WhisperConfig
from .hardware import HardwareProfile, resolve_whisper_device, resolve_compute_type


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

    if on_progress:
        on_progress(0.05, f"Загрузка модели Whisper {cfg.model} ({device}/{compute_type})")

    language = None if cfg.language == "auto" else cfg.language

    model = whisperx.load_model(
        cfg.model,
        device=device,
        compute_type=compute_type,
        language=language,
    )

    if on_progress:
        on_progress(0.15, "Декодирование аудио…")
    audio = whisperx.load_audio(str(audio_or_video))

    if on_progress:
        on_progress(0.25, "Транскрипция…")
    result = model.transcribe(audio, batch_size=cfg.batch_size, language=language)
    detected_lang = result.get("language", "en")

    # Чистим модель чтобы влез alignment
    del model
    gc.collect()
    try:
        import torch  # type: ignore
        if device == "cuda":
            torch.cuda.empty_cache()
    except Exception:
        pass

    if on_progress:
        on_progress(0.6, f"Word-level alignment ({detected_lang})…")
    try:
        align_model, metadata = whisperx.load_align_model(language_code=detected_lang, device=device)
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

    if on_progress:
        on_progress(1.0, f"Транскрипция готова: {len(segments)} сегментов")

    return Transcript(language=detected_lang, segments=segments)
