"""Render dimension helpers and OpenCV scaling utilities."""

import os

VERTICAL_RATIOS = {"9:16", "3:4", "4:5"}
RATIO_VALUES = {
    "9:16": 9 / 16,
    "16:9": 16 / 9,
    "1:1": 1.0,
    "3:4": 3 / 4,
    "4:5": 4 / 5,
}


def _is_vertical_ratio(ratio: str) -> bool:
    return ratio in VERTICAL_RATIOS


def _get_render_dims(cfg, ratio: str, source_h: int = 1080):
    """Return even output dimensions for a ratio and render height.

    render_height may be 'source' (match source) or a number. 9:16 keeps the
    familiar 1080x1920 default; 16:9 is 1920x1080; the rest derive from height.
    """
    target = getattr(cfg, "render_output_height", 1080)
    if isinstance(target, str):
        target = target.strip().lower()
        if target == "source" and source_h:
            height = int(source_h)
        else:
            try:
                height = int(float(target))
            except (TypeError, ValueError):
                height = 1080
    else:
        height = int(target or 1080)

    if ratio == "16:9":
        height = 1080 if height >= 1000 else height
    elif _is_vertical_ratio(ratio) and height < 1800:
        height = 1920

    height = max(2, height)
    width = int(round(height * RATIO_VALUES.get(ratio, 9 / 16)))
    width += width % 2
    height += height % 2
    return width, height


def _get_cv2_interpolation(algo: str):
    import cv2

    return {
        "lanczos": cv2.INTER_LANCZOS4,
        "bicubic": cv2.INTER_CUBIC,
        "bilinear": cv2.INTER_LINEAR,
        "area": cv2.INTER_AREA,
    }.get(str(algo or "lanczos").lower(), cv2.INTER_LANCZOS4)


def _resize_frame(frame, width: int, height: int, algo: str = "lanczos"):
    import cv2

    return cv2.resize(frame, (int(width), int(height)), interpolation=_get_cv2_interpolation(algo))


def _cover_scale(frame, width: int, height: int, algo: str = "lanczos"):
    """Scale to cover the target box, then center-crop."""
    import cv2

    h, w = frame.shape[:2]
    scale = max(width / w, height / h)
    new_w, new_h = max(1, int(round(w * scale))), max(1, int(round(h * scale)))
    resized = _resize_frame(frame, new_w, new_h, algo)
    x = max(0, (new_w - width) // 2)
    y = max(0, (new_h - height) // 2)
    return resized[y:y + height, x:x + width]


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
