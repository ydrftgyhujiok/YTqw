"""Диалог настроек — выбор моделей, путей, параметров рендера."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QSpinBox,
    QDoubleSpinBox, QComboBox, QPushButton, QTabWidget, QWidget, QCheckBox,
    QFileDialog, QLabel,
)

from ..app_config import AppConfig, save_config


WHISPER_MODELS = ["tiny", "base", "small", "medium", "large-v2", "large-v3"]
WHISPER_DEVICES = ["auto", "cuda", "cpu"]
WHISPER_COMPUTE = ["float16", "int8", "float32"]
ENCODERS = ["h264_nvenc", "hevc_nvenc", "libx264"]
NVENC_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
REFRAME_MODES = ["center_blur", "center_crop"]
SUB_STYLES = ["word_by_word", "phrase"]
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
        self.setWindowTitle("Настройки")
        self.resize(640, 600)
        self._build()
        self._populate()

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        tabs = QTabWidget()

        # --- Пути ---
        paths_tab = QWidget()
        pf = QFormLayout(paths_tab)
        self.output_dir = QLineEdit()
        self.work_dir = QLineEdit()
        self.ffmpeg = QLineEdit()
        self.ffprobe = QLineEdit()
        for line, label, picker in [
            (self.output_dir, "Папка вывода клипов", self._pick_dir),
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
        wf.addRow("Модель Whisper", self.whisper_model)
        wf.addRow("Устройство", self.whisper_device)
        wf.addRow("Compute type", self.whisper_compute)
        wf.addRow("Batch size", self.whisper_batch)
        wf.addRow("Язык (auto = автодетект)", self.whisper_lang)
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

        # --- Анализ ---
        at = QWidget()
        af = QFormLayout(at)
        self.an_chunk = QSpinBox(); self.an_chunk.setRange(60, 3600)
        self.an_min = QSpinBox(); self.an_min.setRange(5, 120)
        self.an_max = QSpinBox(); self.an_max.setRange(10, 180)
        self.an_max_clips = QSpinBox(); self.an_max_clips.setRange(1, 50)
        self.an_min_score = QDoubleSpinBox(); self.an_min_score.setRange(0.0, 10.0); self.an_min_score.setSingleStep(0.1)
        af.addRow("Размер фрагмента (сек)", self.an_chunk)
        af.addRow("Мин. длина клипа (сек)", self.an_min)
        af.addRow("Макс. длина клипа (сек)", self.an_max)
        af.addRow("Макс. клипов из видео", self.an_max_clips)
        af.addRow("Мин. score (0–10)", self.an_min_score)
        tabs.addTab(at, "Анализ")

        # --- Видео ---
        vt = QWidget()
        vf = QFormLayout(vt)
        self.v_w = QSpinBox(); self.v_w.setRange(360, 3840)
        self.v_h = QSpinBox(); self.v_h.setRange(640, 3840)
        self.v_fps = QSpinBox(); self.v_fps.setRange(24, 120)
        self.v_enc = QComboBox(); self.v_enc.addItems(ENCODERS)
        self.v_preset = QComboBox(); self.v_preset.addItems(NVENC_PRESETS)
        self.v_cq = QSpinBox(); self.v_cq.setRange(0, 51)
        self.v_maxbr = QLineEdit()
        self.v_reframe = QComboBox(); self.v_reframe.addItems(REFRAME_MODES)
        self.v_blur = QSpinBox(); self.v_blur.setRange(0, 80)
        vf.addRow("Ширина (px)", self.v_w)
        vf.addRow("Высота (px)", self.v_h)
        vf.addRow("FPS", self.v_fps)
        vf.addRow("Кодировщик", self.v_enc)
        vf.addRow("NVENC preset", self.v_preset)
        vf.addRow("CQ (качество)", self.v_cq)
        vf.addRow("Max bitrate", self.v_maxbr)
        vf.addRow("Reframe mode", self.v_reframe)
        vf.addRow("Сила blur", self.v_blur)
        tabs.addTab(vt, "Видео")

        # --- Субтитры ---
        st = QWidget()
        sf = QFormLayout(st)
        self.s_style = QComboBox(); self.s_style.addItems(SUB_STYLES)
        self.s_font = QLineEdit()
        self.s_size = QSpinBox(); self.s_size.setRange(8, 80)
        self.s_primary = QLineEdit()
        self.s_hi = QLineEdit()
        self.s_outline = QLineEdit()
        self.s_thick = QSpinBox(); self.s_thick.setRange(0, 10)
        self.s_shadow = QSpinBox(); self.s_shadow.setRange(0, 10)
        self.s_margin = QSpinBox(); self.s_margin.setRange(0, 1800)
        self.s_chars = QSpinBox(); self.s_chars.setRange(8, 60)
        self.s_upper = QCheckBox("ВЕРХНИЙ РЕГИСТР")
        sf.addRow("Стиль", self.s_style)
        sf.addRow("Шрифт", self.s_font)
        sf.addRow("Размер (логические px)", self.s_size)
        sf.addRow("Цвет основной (ASS &H00BBGGRR)", self.s_primary)
        sf.addRow("Цвет подсветки", self.s_hi)
        sf.addRow("Цвет обводки", self.s_outline)
        sf.addRow("Толщина обводки", self.s_thick)
        sf.addRow("Тень", self.s_shadow)
        sf.addRow("Отступ снизу (px)", self.s_margin)
        sf.addRow("Макс. символов в строке", self.s_chars)
        sf.addRow("", self.s_upper)
        tabs.addTab(st, "Субтитры")

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

        self.ollama_host.setText(c.ollama.host)
        self.ollama_model.setCurrentText(c.ollama.model)
        self.ollama_temp.setValue(c.ollama.temperature)
        self.ollama_predict.setValue(c.ollama.num_predict)
        self.ollama_ctx.setValue(c.ollama.num_ctx)

        self.an_chunk.setValue(c.analysis.chunk_seconds)
        self.an_min.setValue(c.analysis.min_clip_seconds)
        self.an_max.setValue(c.analysis.max_clip_seconds)
        self.an_max_clips.setValue(c.analysis.max_clips_per_video)
        self.an_min_score.setValue(c.analysis.min_score)

        self.v_w.setValue(c.video.width)
        self.v_h.setValue(c.video.height)
        self.v_fps.setValue(c.video.fps)
        self.v_enc.setCurrentText(c.video.encoder)
        self.v_preset.setCurrentText(c.video.nvenc_preset)
        self.v_cq.setValue(c.video.cq)
        self.v_maxbr.setText(c.video.max_bitrate)
        self.v_reframe.setCurrentText(c.video.reframe_mode)
        self.v_blur.setValue(c.video.blur_strength)

        self.s_style.setCurrentText(c.subtitles.style)
        self.s_font.setText(c.subtitles.font)
        self.s_size.setValue(c.subtitles.font_size)
        self.s_primary.setText(c.subtitles.primary_color)
        self.s_hi.setText(c.subtitles.highlight_color)
        self.s_outline.setText(c.subtitles.outline_color)
        self.s_thick.setValue(c.subtitles.outline_thickness)
        self.s_shadow.setValue(c.subtitles.shadow)
        self.s_margin.setValue(c.subtitles.bottom_margin)
        self.s_chars.setValue(c.subtitles.max_chars_per_line)
        self.s_upper.setChecked(c.subtitles.uppercase)

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

        c.ollama.host = self.ollama_host.text().strip() or "http://localhost:11434"
        c.ollama.model = self.ollama_model.currentText().strip() or "llama3.1:8b"
        c.ollama.temperature = self.ollama_temp.value()
        c.ollama.num_predict = self.ollama_predict.value()
        c.ollama.num_ctx = self.ollama_ctx.value()

        c.analysis.chunk_seconds = self.an_chunk.value()
        c.analysis.min_clip_seconds = self.an_min.value()
        c.analysis.max_clip_seconds = self.an_max.value()
        c.analysis.max_clips_per_video = self.an_max_clips.value()
        c.analysis.min_score = self.an_min_score.value()

        c.video.width = self.v_w.value()
        c.video.height = self.v_h.value()
        c.video.fps = self.v_fps.value()
        c.video.encoder = self.v_enc.currentText()
        c.video.nvenc_preset = self.v_preset.currentText()
        c.video.cq = self.v_cq.value()
        c.video.max_bitrate = self.v_maxbr.text().strip() or "12M"
        c.video.reframe_mode = self.v_reframe.currentText()
        c.video.blur_strength = self.v_blur.value()

        c.subtitles.style = self.s_style.currentText()
        c.subtitles.font = self.s_font.text().strip() or "Arial"
        c.subtitles.font_size = self.s_size.value()
        c.subtitles.primary_color = self.s_primary.text().strip() or "&H00FFFFFF"
        c.subtitles.highlight_color = self.s_hi.text().strip() or "&H0000FFFF"
        c.subtitles.outline_color = self.s_outline.text().strip() or "&H00000000"
        c.subtitles.outline_thickness = self.s_thick.value()
        c.subtitles.shadow = self.s_shadow.value()
        c.subtitles.bottom_margin = self.s_margin.value()
        c.subtitles.max_chars_per_line = self.s_chars.value()
        c.subtitles.uppercase = self.s_upper.isChecked()

        c.processing.parallel_clips = self.p_parallel_clips.value()
        c.processing.parallel_videos = self.p_parallel_vids.value()

        save_config(c)
        self.accept()
