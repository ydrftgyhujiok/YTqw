"""Диалог редактирования профиля канала."""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QSpinBox,
    QDoubleSpinBox, QComboBox, QPushButton, QTabWidget, QWidget, QCheckBox,
    QFileDialog, QLabel,
)

from ..profile import Profile, save_profile


ENCODERS = ["h264_nvenc", "hevc_nvenc", "libx264"]
NVENC_PRESETS = ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
REFRAME_MODES = ["center_blur", "center_crop"]
SUB_STYLES = ["word_by_word", "phrase"]


class ProfileEditDialog(QDialog):
    """Все настройки конкретного канала. Глобальные (Whisper/Ollama/ffmpeg)
    редактируются отдельно через Настройки приложения."""

    def __init__(self, profile: Profile, parent=None) -> None:
        super().__init__(parent)
        self.profile = profile
        self.setWindowTitle(f"Профиль: {profile.name}")
        self.resize(720, 660)
        self._build()
        self._populate()

    def _build(self) -> None:
        layout = QVBoxLayout(self)

        # Шапка — имя профиля
        header = QFormLayout()
        self.name_edit = QLineEdit()
        header.addRow("Имя профиля", self.name_edit)
        layout.addLayout(header)

        tabs = QTabWidget()

        # --- Папки ---
        folders = QWidget()
        ff = QFormLayout(folders)
        self.source_dir = QLineEdit()
        self.output_dir = QLineEdit()
        for line, label in [
            (self.source_dir, "Папка с исходными видео"),
            (self.output_dir, "Папка вывода клипов"),
        ]:
            row = QHBoxLayout()
            row.addWidget(line, 1)
            btn = QPushButton("…"); btn.setFixedWidth(32)
            btn.clicked.connect(lambda _=False, le=line: self._pick_dir(le))
            row.addWidget(btn)
            w = QWidget(); w.setLayout(row)
            ff.addRow(label, w)
        ff.addRow(QLabel(
            "Если оставить «Папка с исходными» пустой — будешь добавлять видео вручную."
        ))
        tabs.addTab(folders, "Папки")

        # --- Видео ---
        vt = QWidget(); vf = QFormLayout(vt)
        self.v_w = QSpinBox(); self.v_w.setRange(360, 3840)
        self.v_h = QSpinBox(); self.v_h.setRange(640, 3840)
        self.v_fps = QSpinBox(); self.v_fps.setRange(24, 120)
        self.v_enc = QComboBox(); self.v_enc.addItems(ENCODERS)
        self.v_preset = QComboBox(); self.v_preset.addItems(NVENC_PRESETS)
        self.v_cq = QSpinBox(); self.v_cq.setRange(0, 51)
        self.v_maxbr = QLineEdit()
        self.v_reframe = QComboBox(); self.v_reframe.addItems(REFRAME_MODES)
        self.v_blur = QSpinBox(); self.v_blur.setRange(0, 80)
        self.v_fg_scale = QSpinBox(); self.v_fg_scale.setRange(50, 400); self.v_fg_scale.setSuffix(" %")
        self.v_fg_offset = QSpinBox(); self.v_fg_offset.setRange(-40, 40); self.v_fg_offset.setSuffix(" %")
        vf.addRow("Ширина (px)", self.v_w)
        vf.addRow("Высота (px)", self.v_h)
        vf.addRow("FPS", self.v_fps)
        vf.addRow("Кодировщик", self.v_enc)
        vf.addRow("NVENC preset", self.v_preset)
        vf.addRow("CQ (качество)", self.v_cq)
        vf.addRow("Max bitrate", self.v_maxbr)
        vf.addRow("Reframe mode", self.v_reframe)
        vf.addRow("Сила blur", self.v_blur)
        vf.addRow("Масштаб переднего слоя", self.v_fg_scale)
        vf.addRow("Сдвиг переднего слоя по Y", self.v_fg_offset)
        vf.addRow(QLabel(
            "Масштаб > 100% делает видео крупнее (центральный кроп). "
            "Полезно для шортсов на телефоне — крупное лицо/действие."
        ))
        tabs.addTab(vt, "Видео")

        # --- Субтитры ---
        st = QWidget(); sf = QFormLayout(st)
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

        # --- Анализ ---
        at = QWidget(); af = QFormLayout(at)
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

        layout.addWidget(tabs)

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

    def _populate(self) -> None:
        p = self.profile
        self.name_edit.setText(p.name)
        self.source_dir.setText(p.source_dir)
        self.output_dir.setText(p.output_dir)

        self.v_w.setValue(p.video.width)
        self.v_h.setValue(p.video.height)
        self.v_fps.setValue(p.video.fps)
        self.v_enc.setCurrentText(p.video.encoder)
        self.v_preset.setCurrentText(p.video.nvenc_preset)
        self.v_cq.setValue(p.video.cq)
        self.v_maxbr.setText(p.video.max_bitrate)
        self.v_reframe.setCurrentText(p.video.reframe_mode)
        self.v_blur.setValue(p.video.blur_strength)
        self.v_fg_scale.setValue(getattr(p.video, "foreground_scale", 100))
        self.v_fg_offset.setValue(getattr(p.video, "foreground_offset_y", 0))

        self.s_style.setCurrentText(p.subtitles.style)
        self.s_font.setText(p.subtitles.font)
        self.s_size.setValue(p.subtitles.font_size)
        self.s_primary.setText(p.subtitles.primary_color)
        self.s_hi.setText(p.subtitles.highlight_color)
        self.s_outline.setText(p.subtitles.outline_color)
        self.s_thick.setValue(p.subtitles.outline_thickness)
        self.s_shadow.setValue(p.subtitles.shadow)
        self.s_margin.setValue(p.subtitles.bottom_margin)
        self.s_chars.setValue(p.subtitles.max_chars_per_line)
        self.s_upper.setChecked(p.subtitles.uppercase)

        self.an_chunk.setValue(p.analysis.chunk_seconds)
        self.an_min.setValue(p.analysis.min_clip_seconds)
        self.an_max.setValue(p.analysis.max_clip_seconds)
        self.an_max_clips.setValue(p.analysis.max_clips_per_video)
        self.an_min_score.setValue(p.analysis.min_score)

    def _on_save(self) -> None:
        p = self.profile
        new_name = self.name_edit.text().strip() or "Profile"
        # При смене имени сохранится новый файл; старый файл вызывающий код
        # удалит сам (через rename_profile), если имя изменилось.
        p.name = new_name
        p.source_dir = self.source_dir.text().strip()
        p.output_dir = self.output_dir.text().strip() or f"./output/{p.slug}"

        p.video.width = self.v_w.value()
        p.video.height = self.v_h.value()
        p.video.fps = self.v_fps.value()
        p.video.encoder = self.v_enc.currentText()
        p.video.nvenc_preset = self.v_preset.currentText()
        p.video.cq = self.v_cq.value()
        p.video.max_bitrate = self.v_maxbr.text().strip() or "12M"
        p.video.reframe_mode = self.v_reframe.currentText()
        p.video.blur_strength = self.v_blur.value()
        p.video.foreground_scale = self.v_fg_scale.value()
        p.video.foreground_offset_y = self.v_fg_offset.value()

        p.subtitles.style = self.s_style.currentText()
        p.subtitles.font = self.s_font.text().strip() or "Arial"
        p.subtitles.font_size = self.s_size.value()
        p.subtitles.primary_color = self.s_primary.text().strip() or "&H00FFFFFF"
        p.subtitles.highlight_color = self.s_hi.text().strip() or "&H0000FFFF"
        p.subtitles.outline_color = self.s_outline.text().strip() or "&H00000000"
        p.subtitles.outline_thickness = self.s_thick.value()
        p.subtitles.shadow = self.s_shadow.value()
        p.subtitles.bottom_margin = self.s_margin.value()
        p.subtitles.max_chars_per_line = self.s_chars.value()
        p.subtitles.uppercase = self.s_upper.isChecked()

        p.analysis.chunk_seconds = self.an_chunk.value()
        p.analysis.min_clip_seconds = self.an_min.value()
        p.analysis.max_clip_seconds = self.an_max.value()
        p.analysis.max_clips_per_video = self.an_max_clips.value()
        p.analysis.min_score = self.an_min_score.value()

        save_profile(p)
        self.accept()
