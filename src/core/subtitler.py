"""Генерация ASS-субтитров. Два режима: word_by_word и phrase."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..app_config import SubtitlesConfig, VideoConfig
from .transcriber import Segment, Word
from .utils import format_timestamp


def _ass_header(subs: SubtitlesConfig, video: VideoConfig) -> str:
    """ASS-заголовок с двумя стилями: Default (обычный) и Hi (подсветка слова)."""
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video.width}
PlayResY: {video.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{subs.font},{subs.font_size * 2},{subs.primary_color},&H000000FF,{subs.outline_color},&H64000000,-1,0,0,0,100,100,0,0,1,{subs.outline_thickness},{subs.shadow},2,60,60,{subs.bottom_margin},1
Style: Hi,{subs.font},{subs.font_size * 2},{subs.highlight_color},&H000000FF,{subs.outline_color},&H64000000,-1,0,0,0,100,100,0,0,1,{subs.outline_thickness},{subs.shadow},2,60,60,{subs.bottom_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _apply_case(text: str, uppercase: bool) -> str:
    return text.upper() if uppercase else text


def _split_words_into_phrases(
    words: list[Word], max_chars: int
) -> list[list[Word]]:
    """Группируем слова во фразы, не длиннее max_chars символов."""
    phrases: list[list[Word]] = []
    current: list[Word] = []
    current_len = 0
    for w in words:
        wl = len(w.text)
        if current and current_len + wl + 1 > max_chars:
            phrases.append(current)
            current = []
            current_len = 0
        current.append(w)
        current_len += wl + 1
    if current:
        phrases.append(current)
    return phrases


def _build_word_by_word_events(
    segments: list[Segment], subs: SubtitlesConfig, clip_offset: float
) -> list[str]:
    """Для каждой фразы создаём по одной строке Dialogue на слово,
    в которой текущее слово выделено стилем подсветки, остальные обычные.

    Главное: события НЕ ДОЛЖНЫ перекрываться по времени, иначе на экране
    будут видны две версии фразы одновременно. WhisperX иногда возвращает
    word boundaries с микро-наложениями (w[i].end > w[i+1].start) — мы их
    жёстко зажимаем."""
    events: list[str] = []

    # Собираем все слова из всех сегментов
    all_words: list[Word] = []
    for seg in segments:
        if seg.words:
            all_words.extend(seg.words)
        else:
            # Fallback: распределяем слова сегмента равномерно
            tokens = seg.text.split()
            if not tokens:
                continue
            dur_per = (seg.end - seg.start) / max(len(tokens), 1)
            for i, t in enumerate(tokens):
                all_words.append(Word(
                    start=seg.start + i * dur_per,
                    end=seg.start + (i + 1) * dur_per,
                    text=t,
                ))

    if not all_words:
        return events

    phrases = _split_words_into_phrases(all_words, subs.max_chars_per_line)

    # Плоский список (phrase_idx, word_idx_in_phrase, word) для прохода по времени
    flat: list[tuple[int, int, Word]] = []
    for pi, phrase in enumerate(phrases):
        for wi, w in enumerate(phrase):
            flat.append((pi, wi, w))

    # Считаем "следующую опорную точку" для каждой пары — это start следующего слова
    # (в той же фразе или в следующей). Если ничего нет — оставляем w.end.
    for i in range(len(flat)):
        pi, wi, w = flat[i]
        if i + 1 < len(flat):
            next_w = flat[i + 1][2]
            # Жёстко зажимаем конец к началу следующего слова —
            # это и убирает overlap внутри фразы, и убирает overlap на границе фраз.
            new_end = min(w.end, next_w.start)
            # Гарантируем что end > start (хоть немного)
            if new_end <= w.start:
                new_end = w.start + 0.05
            flat[i] = (pi, wi, Word(start=w.start, end=new_end, text=w.text))

    # Для каждого слова рисуем фразу с выделением текущего
    for pi, wi, w in flat:
        phrase = phrases[pi]
        start = max(0.0, w.start - clip_offset)
        end = max(start + 0.05, w.end - clip_offset)
        # Собираем строку с выделением wi-го слова
        parts: list[str] = []
        for j, ww in enumerate(phrase):
            text = _apply_case(ww.text, subs.uppercase)
            if j == wi:
                parts.append(
                    f"{{\\c{_color_to_ass_override(subs.highlight_color)}\\b1}}{text}{{\\r}}"
                )
            else:
                parts.append(text)
        line = " ".join(parts)
        events.append(
            f"Dialogue: 0,{format_timestamp(start, ass=True)},"
            f"{format_timestamp(end, ass=True)},Default,,0,0,0,,{line}"
        )
    return events


def _color_to_ass_override(color: str) -> str:
    """ASS PrimaryColour в стиле &H00BBGGRR -> для inline-override без &."""
    # Уже в формате &H00BBGGRR, для override нужен &HBBGGRR&
    c = color.strip()
    if c.startswith("&H"):
        c = c[2:]
    c = c.rstrip("&")
    # Снимаем альфу если она первая (8 hex chars) — берём последние 6
    if len(c) == 8:
        c = c[2:]
    return f"&H{c}&"


def _build_phrase_events(
    segments: list[Segment], subs: SubtitlesConfig, clip_offset: float
) -> list[str]:
    """Классические субтитры — целая фраза появляется и исчезает.

    Также защита от overlap: end текущего сегмента не должен заходить за start
    следующего."""
    if not segments:
        return []

    events: list[str] = []
    # Нормализованные интервалы (start, end) с обрезанием overlap
    bounds: list[tuple[float, float]] = []
    for i, seg in enumerate(segments):
        s = seg.start
        e = seg.end
        if i + 1 < len(segments):
            e = min(e, segments[i + 1].start)
        if e <= s:
            e = s + 0.05
        bounds.append((s, e))

    for (s, e), seg in zip(bounds, segments):
        text = _apply_case(seg.text.strip(), subs.uppercase)
        if not text:
            continue
        words = text.split()
        lines: list[str] = []
        current = ""
        for w in words:
            if current and len(current) + len(w) + 1 > subs.max_chars_per_line:
                lines.append(current)
                current = w
            else:
                current = f"{current} {w}".strip()
        if current:
            lines.append(current)
        line = "\\N".join(lines)

        start = max(0.0, s - clip_offset)
        end = max(start + 0.05, e - clip_offset)
        events.append(
            f"Dialogue: 0,{format_timestamp(start, ass=True)},"
            f"{format_timestamp(end, ass=True)},Default,,0,0,0,,{line}"
        )
    return events


def write_subtitles(
    out_path: Path,
    segments: list[Segment],
    subs: SubtitlesConfig,
    video: VideoConfig,
    clip_offset: float,
    clip_duration: float,
) -> Path:
    """Пишет ASS-файл для клипа. clip_offset — секунда начала клипа в исходнике,
    т.е. в ASS-файле время отсчитывается с 0 от начала клипа."""
    # Фильтруем сегменты, пересекающиеся с клипом
    in_clip: list[Segment] = []
    clip_end_abs = clip_offset + clip_duration
    for s in segments:
        if s.end < clip_offset or s.start > clip_end_abs:
            continue
        in_clip.append(s)

    if subs.style == "word_by_word":
        events = _build_word_by_word_events(in_clip, subs, clip_offset)
    else:
        events = _build_phrase_events(in_clip, subs, clip_offset)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_ass_header(subs, video))
        f.write("\n".join(events))
        f.write("\n")
    return out_path
