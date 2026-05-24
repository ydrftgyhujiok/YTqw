"""Оркестратор пайплайна: source -> download -> transcribe -> analyze -> render."""

from __future__ import annotations

import dataclasses
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..app_config import AppConfig
from . import downloader, transcriber, analyzer, subtitler, clipper
from .analyzer import Moment
from .hardware import HardwareProfile, detect_hardware
from .utils import sanitize_filename, write_json, ffprobe_duration


# (stage_name, stage_progress 0..1, message)
StageCb = Optional[Callable[[str, float, str], None]]


@dataclass
class VideoJob:
    source: str           # путь или URL
    label: str            # отображаемое имя


@dataclass
class ClipResult:
    moment: Moment
    out_path: Path
    error: Optional[str] = None


@dataclass
class VideoResult:
    job: VideoJob
    source_path: Optional[Path]
    moments: list[Moment]
    clips: list[ClipResult]
    error: Optional[str] = None


def _emit(cb: StageCb, stage: str, progress: float, message: str) -> None:
    if cb:
        try:
            cb(stage, progress, message)
        except Exception:
            pass


def process_video(
    job: VideoJob,
    cfg: AppConfig,
    hw: HardwareProfile,
    on_stage: StageCb = None,
) -> VideoResult:
    """Обрабатываем одно видео: скачивание -> транскрипт -> анализ -> рендер всех клипов."""
    work = Path(cfg.paths.work_dir).expanduser().resolve()
    out_root = Path(cfg.paths.output_dir).expanduser().resolve()
    work.mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)

    try:
        # 1. Источник
        _emit(on_stage, "download", 0.0, f"Источник: {job.label}")
        source_path = downloader.download_video(
            job.source, work,
            on_progress=lambda p, m: _emit(on_stage, "download", p, m),
        )

        # 2. Транскрипция
        _emit(on_stage, "transcribe", 0.0, "Запускаем WhisperX")
        transcript = transcriber.transcribe(
            source_path, cfg.whisper, hw,
            on_progress=lambda p, m: _emit(on_stage, "transcribe", p, m),
        )

        # Кешируем транскрипт рядом с источником
        transcript_path = work / f"{source_path.stem}.transcript.json"
        write_json(transcript_path, {
            "language": transcript.language,
            "segments": [
                {
                    "start": s.start, "end": s.end, "text": s.text,
                    "words": [dataclasses.asdict(w) for w in s.words],
                }
                for s in transcript.segments
            ],
        })

        # 3. Анализ моментов
        _emit(on_stage, "analyze", 0.0, "LLM ищет high-engagement моменты")
        moments = analyzer.analyze_transcript(
            transcript, cfg.analysis, cfg.ollama,
            on_progress=lambda p, m: _emit(on_stage, "analyze", p, m),
        )

        # Папка под клипы этого видео
        video_out = out_root / sanitize_filename(source_path.stem)
        video_out.mkdir(parents=True, exist_ok=True)
        write_json(video_out / "moments.json", [m.to_dict() for m in moments])

        if not moments:
            _emit(on_stage, "render", 1.0, "Моментов не найдено — пропускаем рендер")
            return VideoResult(job=job, source_path=source_path, moments=[], clips=[])

        # 4. Готовим джобы клипов: для каждого момента — ASS и ClipJob
        try:
            total_duration = ffprobe_duration(cfg.paths.ffprobe, source_path)
        except Exception:
            total_duration = transcript.segments[-1].end if transcript.segments else 0

        clip_jobs: list[clipper.ClipJob] = []
        for i, m in enumerate(moments):
            start = max(0.0, m.start)
            end = min(total_duration, m.end)
            duration = max(1.0, end - start)
            safe_title = sanitize_filename(m.title or f"clip_{i+1:02d}", max_len=80)
            out_path = video_out / f"{i+1:02d}_{safe_title}.mp4"
            subs_path = video_out / f"{i+1:02d}_{safe_title}.ass"
            subtitler.write_subtitles(
                subs_path, transcript.segments, cfg.subtitles, cfg.video,
                clip_offset=start, clip_duration=duration,
            )
            clip_jobs.append(clipper.ClipJob(
                source=source_path,
                start=start,
                duration=duration,
                subs_path=subs_path,
                out_path=out_path,
                title=m.title,
            ))

        # 5. Параллельный рендер (NVENC ограничен 3-5 сессиями)
        _emit(on_stage, "render", 0.0, f"Рендер {len(clip_jobs)} клипов "
              f"(parallel={cfg.processing.parallel_clips})")
        results: list[ClipResult] = []
        completed = 0
        total = len(clip_jobs)

        with ThreadPoolExecutor(max_workers=max(1, cfg.processing.parallel_clips)) as ex:
            futures = {
                ex.submit(
                    clipper.render_clip, cj, cfg.video, cfg.subtitles, cfg.paths, hw, None,
                ): (cj, m)
                for cj, m in zip(clip_jobs, moments)
            }
            for fut in as_completed(futures):
                cj, m = futures[fut]
                try:
                    out = fut.result()
                    results.append(ClipResult(moment=m, out_path=out))
                except Exception as e:
                    results.append(ClipResult(moment=m, out_path=cj.out_path, error=str(e)))
                completed += 1
                _emit(on_stage, "render", completed / max(total, 1),
                      f"Рендер {completed}/{total}: {cj.out_path.name}")

        results.sort(key=lambda r: r.moment.start)
        return VideoResult(job=job, source_path=source_path, moments=moments, clips=results)

    except Exception as e:
        return VideoResult(
            job=job, source_path=None, moments=[], clips=[],
            error=f"{e}\n{traceback.format_exc()}",
        )


def process_batch(
    jobs: list[VideoJob],
    cfg: AppConfig,
    on_video: Callable[[int, VideoJob], None] | None = None,
    on_stage: StageCb = None,
    on_video_done: Callable[[VideoResult], None] | None = None,
) -> list[VideoResult]:
    """Обрабатываем batch видео. WhisperX занимает GPU — обычно parallel_videos=1."""
    hw = detect_hardware(cfg.paths.ffmpeg)
    results: list[VideoResult] = []
    for i, job in enumerate(jobs):
        if on_video:
            on_video(i, job)
        t0 = time.time()
        res = process_video(job, cfg, hw, on_stage=on_stage)
        res_elapsed = time.time() - t0
        if on_video_done:
            on_video_done(res)
        results.append(res)
        _emit(on_stage, "video_done", 1.0,
              f"Видео {job.label}: {len(res.clips)} клипов за {res_elapsed:.0f}с")
    return results
