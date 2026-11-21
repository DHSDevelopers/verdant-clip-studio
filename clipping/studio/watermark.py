"""Watermark overlay (text or image) with 9-anchor positioning."""

import os
import subprocess

POSITIONS = {
    "top-left": ("W*0.04", "H*0.04"),
    "top-center": ("(W-w)/2", "H*0.04"),
    "top-right": ("W-w-W*0.04", "H*0.04"),
    "center-left": ("W*0.04", "(H-h)/2"),
    "center": ("(W-w)/2", "(H-h)/2"),
    "center-right": ("W-w-W*0.04", "(H-h)/2"),
    "bottom-left": ("W*0.04", "H-h-H*0.04"),
    "bottom-center": ("(W-w)/2", "H-h-H*0.04"),
    "bottom-right": ("W-w-W*0.04", "H-h-H*0.04"),
}


def _font_file(cfg):
    try:
        info = cfg.daftar_font[cfg.gaya_font_aktif]["utama"]
        path = os.path.join(cfg.font_dir, info["file"])
        if os.path.exists(path):
            return path
    except Exception:
        pass
    return None


def build_watermark_filter(cfg, width: int, height: int):
    """Return an FFmpeg filter fragment drawing the watermark, or None."""
    if not getattr(cfg, "watermark_enabled", False):
        return None
    position = getattr(cfg, "watermark_position", "center-right")
    x_expr, y_expr = POSITIONS.get(position, POSITIONS["center-right"])
    pad = int(getattr(cfg, "watermark_padding", 0) or 0)
    if pad:
        x_expr = f"{x_expr}+{pad}" if "left" in position else (
            f"{x_expr}-{pad}" if "right" in position else x_expr
        )
        y_expr = f"{y_expr}+{pad}" if "top" in position else (
            f"{y_expr}-{pad}" if "bottom" in position else y_expr
        )
    opacity = max(0.01, min(1.0, int(getattr(cfg, "watermark_opacity", 70) or 70) / 100.0))

    image = getattr(cfg, "watermark_image", None)
    if image and os.path.exists(image):
        return (
            f"movie='{os.path.abspath(image).replace(chr(92), '/').replace(':', chr(92) + ':')}'"
            f"[wm];[wm]format=rgba,colorchannelmixer=aa={opacity:.2f},"
            f"scale=-1:{int(height * int(getattr(cfg, 'watermark_scale', 15) or 15) / 100)}[wms];"
            f"[in][wms]overlay={x_expr}:{y_expr}[out]"
        )

    text = str(getattr(cfg, "watermark_text", "") or "").replace("'", "\\'").replace(":", "\\:")
    if not text:
        return None
    size = int(getattr(cfg, "watermark_font_size", 0) or 0) or max(14, int(height * 0.03))
    font = _font_file(cfg)
    font_arg = f":fontfile='{font.replace(chr(92), '/').replace(':', chr(92) + ':')}'" if font else ""
    return (
        f"drawtext=text='{text}'{font_arg}:fontsize={size}:"
        f"fontcolor=white@{opacity:.2f}:borderw=2:bordercolor=black@0.55:"
        f"x={x_expr}:y={y_expr}"
    )


def apply_watermark(input_path: str, cfg, width: int, height: int, encoder_args) -> bool:
    filt = build_watermark_filter(cfg, width, height)
    if not filt:
        return False
    tmp = input_path + ".wm.mp4"
    if "[in]" in filt:
        vf_args = ["-filter_complex", filt.replace("[in]", "[0:v]"), "-map", "[out]", "-map", "0:a?"]
    else:
        vf_args = ["-vf", filt]
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", input_path]
    cmd += vf_args + encoder_args + [tmp]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and os.path.exists(tmp):
        os.replace(tmp, input_path)
        return True
    if os.path.exists(tmp):
        os.remove(tmp)
    print(f"      Watermark skipped: {result.stderr[-300:]}")
    return False
