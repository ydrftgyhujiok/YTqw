"""Главное окно приложения."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QProgressBar, QTextEdit, QLineEdit,
    QMessageBox, QSplitter, QStatusBar, QInputDialog,
)

from ..app_config import load_config, save_config
from ..core.pipeline import VideoJob, VideoResult
from ..core.hardware import detect_hardware, cuda_misconfigured
from .settings_dialog import SettingsDialog
from .workers import PipelineWorker


VIDEO_EXTS = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv", ".m4v", ".ts"}


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("AI Short Video Clip Generator")
        self.resize(1100, 720)
        self.setAcceptDrops(True)

        self.cfg = load_config()
        self.worker: PipelineWorker | None = None
        self.results: list[VideoResult] = []

        self._build_ui()
        self._build_menu()
        self._show_hardware_info()

    # ---------- UI ----------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout(central)

        # Плашка-предупреждение о CUDA (показывается только если проблема)
        self.cuda_warning = QLabel("")
        self.cuda_warning.setWordWrap(True)
        self.cuda_warning.setStyleSheet(
            "QLabel { background: #5a1a1a; color: #ffe; "
            "padding: 10px; border: 2px solid #a33; border-radius: 4px; "
            "font-family: 'Consolas','Courier New',monospace; }"
        )
        self.cuda_warning.setVisible(False)
        self.cuda_warning.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.cuda_warning)

        # Верхняя панель — добавление источников
        add_row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Вставь YouTube/Twitch URL и нажми «Добавить»…")
        self.url_input.returnPressed.connect(self._add_url)
        add_row.addWidget(self.url_input, 1)

        add_url_btn = QPushButton("Добавить URL")
        add_url_btn.clicked.connect(self._add_url)
        add_row.addWidget(add_url_btn)

        add_files_btn = QPushButton("Добавить файлы…")
        add_files_btn.clicked.connect(self._add_files)
        add_row.addWidget(add_files_btn)

        add_folder_btn = QPushButton("Добавить папку…")
        add_folder_btn.clicked.connect(self._add_folder)
        add_row.addWidget(add_folder_btn)

        root.addLayout(add_row)

        # Сплиттер: слева очередь, справа лог
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Левая колонка — очередь
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(QLabel("Очередь видео (drag & drop поддерживается):"))
        self.queue_list = QListWidget()
        self.queue_list.setAlternatingRowColors(True)
        ll.addWidget(self.queue_list, 1)

        queue_btns = QHBoxLayout()
        remove_btn = QPushButton("Удалить выбранное")
        remove_btn.clicked.connect(self._remove_selected)
        clear_btn = QPushButton("Очистить очередь")
        clear_btn.clicked.connect(lambda: self.queue_list.clear())
        queue_btns.addWidget(remove_btn)
        queue_btns.addWidget(clear_btn)
        queue_btns.addStretch(1)
        ll.addLayout(queue_btns)
        splitter.addWidget(left)

        # Правая колонка — прогресс + лог + результаты
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)

        self.current_label = QLabel("Готов к запуску")
        self.current_label.setStyleSheet("font-weight: bold;")
        rl.addWidget(self.current_label)

        self.stage_label = QLabel("")
        rl.addWidget(self.stage_label)

        self.stage_bar = QProgressBar()
        self.stage_bar.setRange(0, 1000)
        rl.addWidget(self.stage_bar)

        self.total_label = QLabel("Прогресс batch'а:")
        rl.addWidget(self.total_label)

        self.total_bar = QProgressBar()
        self.total_bar.setRange(0, 1000)
        rl.addWidget(self.total_bar)

        rl.addWidget(QLabel("Лог:"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        rl.addWidget(self.log, 1)

        results_btns = QHBoxLayout()
        open_out_btn = QPushButton("Открыть папку вывода")
        open_out_btn.clicked.connect(self._open_output_folder)
        results_btns.addWidget(open_out_btn)
        results_btns.addStretch(1)
        rl.addLayout(results_btns)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)

        # Нижняя панель — управление
        ctrl = QHBoxLayout()
        self.start_btn = QPushButton("▶  Запустить обработку")
        self.start_btn.setStyleSheet("font-size: 14px; padding: 8px 16px;")
        self.start_btn.clicked.connect(self._start)
        ctrl.addWidget(self.start_btn)

        self.stop_btn = QPushButton("⏹  Остановить")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop)
        ctrl.addWidget(self.stop_btn)

        ctrl.addStretch(1)

        settings_btn = QPushButton("⚙  Настройки")
        settings_btn.clicked.connect(self._open_settings)
        ctrl.addWidget(settings_btn)

        root.addLayout(ctrl)

        self.setStatusBar(QStatusBar())

    def _build_menu(self) -> None:
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&Файл")

        add_files = QAction("Добавить файлы…", self)
        add_files.triggered.connect(self._add_files)
        file_menu.addAction(add_files)

        add_url = QAction("Добавить URL…", self)
        add_url.triggered.connect(self._add_url_dialog)
        file_menu.addAction(add_url)

        file_menu.addSeparator()
        quit_act = QAction("Выход", self)
        quit_act.triggered.connect(self.close)
        file_menu.addAction(quit_act)

        tools = menubar.addMenu("&Инструменты")
        settings = QAction("Настройки…", self)
        settings.triggered.connect(self._open_settings)
        tools.addAction(settings)

        open_out = QAction("Открыть папку вывода", self)
        open_out.triggered.connect(self._open_output_folder)
        tools.addAction(open_out)

        help_menu = menubar.addMenu("&Справка")
        about = QAction("О программе", self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)

    # ---------- Drag & drop ----------

    def dragEnterEvent(self, e: QDragEnterEvent) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent) -> None:
        for url in e.mimeData().urls():
            if url.isLocalFile():
                p = Path(url.toLocalFile())
                if p.is_dir():
                    self._add_dir(p)
                elif p.suffix.lower() in VIDEO_EXTS:
                    self._add_job(str(p), p.name)
            else:
                self._add_job(url.toString(), url.toString())

    # ---------- Добавление источников ----------

    def _add_job(self, source: str, label: str) -> None:
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, source)
        item.setToolTip(source)
        self.queue_list.addItem(item)

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Выбор видеофайлов", "",
            "Видео (*.mp4 *.mkv *.mov *.avi *.webm *.flv *.m4v *.ts);;Все файлы (*)"
        )
        for f in files:
            p = Path(f)
            self._add_job(str(p), p.name)

    def _add_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Выбор папки с видео")
        if d:
            self._add_dir(Path(d))

    def _add_dir(self, d: Path) -> None:
        for p in sorted(d.iterdir()):
            if p.is_file() and p.suffix.lower() in VIDEO_EXTS:
                self._add_job(str(p), p.name)

    def _add_url(self) -> None:
        url = self.url_input.text().strip()
        if not url:
            return
        self._add_job(url, url)
        self.url_input.clear()

    def _add_url_dialog(self) -> None:
        url, ok = QInputDialog.getText(self, "Добавить URL", "Ссылка на видео:")
        if ok and url.strip():
            self._add_job(url.strip(), url.strip())

    def _remove_selected(self) -> None:
        for item in self.queue_list.selectedItems():
            self.queue_list.takeItem(self.queue_list.row(item))

    # ---------- Прочее ----------

    def _show_hardware_info(self) -> None:
        try:
            hw = detect_hardware(self.cfg.paths.ffmpeg)
        except Exception as e:
            self._log(f"Не удалось определить железо: {e}")
            return
        gpu = f"{hw.gpu_name} ({hw.vram_gb} GB)" if hw.cuda_available else "—"
        nvenc = "✓" if hw.nvenc_available else "✗"
        msg = (
            f"GPU CUDA: {gpu} | NVENC: {nvenc} ({', '.join(hw.nvenc_encoders) or 'нет'}) | "
            f"CPU threads: {hw.cpu_threads} | "
            f"torch {hw.torch_version} cuda={hw.torch_cuda_version or '—'}"
        )
        self.statusBar().showMessage(msg)
        self._log(msg)

        if cuda_misconfigured(hw):
            # Большая красная плашка — это самая частая ошибка установки
            self.cuda_warning.setText(
                f"⚠ В системе есть NVIDIA {hw.gpu_name} (драйвер {hw.nvidia_driver}), "
                f"но PyTorch установлен БЕЗ CUDA — транскрипция пойдёт на CPU и будет "
                f"в 20–50 раз медленнее.\n"
                f"Исправь так:\n"
                f"    pip uninstall -y torch torchaudio torchvision\n"
                f"    pip install torch torchaudio --index-url "
                f"https://download.pytorch.org/whl/cu121"
            )
            self.cuda_warning.setVisible(True)
            QMessageBox.warning(
                self, "PyTorch без CUDA",
                "У тебя установлен PyTorch без поддержки CUDA. "
                "Транскрипция пойдёт на CPU и будет очень медленной.\n\n"
                "Подробности и команда для исправления — в красной плашке в окне."
            )
        else:
            self.cuda_warning.setVisible(False)

    def _log(self, msg: str) -> None:
        self.log.append(msg)

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self.cfg = load_config()
            self._log("Настройки сохранены")
            self._show_hardware_info()

    def _open_output_folder(self) -> None:
        p = Path(self.cfg.paths.output_dir).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _show_about(self) -> None:
        QMessageBox.about(
            self, "О программе",
            "AI Short Video Clip Generator v0.1\n\n"
            "Локальный AI-конвейер для генерации коротких клипов 9:16.\n"
            "Whisper(X) + Ollama + FFmpeg/NVENC + PyQt6.\n\n"
            "Полностью бесплатно, без облачных API."
        )

    # ---------- Запуск ----------

    def _collect_jobs(self) -> list[VideoJob]:
        jobs: list[VideoJob] = []
        for i in range(self.queue_list.count()):
            item = self.queue_list.item(i)
            source = item.data(Qt.ItemDataRole.UserRole)
            jobs.append(VideoJob(source=source, label=item.text()))
        return jobs

    def _start(self) -> None:
        jobs = self._collect_jobs()
        if not jobs:
            QMessageBox.information(self, "Очередь пуста",
                                    "Добавь хотя бы одно видео или URL.")
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.log.clear()
        self.results = []
        self.total_bar.setValue(0)
        self.stage_bar.setValue(0)
        self._log(f"Запуск batch: {len(jobs)} видео")

        self.worker = PipelineWorker(jobs, self.cfg, self)
        self._jobs_total = len(jobs)
        self._jobs_done = 0
        self.worker.video_started.connect(self._on_video_started)
        self.worker.stage_update.connect(self._on_stage_update)
        self.worker.video_finished.connect(self._on_video_finished)
        self.worker.all_finished.connect(self._on_all_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _stop(self) -> None:
        if self.worker and self.worker.isRunning():
            self._log("Запрошена остановка. Текущий клип будет завершён…")
            # QThread мягко не останавливается, поэтому terminate.
            # У FFmpeg-процессов будут оборваны connection'ы.
            self.worker.terminate()
            self.worker.wait(3000)
            self._on_all_finished([])

    def _on_video_started(self, idx: int, job: VideoJob) -> None:
        self.current_label.setText(f"Видео {idx+1}/{self._jobs_total}: {job.label}")
        self.stage_bar.setValue(0)
        self._log(f"\n=== {job.label} ===")

    def _on_stage_update(self, stage: str, progress: float, message: str) -> None:
        self.stage_label.setText(f"[{stage}] {message}")
        self.stage_bar.setValue(int(progress * 1000))
        if message:
            self._log(f"  [{stage}] {message}")

    def _on_video_finished(self, result: VideoResult) -> None:
        self.results.append(result)
        self._jobs_done += 1
        self.total_bar.setValue(int(self._jobs_done / max(self._jobs_total, 1) * 1000))
        if result.error:
            self._log(f"  ❌ Ошибка: {result.error.splitlines()[0]}")
        else:
            ok = sum(1 for c in result.clips if not c.error)
            self._log(f"  ✓ Готово клипов: {ok}/{len(result.clips)}")

    def _on_all_finished(self, results: list) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.current_label.setText("Готово")
        self.stage_label.setText("")
        self._log(f"\nBatch завершён. Всего видео: {len(self.results)}")

    def _on_error(self, msg: str) -> None:
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._log(f"❌ Критическая ошибка: {msg}")
        QMessageBox.critical(self, "Ошибка", msg)
