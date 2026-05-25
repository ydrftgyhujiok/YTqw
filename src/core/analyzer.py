"""Поиск high-engagement моментов через локальный LLM (Ollama).

Алгоритм:
1. Делим транскрипт на чанки по N секунд (с перекрытием).
2. Просим LLM выдать JSON-список моментов со score, причиной, hook'ом и заголовком.
3. Сливаем, фильтруем по min_score, разрешаем пересечения, расширяем границы к ближайшим
   паузам в речи, чтобы клип не обрывался посередине фразы.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Callable, Optional

from ..app_config import AnalysisConfig, OllamaConfig
from .transcriber import Transcript, Segment


ProgressCb = Optional[Callable[[float, str], None]]


SYSTEM_PROMPT = """Ты — эксперт по созданию вирусных коротких видео для TikTok, YouTube Shorts и Reels.
Твоя задача — анализировать транскрипты длинных видео (стримов, подкастов, интервью, реакций,
геймплеев) и находить high-engagement моменты — фрагменты с максимальным потенциалом
удержания внимания и виральности.

Критерии оценки момента:
- Эмоциональные пики (смех, удивление, гнев, шок, восторг)
- Сильные фразы, hook-моменты, неожиданные заявления
- Конфликты, споры, шутки
- Интрига и ожидание развязки
- Контекст должен быть понятен зрителю БЕЗ просмотра остального видео
- Длительность: 20–75 секунд (идеально 30–60)
- Сильные первые секунды

Оценка score: 0–10, где:
  9–10 — потенциально вирусный, must-clip
  7–8  — отличный кандидат
  6    — хороший, но не выдающийся
  <6   — не публикуем

Отвечай СТРОГО валидным JSON без преамбулы, без markdown-кодблоков.
Формат ответа:
{
  "moments": [
    {
      "start": <число секунд>,
      "end": <число секунд>,
      "score": <0-10>,
      "title": "<короткий заголовок до 60 символов>",
      "hook": "<фраза hook'а в первые 2 сек, до 80 символов>",
      "reason": "<почему этот момент сильный, 1-2 предложения>",
      "tags": ["тег1", "тег2", "тег3"]
    }
  ]
}
"""


USER_PROMPT_TEMPLATE = """Транскрипт фрагмента видео (с тайм-кодами в секундах):

{transcript}

Ограничения:
- Длительность каждого момента: {min_sec}–{max_sec} секунд
- Только moments со score >= {min_score}
- start/end в секундах от начала ИСХОДНОГО видео (используй тайм-коды из транскрипта)
- Максимум {max_clips} моментов из этого фрагмента
- Если хороших моментов нет — верни {{"moments": []}}

Ответ:"""


@dataclass
class Moment:
    start: float
    end: float
    score: float
    title: str
    hook: str
    reason: str
    tags: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _format_segments(segments: list[Segment]) -> str:
    """Форматируем сегменты для LLM в виде [start–end] текст."""
    lines = []
    for s in segments:
        lines.append(f"[{s.start:.1f}–{s.end:.1f}] {s.text.strip()}")
    return "\n".join(lines)


def _split_into_chunks(segments: list[Segment], chunk_seconds: int) -> list[list[Segment]]:
    """Бьём транскрипт на чанки по чанк-секундам с границей на конце сегмента."""
    if not segments:
        return []
    chunks: list[list[Segment]] = []
    current: list[Segment] = []
    chunk_start = segments[0].start
    for seg in segments:
        if seg.end - chunk_start > chunk_seconds and current:
            chunks.append(current)
            current = []
            chunk_start = seg.start
        current.append(seg)
    if current:
        chunks.append(current)
    return chunks


def _extract_json(raw: str) -> dict:
    """LLM может вернуть с обёртками — пробуем вытащить первый валидный JSON-объект."""
    raw = raw.strip()
    # Снимаем ```json ... ``` если есть
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    # Берём от первой { до парной }
    start_idx = raw.find("{")
    if start_idx == -1:
        return {"moments": []}
    depth = 0
    end_idx = -1
    for i in range(start_idx, len(raw)):
        c = raw[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end_idx = i + 1
                break
    if end_idx == -1:
        return {"moments": []}
    try:
        return json.loads(raw[start_idx:end_idx])
    except json.JSONDecodeError:
        return {"moments": []}


def _snap_to_segment_boundaries(
    start: float, end: float, segments: list[Segment]
) -> tuple[float, float]:
    """Расширяем границы клипа до ближайшего начала/конца целого сегмента,
    чтобы фраза не обрывалась посередине."""
    new_start = start
    new_end = end
    for s in segments:
        if s.start <= start <= s.end:
            new_start = s.start
        if s.start <= end <= s.end:
            new_end = s.end
    return new_start, new_end


def _dedupe_and_filter(
    moments: list[Moment], min_score: float, max_clips: int, total_duration: float
) -> list[Moment]:
    """Сортируем по score, выкидываем пересекающиеся и слабые."""
    valid = [m for m in moments if m.score >= min_score and m.end > m.start and m.start >= 0]
    valid = [m for m in valid if m.end <= total_duration + 1.0]
    valid.sort(key=lambda m: m.score, reverse=True)

    selected: list[Moment] = []
    for m in valid:
        if any(_overlap(m, s) > 0.3 for s in selected):
            continue
        selected.append(m)
        if len(selected) >= max_clips:
            break
    selected.sort(key=lambda m: m.start)
    return selected


def _overlap(a: Moment, b: Moment) -> float:
    """Доля пересечения [0,1] относительно меньшего интервала."""
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    shortest = min(a.end - a.start, b.end - b.start)
    return inter / shortest if shortest > 0 else 0.0


def analyze_transcript(
    transcript: Transcript,
    analysis: AnalysisConfig,
    ollama_cfg: OllamaConfig,
    on_progress: ProgressCb = None,
) -> list[Moment]:
    """Главная точка входа: транскрипт -> список Moment'ов."""
    import ollama  # type: ignore

    if not transcript.segments:
        return []

    total_duration = transcript.segments[-1].end
    chunks = _split_into_chunks(transcript.segments, analysis.chunk_seconds)
    if on_progress:
        on_progress(0.0, f"Анализ {len(chunks)} фрагмента(ов) LLM…")

    client = ollama.Client(host=ollama_cfg.host)
    all_moments: list[Moment] = []

    for i, chunk in enumerate(chunks):
        if on_progress:
            on_progress(i / max(len(chunks), 1), f"LLM-анализ фрагмента {i+1}/{len(chunks)}")

        prompt = USER_PROMPT_TEMPLATE.format(
            transcript=_format_segments(chunk),
            min_sec=analysis.min_clip_seconds,
            max_sec=analysis.max_clip_seconds,
            min_score=analysis.min_score,
            max_clips=analysis.max_clips_per_video,
        )

        try:
            response = client.chat(
                model=ollama_cfg.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                options={
                    "temperature": ollama_cfg.temperature,
                    "num_predict": ollama_cfg.num_predict,
                    "num_ctx": ollama_cfg.num_ctx,
                },
                format="json",
            )
            raw = response.get("message", {}).get("content", "")
        except Exception as e:
            if on_progress:
                on_progress(i / max(len(chunks), 1), f"Ошибка LLM на фрагменте {i+1}: {e}")
            continue

        data = _extract_json(raw)
        for m in data.get("moments", []):
            try:
                start = float(m.get("start", 0))
                end = float(m.get("end", 0))
                # Подгоняем к границам сегментов чтобы не было обрывов фраз
                start, end = _snap_to_segment_boundaries(start, end, chunk)
                # Жёсткие лимиты по длительности
                length = end - start
                if length < analysis.min_clip_seconds:
                    end = start + analysis.min_clip_seconds
                if length > analysis.max_clip_seconds:
                    end = start + analysis.max_clip_seconds
                all_moments.append(Moment(
                    start=start,
                    end=end,
                    score=float(m.get("score", 0)),
                    title=str(m.get("title", "")).strip()[:80] or "Clip",
                    hook=str(m.get("hook", "")).strip()[:120],
                    reason=str(m.get("reason", "")).strip()[:300],
                    tags=[str(t).strip() for t in m.get("tags", []) if t][:8],
                ))
            except (TypeError, ValueError):
                continue

    final = _dedupe_and_filter(
        all_moments, analysis.min_score, analysis.max_clips_per_video, total_duration
    )
    if on_progress:
        on_progress(1.0, f"Найдено {len(final)} моментов")
    return final
