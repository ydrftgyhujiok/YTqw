"""Главное окно приложения."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel, QFileDialog, QProgressBar, QTextEdit, QLineEdit,
    QMessageBox, QSplitter, QStatusBar, QInputDialog, QComboBox,
)

from ..app_config import load_config, save_config
from ..core.pipeline import VideoJob, VideoResult
from ..core.hardware import detect_hardware, cuda_misconfigured
from ..profile import (
    Profile, list_profiles, load_profile, save_profile,
    delete_profile, rename_profile, duplicate_profile,
)
from .profile_dialog import ProfileEditDialog
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

        # Загружаем список профилей; если ничего нет — создаётся Default
        self.profiles: list[Profile] = list_profiles()
        self.active_profile: Profile = self._resolve_active_profile()

        self._build_ui()
        self._build_menu()
        self._refresh_profile_combo()
        self._show_hardware_info()

    def _resolve_active_profile(self) -> Profile:
        target = (self.cfg.active_profile or "").strip()
        if target:
            for p in self.profiles:
                if p.name == target or p.slug == target:
                    return p
        return self.profiles[0]

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

        # Панель профиля канала
        prof_row = QHBoxLayout()
        prof_row.addWidget(QLabel("Профиль канала:"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(220)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        prof_row.addWidget(self.profile_combo, 1)

        new_prof_btn = QPushButton("+")
        new_prof_btn.setFixedWidth(28)
        new_prof_btn.setToolTip("Новый профиль")
        new_prof_btn.clicked.connect(self._new_profile)
        prof_row.addWidget(new_prof_btn)

        edit_prof_btn = QPushButton("✎")
        edit_prof_btn.setFixedWidth(28)
        edit_prof_btn.setToolTip("Редактировать профиль")
        edit_prof_btn.clicked.connect(self._edit_profile)
        prof_row.addWidget(edit_prof_btn)

        dup_prof_btn = QPushButton("⧉")
        dup_prof_btn.setFixedWidth(28)
        dup_prof_btn.setToolTip("Дублировать профиль")
        dup_prof_btn.clicked.connect(self._duplicate_profile)
        prof_row.addWidget(dup_prof_btn)

        del_prof_btn = QPushButton("🗑")
        del_prof_btn.setFixedWidth(28)
        del_prof_btn.setToolTip("Удалить профиль")
        del_prof_btn.clicked.connect(self._delete_profile)
        prof_row.addWidget(del_prof_btn)

        load_src_btn = QPushButton("⇣ Загрузить из папки канала")
        load_src_btn.setToolTip(
            "Добавить в очередь все видео из source_dir текущего профиля"
        )
        load_src_btn.clicked.connect(self._load_from_profile_source)
        prof_row.addWidget(load_src_btn)

        root.addLayout(prof_row)

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
        edit_prof = QAction("Редактировать профиль…", self)
        edit_prof.triggered.connect(self._edit_profile)
        tools.addAction(edit_prof)

        new_prof = QAction("Новый профиль…", self)
        new_prof.triggered.connect(self._new_profile)
        tools.addAction(new_prof)

        tools.addSeparator()
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
        ts = datetime.now().strftime("%H:%M:%S")
        # Для многострочных сообщений ставим префикс только перед первой строкой
        if msg.startswith("\n"):
            self.log.append(msg)
            self.log.append(f"[{ts}] ")
            return
        self.log.append(f"[{ts}] {msg}")

    # ---------- Профили ----------

    def _refresh_profile_combo(self) -> None:
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.profiles:
            self.profile_combo.addItem(p.name, p.slug)
        # Выставляем текущий
        for i, p in enumerate(self.profiles):
            if p.slug == self.active_profile.slug:
                self.profile_combo.setCurrentIndex(i)
                break
        self.profile_combo.blockSignals(False)

    def _on_profile_changed(self, idx: int) -> None:
        if idx < 0 or idx >= len(self.profiles):
            return
        self.active_profile = self.profiles[idx]
        self.cfg.active_profile = self.active_profile.name
        save_config(self.cfg)
        self._log(f"Активный профиль: {self.active_profile.name}")

    def _reload_profiles(self, prefer_slug: str | None = None) -> None:
        self.profiles = list_profiles()
        if prefer_slug:
            for p in self.profiles:
                if p.slug == prefer_slug:
                    self.active_profile = p
                    break
            else:
                self.active_profile = self.profiles[0]
        else:
            # Если активный исчез — берём первый
            self.active_profile = next(
                (p for p in self.profiles if p.slug == self.active_profile.slug),
                self.profiles[0],
            )
        self.cfg.active_profile = self.active_profile.name
        save_config(self.cfg)
        self._refresh_profile_combo()

    def _new_profile(self) -> None:
        name, ok = QInputDialog.getText(
            self, "Новый профиль", "Имя профиля:"
        )
        if not ok or not name.strip():
            return
        prof = Profile(name=name.strip())
        prof.output_dir = f"./output/{prof.slug}"
        save_profile(prof)
        self._log(f"Создан профиль: {prof.name}")
        self._reload_profiles(prefer_slug=prof.slug)
        self._edit_profile()

    def _edit_profile(self) -> None:
        if not self.active_profile:
            return
        old_slug = self.active_profile.slug
        dlg = ProfileEditDialog(self.active_profile, self)
        if dlg.exec():
            # Если имя сменилось — удалить старый файл
            if self.active_profile.slug != old_slug:
                old_path = Path.home() / ".ai_clip_gen" / "profiles" / f"{old_slug}.yaml"
                if old_path.exists():
                    try:
                        old_path.unlink()
                    except Exception:
                        pass
            self._log(f"Профиль сохранён: {self.active_profile.name}")
            self._reload_profiles(prefer_slug=self.active_profile.slug)

    def _duplicate_profile(self) -> None:
        if not self.active_profile:
            return
        name, ok = QInputDialog.getText(
            self, "Дубликат профиля",
            f"Имя для копии «{self.active_profile.name}»:",
            text=f"{self.active_profile.name} (копия)",
        )
        if not ok or not name.strip():
            return
        new = duplicate_profile(self.active_profile.name, name.strip())
        if new:
            self._log(f"Создан дубликат: {new.name}")
            self._reload_profiles(prefer_slug=new.slug)

    def _delete_profile(self) -> None:
        if not self.active_profile:
            return
        if len(self.profiles) <= 1:
            QMessageBox.information(
                self, "Нельзя удалить",
                "Это последний профиль — нужен хотя бы один."
            )
            return
        ans = QMessageBox.question(
            self, "Удалить профиль",
            f"Удалить профиль «{self.active_profile.name}»? Файлы вывода не трогаются.",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        delete_profile(self.active_profile.name)
        self._log(f"Удалён профиль: {self.active_profile.name}")
        self._reload_profiles()

    def _load_from_profile_source(self) -> None:
        src = (self.active_profile.source_dir or "").strip()
        if not src:
            QMessageBox.information(
                self, "Папка не задана",
                "В профиле не указана папка с исходными видео. "
                "Открой «✎» и заполни поле «Папка с исходными видео»."
            )
            return
        d = Path(src).expanduser()
        if not d.is_dir():
            QMessageBox.warning(
                self, "Папка не найдена",
                f"Папка не существует:\n{d}"
            )
            return
        before = self.queue_list.count()
        self._add_dir(d)
        added = self.queue_list.count() - before
        self._log(f"Загружено из «{self.active_profile.name}»: {added} видео из {d}")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, self)
        if dlg.exec():
            self.cfg = load_config()
            self._log("Настройки сохранены")
            self._show_hardware_info()

    def _open_output_folder(self) -> None:
        # Сначала смотрим папку текущего профиля, fallback на глобальную
        out = (self.active_profile.output_dir or self.cfg.paths.output_dir
               if hasattr(self, "active_profile") else self.cfg.paths.output_dir)
        p = Path(out).expanduser().resolve()
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

        self._log(f"Профиль: {self.active_profile.name}  →  {self.active_profile.output_dir}")
        self.worker = PipelineWorker(jobs, self.cfg, self.active_profile, self)
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
