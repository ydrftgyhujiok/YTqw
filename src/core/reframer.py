"""Построение FFmpeg-фильтра для 9:16 кадрирования.

Поддерживает два режима:
- center_crop: жёсткий кроп центра 16:9 -> 9:16
- center_blur: исходное видео по центру + размытый фон, заполняющий 9:16
"""

from __future__ import annotations

from ..app_config import VideoConfig


def build_reframe_filter(cfg: VideoConfig) -> str:
    w, h = cfg.width, cfg.height
    # Масштаб переднего слоя в пикселях
    fg_scale_pct = max(10, min(500, cfg.foreground_scale or 100))
    fg_target_w = int(w * fg_scale_pct / 100)
    # Чтобы получилось чётное значение для yuv420p
    if fg_target_w % 2:
        fg_target_w -= 1

    if cfg.reframe_mode == "center_crop":
        # Жёсткий центр-кроп с учётом масштаба переднего слоя
        # (масштабируем исходник по высоте + crop по ширине)
        return (
            f"[0:v]scale=-2:{int(h * fg_scale_pct / 100)}:flags=lanczos,"
            f"crop={w}:{h}:(in_w-{w})/2:(in_h-{h})/2,"
            f"setsar=1[v]"
        )

    # center_blur (по умолчанию)
    # 1) bg: масштабируем входное видео на размер canvas с заполнением + размываем
    # 2) fg: исходное видео масштабируется до ширины fg_target_w; если оно становится
    #    шире холста — обрезаем центром по ширине, если выше холста — обрезаем по высоте
    # 3) накладываем fg на bg, центрируем (с вертикальным сдвигом если задан)
    blur = max(1, cfg.blur_strength)
    offset_y_px = int(h * (cfg.foreground_offset_y or 0) / 100)
    overlay_y = f"(H-h)/2+{offset_y_px}"

    return (
        f"[0:v]split=2[main][bg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},boxblur={blur}:1[bgblur];"
        f"[main]scale={fg_target_w}:-2:flags=lanczos,"
        f"crop='min(iw,{w})':'min(ih,{h})':"
        f"'(iw-min(iw,{w}))/2':'(ih-min(ih,{h}))/2'[fg];"
        f"[bgblur][fg]overlay=(W-w)/2:{overlay_y},setsar=1[v]"
    )
