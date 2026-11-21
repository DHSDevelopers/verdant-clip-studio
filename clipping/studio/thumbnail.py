"""Extract a frame, darken it and draw a large wrapped title."""

import os
import subprocess
import textwrap


def buat_thumbnail(video_path: str, out_path: str, title: str, cfg) -> str:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("      Pillow is not installed; skipping thumbnail.")
        return ""

    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        frame_path = tmp.name

    try:
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-ss", "1.0", "-i", video_path, "-vframes", "1", "-q:v", "2", frame_path,
            ],
            check=True,
        )
        image = Image.open(frame_path).convert("RGB")
        width, height = image.size

        overlay = Image.new("RGBA", image.size, (4, 10, 8, 0))
        draw = ImageDraw.Draw(overlay)
        draw.rectangle([0, int(height * 0.45), width, height], fill=(4, 10, 8, 195))
        image = Image.alpha_composite(image.convert("RGBA"), overlay)

        font = None
        for candidate in (
            os.path.join(cfg.font_dir, "Montserrat-Black.ttf"),
            os.path.join(cfg.font_dir, "Anton-Regular.ttf"),
        ):
            if os.path.exists(candidate):
                try:
                    font = ImageFont.truetype(candidate, int(width / 14))
                    break
                except OSError:
                    pass
        if font is None:
            font = ImageFont.load_default()

        draw = ImageDraw.Draw(image)
        wrapped = textwrap.fill(str(title or "Highlight"), width=22)
        bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=12)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        draw.multiline_text(
            ((width - text_w) / 2, height * 0.62 - text_h / 2),
            wrapped,
            font=font,
            fill=(230, 255, 245, 255),
            stroke_width=max(2, width // 300),
            stroke_fill=(7, 11, 10, 255),
            align="center",
            spacing=12,
        )
        accent_w = int(width * 0.12)
        draw.rectangle(
            [(width - accent_w) / 2, height * 0.62 + text_h / 2 + 26,
             (width + accent_w) / 2, height * 0.62 + text_h / 2 + 32],
            fill=(52, 245, 168, 255),
        )
        image.convert("RGB").save(out_path, quality=92)
        return out_path
    finally:
        if os.path.exists(frame_path):
            os.remove(frame_path)
