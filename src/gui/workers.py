"""QThread воркер для запуска пайплайна без блокировки UI."""

from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from ..app_config import AppConfig
from ..core.pipeline import VideoJob, VideoResult, process_batch


class PipelineWorker(QThread):
    # (video_index, job)
    video_started = pyqtSignal(int, object)
    # (stage, progress 0..1, message)
    stage_update = pyqtSignal(str, float, str)
    # VideoResult
    video_finished = pyqtSignal(object)
    # list[VideoResult]
    all_finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, jobs: list[VideoJob], cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.jobs = jobs
        self.cfg = cfg

    def run(self) -> None:
        try:
            results = process_batch(
                self.jobs, self.cfg,
                on_video=lambda i, j: self.video_started.emit(i, j),
                on_stage=lambda s, p, m: self.stage_update.emit(s, p, m),
                on_video_done=lambda r: self.video_finished.emit(r),
            )
            self.all_finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))
