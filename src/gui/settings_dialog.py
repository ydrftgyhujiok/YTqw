"""Диалог глобальных настроек приложения: пути, Whisper, Ollama, обработка.

Per-канал настройки (видео/субтитры/анализ/папки) живут в ProfileEditDialog
и хранятся отдельно — здесь только то, что общее для всех каналов."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QSpinBox,
    QDoubleSpinBox, QComboBox, QPushButton, QTabWidget, QWidget, QCheckBox,
    QFileDialog, QLabel,
)

from ..app_config import AppConfig, save_config


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
WHISPER_DEVICES = ["auto", "cuda", "cpu"]
WHISPER_COMPUTE = ["float16", "int8", "float32"]
OLLAMA_SUGGESTIONS = [
    "llama3.1:8b", "llama3.1:70b",
    "qwen2.5:7b", "qwen2.5:14b", "qwen2.5:32b",
    "mistral:7b", "mixtral:8x7b",
    "gemma2:9b", "gemma2:27b",
]


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.cfg = cfg
        self.setWindowTitle("Глобальные настройки")
        self.resize(640, 520)
        self._build()
        self._populate()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            "Здесь только глобальные настройки. "
            "Настройки видео, субтитров и анализа — в профиле канала."
        )
        info.setStyleSheet("color: #888;")
        info.setWordWrap(True)
        layout.addWidget(info)

        tabs = QTabWidget()

        # --- Пути ---
        paths_tab = QWidget()
        pf = QFormLayout(paths_tab)
        self.output_dir = QLineEdit()
        self.work_dir = QLineEdit()
        self.ffmpeg = QLineEdit()
        self.ffprobe = QLineEdit()
        for line, label, picker in [
            (self.output_dir, "Папка вывода (fallback)", self._pick_dir),
            (self.work_dir, "Рабочая папка (кеш)", self._pick_dir),
            (self.ffmpeg, "Путь к ffmpeg", self._pick_file),
            (self.ffprobe, "Путь к ffprobe", self._pick_file),
        ]:
            row = QHBoxLayout()
            row.addWidget(line, 1)
            btn = QPushButton("…")
            btn.setFixedWidth(32)
            btn.clicked.connect(lambda _=False, le=line, p=picker: p(le))
            row.addWidget(btn)
            wrapper = QWidget()
            wrapper.setLayout(row)
            pf.addRow(label, wrapper)
        pf.addRow(QLabel(
            "Папка вывода в профиле канала перебивает глобальную."
        ))
        tabs.addTab(paths_tab, "Пути")

        # --- Whisper ---
        wt = QWidget()
        wf = QFormLayout(wt)
        self.whisper_model = QComboBox()
        self.whisper_model.addItems(WHISPER_MODELS)
        self.whisper_device = QComboBox()
        self.whisper_device.addItems(WHISPER_DEVICES)
        self.whisper_compute = QComboBox()
        self.whisper_compute.addItems(WHISPER_COMPUTE)
        self.whisper_batch = QSpinBox()
        self.whisper_batch.setRange(1, 64)
        self.whisper_lang = QLineEdit()
        self.whisper_skip_align = QCheckBox(
            "Пропустить word-level alignment (×2 быстрее, "
            "субтитры не будут word-by-word)"
        )
        wf.addRow("Модель Whisper", self.whisper_model)
        wf.addRow("Устройство", self.whisper_device)
        wf.addRow("Compute type", self.whisper_compute)
        wf.addRow("Batch size", self.whisper_batch)
        wf.addRow("Язык (auto = автодетект)", self.whisper_lang)
        wf.addRow("", self.whisper_skip_align)
        tabs.addTab(wt, "Whisper")

        # --- Ollama ---
        ot = QWidget()
        of = QFormLayout(ot)
        self.ollama_host = QLineEdit()
        self.ollama_model = QComboBox()
        self.ollama_model.setEditable(True)
        self.ollama_model.addItems(OLLAMA_SUGGESTIONS)
        self.ollama_temp = QDoubleSpinBox()
        self.ollama_temp.setRange(0.0, 2.0)
        self.ollama_temp.setSingleStep(0.05)
        self.ollama_predict = QSpinBox()
        self.ollama_predict.setRange(256, 32768)
        self.ollama_ctx = QSpinBox()
        self.ollama_ctx.setRange(1024, 131072)
        of.addRow("Host Ollama", self.ollama_host)
        of.addRow("Модель", self.ollama_model)
        of.addRow("Temperature", self.ollama_temp)
        of.addRow("num_predict", self.ollama_predict)
        of.addRow("num_ctx", self.ollama_ctx)
        of.addRow(QLabel("Список моделей можно расширять любой строкой (нужно `ollama pull`)"))
        tabs.addTab(ot, "Ollama")

        # --- Обработка ---
        pt = QWidget()
        pf2 = QFormLayout(pt)
        self.p_parallel_clips = QSpinBox(); self.p_parallel_clips.setRange(1, 16)
        self.p_parallel_vids = QSpinBox(); self.p_parallel_vids.setRange(1, 4)
        pf2.addRow("Параллельных клипов (NVENC сессии)", self.p_parallel_clips)
        pf2.addRow("Параллельных видео", self.p_parallel_vids)
        tabs.addTab(pt, "Обработка")

        layout.addWidget(tabs)

        # Кнопки
        btns = QHBoxLayout()
        btns.addStretch(1)
        save_btn = QPushButton("Сохранить")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btns.addWidget(save_btn)
        btns.addWidget(cancel_btn)
        layout.addLayout(btns)

    def _pick_dir(self, line: QLineEdit) -> None:
        d = QFileDialog.getExistingDirectory(self, "Выбор папки", line.text() or "")
        if d:
            line.setText(d)

    def _pick_file(self, line: QLineEdit) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Выбор файла", line.text() or "")
        if f:
            line.setText(f)

    def _populate(self) -> None:
        c = self.cfg
        self.output_dir.setText(c.paths.output_dir)
        self.work_dir.setText(c.paths.work_dir)
        self.ffmpeg.setText(c.paths.ffmpeg)
        self.ffprobe.setText(c.paths.ffprobe)

        self.whisper_model.setCurrentText(c.whisper.model)
        self.whisper_device.setCurrentText(c.whisper.device)
        self.whisper_compute.setCurrentText(c.whisper.compute_type)
        self.whisper_batch.setValue(c.whisper.batch_size)
        self.whisper_lang.setText(c.whisper.language)
        self.whisper_skip_align.setChecked(c.whisper.skip_alignment)

        self.ollama_host.setText(c.ollama.host)
        self.ollama_model.setCurrentText(c.ollama.model)
        self.ollama_temp.setValue(c.ollama.temperature)
        self.ollama_predict.setValue(c.ollama.num_predict)
        self.ollama_ctx.setValue(c.ollama.num_ctx)

        self.p_parallel_clips.setValue(c.processing.parallel_clips)
        self.p_parallel_vids.setValue(c.processing.parallel_videos)

    def _on_save(self) -> None:
        c = self.cfg
        c.paths.output_dir = self.output_dir.text().strip() or "./output"
        c.paths.work_dir = self.work_dir.text().strip() or "./work"
        c.paths.ffmpeg = self.ffmpeg.text().strip() or "ffmpeg"
        c.paths.ffprobe = self.ffprobe.text().strip() or "ffprobe"

        c.whisper.model = self.whisper_model.currentText()
        c.whisper.device = self.whisper_device.currentText()
        c.whisper.compute_type = self.whisper_compute.currentText()
        c.whisper.batch_size = self.whisper_batch.value()
        c.whisper.language = self.whisper_lang.text().strip() or "auto"
        c.whisper.skip_alignment = self.whisper_skip_align.isChecked()

        c.ollama.host = self.ollama_host.text().strip() or "http://localhost:11434"
        c.ollama.model = self.ollama_model.currentText().strip() or "llama3.1:8b"
        c.ollama.temperature = self.ollama_temp.value()
        c.ollama.num_predict = self.ollama_predict.value()
        c.ollama.num_ctx = self.ollama_ctx.value()

        c.processing.parallel_clips = self.p_parallel_clips.value()
        c.processing.parallel_videos = self.p_parallel_vids.value()

        save_config(c)
        self.accept()
