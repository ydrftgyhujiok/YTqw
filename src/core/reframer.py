"""Построение FFmpeg-фильтра для 9:16 кадрирования.

Поддерживает два режима:
- center_crop: жёсткий кроп центра 16:9 -> 9:16
- center_blur: исходное видео по центру + размытый фон, заполняющий 9:16
"""

from __future__ import annotations

from ..app_config import VideoConfig


def build_reframe_filter(cfg: VideoConfig) -> str:
    w, h = cfg.width, cfg.height
    if cfg.reframe_mode == "center_crop":
        # Берём центр шириной h*9/16 от исходника и масштабируем
        return (
            f"[0:v]scale=-2:{h}:flags=lanczos,"
            f"crop={w}:{h}:(in_w-{w})/2:0,"
            f"setsar=1[v]"
        )
    # center_blur (по умолчанию)
    # 1) bg: масштабируем входное видео на размер canvas с заполнением + размываем
    # 2) fg: исходное видео ужимаем по ширине canvas, центрируем
    # 3) накладываем fg на bg
    blur = max(1, cfg.blur_strength)
    return (
        f"[0:v]split=2[main][bg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},boxblur={blur}:1[bgblur];"
        f"[main]scale={w}:-2:flags=lanczos[fg];"
        f"[bgblur][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
    )
