"""Smart auto-framing renderer.

Reads the source range, moves a virtual camera (face tracking + deadzone +
smoothing), composes the target ratio (crop, or blurred backdrop when the
source is narrower than the crop), writes a silent MPEG-TS intermediate. The
original audio is muxed later together with subtitles and BGM.
"""

import os

from .face_detection import FaceTracker
from .ffmpeg_utils import open_ffmpeg_video_writer
from .utils import (
    _get_render_dims,
    _is_vertical_ratio,
    _resize_frame,
    _cover_scale,
)


def _compose(frame, crop_x, crop_w, out_w, out_h, ratio, cfg, fill_mode="crop"):
    import cv2
    import numpy as np

    h, w = frame.shape[:2]
    algo = getattr(cfg, "video_scale_algo", "lanczos")

    if crop_w >= w - 1 and _is_vertical_ratio(ratio):
        # Portrait source narrower than the target crop: blurred backdrop.
        bg = _cover_scale(frame, out_w, out_h, "bilinear")
        bg = cv2.GaussianBlur(bg, (0, 0), sigmaX=max(8, out_w // 40))
        bg = (bg * 0.55).astype(np.uint8)
        scale = out_h / h
        fg_w = max(2, int(round(w * scale)))
        fg = _resize_frame(frame, fg_w, out_h, algo)
        x = max(0, (out_w - fg_w) // 2)
        canvas = bg.copy()
        canvas[0:out_h, x:x + fg_w] = fg[:, :out_w]
        return canvas

    x0 = int(max(0, min(w - crop_w, crop_x)))
    crop = frame[:, x0:x0 + crop_w]
    return _resize_frame(crop, out_w, out_h, algo)


def buat_video_hybrid(
    input_path,
    output_path,
    start_time,
    end_time,
    ratio,
    cfg,
    broll_data=None,
    label="Hybrid render",
):
    """Render the visual track for [start_time, end_time] into output_path."""
    import cv2

    duration = max(0.1, float(end_time) - float(start_time))
    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open source video: {input_path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out_w, out_h = _get_render_dims(cfg, ratio, source_h=src_h)

    if _is_vertical_ratio(ratio):
        crop_w = min(src_w, int(round(src_h * out_w / out_h)))
    elif ratio == "16:9":
        crop_w = src_w
    else:
        crop_w = min(src_w, int(round(src_h * out_w / out_h)))
    crop_w = max(2, crop_w)

    fps = 30.0
    frame_step = max(1.0, src_fps / fps)
    tracker = FaceTracker(cfg)
    total_frames = max(1, int(round(duration * fps)))

    proc = open_ffmpeg_video_writer(output_path, out_w, out_h, int(fps), _encoder_for(cfg, out_h))
    print(
        f"      {label}: {duration:.1f}s -> {out_w}x{out_h} @ {int(fps)}fps "
        f"({total_frames} frames)",
        flush=True,
    )

    written = 0
    try:
        assert proc.stdin is not None
        for idx in range(total_frames):
            t = float(start_time) + idx / fps
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                break
            center, boxes = tracker.update(frame, t, crop_w)
            frame = tracker.draw_overlays(frame, center - crop_w / 2, crop_w, boxes)
            out = _compose(frame, center - crop_w / 2, crop_w, out_w, out_h, ratio, cfg)
            proc.stdin.write(out.tobytes())
            written += 1
            if idx % 90 == 0:
                print(f"        {label}: {int(idx / total_frames * 100)}%", flush=True)
        proc.stdin.close()
        rc = proc.wait()
        if rc != 0:
            err = proc.stderr.read().decode("utf-8", "ignore") if proc.stderr else ""
            raise RuntimeError(f"FFmpeg visual render failed ({label}): {err[-600:]}")
    finally:
        cap.release()
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass

    if not written:
        raise RuntimeError(f"No frames were rendered for {label}.")

    if broll_data:
        _overlay_broll(output_path, broll_data, start_time, out_w, out_h, cfg, fps)
    return lambda _t: out_w / 2


def _encoder_for(cfg, target_h):
    from .ffmpeg_utils import detect_video_encoder

    return detect_video_encoder(cfg, target_h=target_h)


def _overlay_broll(path, broll_list, clip_start, out_w, out_h, cfg, fps):
    """Insert contextual B-roll with a short crossfade over the silent track."""
    import subprocess

    usable = [b for b in broll_list if os.path.exists(b.get("filepath", ""))]
    if not usable:
        return
    tmp = path + ".broll.mp4"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", path]
    for item in usable:
        cmd += ["-i", item["filepath"]]
    filters = []
    last = "0:v"
    for idx, item in enumerate(usable, start=1):
        s = max(0.0, float(item["start_time"]) - float(clip_start))
        e = max(s + 0.5, float(item["end_time"]) - float(clip_start))
        filters.append(
            f"[{idx}:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},fps={int(fps)},setpts=PTS-STARTPTS+{s}/TB[b{idx}]"
        )
        filters.append(
            f"[{last}][b{idx}]overlay=enable='between(t,{s:.2f},{e:.2f})':"
            f"eof_action=pass[v{idx}]"
        )
        last = f"v{idx}"
    cmd += [
        "-filter_complex", ";".join(filters),
        "-map", f"[{last}]", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-an", tmp,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0 and os.path.exists(tmp):
        os.replace(tmp, path)
    else:
        print(f"      B-roll overlay skipped: {result.stderr[-300:]}")
        if os.path.exists(tmp):
            os.remove(tmp)
