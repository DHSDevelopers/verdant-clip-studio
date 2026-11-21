"""Per-clip rendering orchestration: hook, main, BGM, concat, watermark."""

import os
import subprocess

from .audio_bgm import build_bgm_filter, get_local_bgm_file
from .broll import download_pexels_broll
from .effects import (
    create_glitch_transition,
    create_white_flash_transition,
    siapkan_glitch_video,
)
from .ffmpeg_utils import (
    detect_video_encoder,
    get_mp4_encode_args,
    probe_duration,
    run_ffmpeg_with_progress,
)
from .helpers import escape_ffmpeg_filter_value
from .render_hybrid import buat_video_hybrid
from .subtitles import buat_file_ass
from .thumbnail import buat_thumbnail
from .utils import _get_render_dims, _is_vertical_ratio, ensure_parent
from .watermark import apply_watermark


def _final_filename(rank, cfg):
    pattern = getattr(cfg, "output_naming", None)
    if not pattern:
        return f"highlight_rank_{rank}_ready.mp4"
    from datetime import datetime

    slug = os.path.basename(str(getattr(cfg, "outputs_dir", "clip")))
    name = (
        str(pattern)
        .replace("{rank}", str(rank))
        .replace("{slug}", slug)
        .replace("{date}", datetime.now().strftime("%Y%m%d"))
    )
    name = "".join(c for c in name if c.isalnum() or c in "._- ") or f"highlight_rank_{rank}"
    return name if name.lower().endswith(".mp4") else name + ".mp4"


def _encode_args(cfg, encoder, height):
    return get_mp4_encode_args(encoder, fps=30, target_h=height)


def _burn_mux(
    silent_path,
    src_path,
    start,
    end,
    ass_path,
    out_path,
    cfg,
    encoder,
    dims,
    bgm_file=None,
):
    """Mux original audio (+ optional BGM) and burn subtitles into an MP4."""
    width, height = dims
    if not os.path.exists(silent_path):
        raise RuntimeError(f"Silent visual track is missing: {silent_path}")
    if os.path.getsize(silent_path) < 1000:
        raise RuntimeError(f"Silent visual track is empty: {silent_path}")

    vf_parts = []
    if ass_path and not getattr(cfg, "no_subs", False):
        esc_ass = escape_ffmpeg_filter_value(ass_path)
        esc_fonts = escape_ffmpeg_filter_value(cfg.font_dir)
        vf_parts.append(f"subtitles={esc_ass}:fontsdir={esc_fonts}")
    if getattr(cfg, "video_sharpen", False):
        vf_parts.append("unsharp=5:5:0.5:5:5:0.0")
    vf = ",".join(vf_parts)

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "verbose", "-y",
        "-i", silent_path,
        "-ss", f"{float(start):.3f}", "-to", f"{float(end):.3f}", "-i", src_path,
    ]
    if bgm_file:
        cmd += ["-stream_loop", "-1", "-i", bgm_file]
        audio_filter = build_bgm_filter(
            getattr(cfg, "bgm_mode", "ducking"),
            getattr(cfg, "bgm_base_volume", 0.25),
            audio_input_voc="[1:a]",
            audio_input_bgm="[2:a]",
        )
        chain = f"[0:v]{vf}[v_out]; {audio_filter}" if vf else f"[0:v]null[v_out]; {audio_filter}"
        cmd += ["-filter_complex", chain, "-map", "[v_out]", "-map", "[a_out]", "-shortest"]
    else:
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
        if vf:
            cmd += ["-vf", vf]
    cmd += _encode_args(cfg, encoder, height)
    cmd.append(out_path)
    rc, err = run_ffmpeg_with_progress(cmd, float(end) - float(start), label="FFmpeg mux")
    if rc != 0:
        raise RuntimeError("FFmpeg mux failed:\n" + "\n".join(err))


def _concat(parts, out_path, cfg=None, encoder=None, dims=None, reencode=False):
    """Concat MP4 parts with the concat demuxer; re-encode as a fallback."""
    parts = [os.path.abspath(p) for p in parts if p and os.path.exists(p)]
    if not parts:
        raise RuntimeError("No visual parts to concatenate.")
    ensure_parent(out_path)
    if len(parts) == 1:
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", parts[0],
             "-c", "copy", out_path],
            check=True,
        )
        return out_path

    list_path = out_path + ".concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for part in parts:
            escaped = part.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "concat", "-safe", "0", "-i", list_path,
    ]
    if reencode:
        cmd += ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
    else:
        cmd += ["-c", "copy"]
    cmd.append(out_path)
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        os.remove(list_path)
    except OSError:
        pass
    if result.returncode != 0:
        if not reencode and cfg and encoder:
            return _concat(parts, out_path, cfg=cfg, encoder=encoder, dims=dims, reencode=True)
        raise RuntimeError(f"FFmpeg concat failed: {result.stderr[-600:]}")
    return out_path


def _attach_bgm(path, bgm_file, cfg, duration):
    if not bgm_file:
        return
    out_path = path + ".bgm.mp4"
    audio_filter = build_bgm_filter(
        getattr(cfg, "bgm_mode", "ducking"),
        getattr(cfg, "bgm_base_volume", 0.25),
        audio_input_voc="[0:a]",
        audio_input_bgm="[1:a]",
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", path, "-stream_loop", "-1", "-i", bgm_file,
        "-filter_complex", audio_filter,
        "-map", "0:v:0", "-map", "[a_out]", "-shortest",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", out_path,
    ]
    rc, err = run_ffmpeg_with_progress(cmd, duration, label="FFmpeg BGM")
    if rc == 0 and os.path.exists(out_path):
        os.replace(out_path, path)
    else:
        print("      BGM pass skipped:", " | ".join(err[-3:]))


def proses_klip(rank, clip, rasio, glitch_ts, data_segmen, cfg, video_encoder, diarization_data=None):
    """Render one clip and return its manifest row."""
    import cv2

    out_dir = cfg.outputs_dir
    os.makedirs(out_dir, exist_ok=True)

    h_start = float(clip.get("hook_start_time", clip["start_time"]))
    h_end = float(
        clip.get("hook_end_time", clip.get("hook_start_time", clip["start_time"]) + cfg.durasi_hook)
    )
    m_start = float(clip["start_time"])
    m_end = float(clip["end_time"])
    judul = clip.get("title_indonesia")
    judul_en = clip.get("title_inggris")

    cap = cv2.VideoCapture(cfg.file_video_asli)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    dims = _get_render_dims(cfg, rasio, source_h=src_h)
    source_dim = (src_w, src_h)

    out_vid = os.path.join(out_dir, _final_filename(rank, cfg))
    out_thm = os.path.join(out_dir, f"thumbnail_rank_{rank}.jpg")

    manifest = {
        "rank": rank,
        "status": "pending",
        "ratio": rasio,
        "video_path": out_vid,
        "output_file": out_vid,
        "thumbnail_path": out_thm,
        "thumbnail_text": judul_en or judul or f"Highlight {rank}",
        "youtube_title_final": clip.get("youtube_title_final", clip.get("title_inggris", "")),
        "youtube_description_final": clip.get("youtube_description_final", ""),
        "youtube_tags_final": clip.get("youtube_tags_final", []),
        "tiktok_caption_final": clip.get("tiktok_caption_final", clip.get("hastag", "")),
        "tiktok_title_id_final": clip.get("tiktok_title_id_final", ""),
        "tiktok_caption_id_final": clip.get("tiktok_caption_id_final", ""),
        "title_indonesia": clip.get("title_indonesia", ""),
        "title_inggris": clip.get("title_inggris", ""),
        "hastag": clip.get("hastag", ""),
        "viral_score": clip.get("viral_score"),
        "start_time": m_start,
        "end_time": m_end,
        "hook_start_time": h_start,
        "hook_end_time": h_end,
        "duration": round(m_end - m_start, 2),
        "alasan": clip.get("alasan", ""),
        "bgm_mood": clip.get("bgm_mood", ""),
        "broll_list": clip.get("broll_list", []),
        "typography_plan": clip.get("typography_plan", []),
        "klasifikasi_akun": clip.get("klasifikasi_akun", {}),
    }

    print(f"\n{'=' * 70}")
    print(f"[Rank {rank}] Rendering clip")
    print(f"Title (ID): {clip.get('title_indonesia', '-')}")
    print(f"Title (EN): {clip.get('title_inggris', '-')}")
    print(f"Encoder   : {video_encoder['name']}")
    print(f"{'=' * 70}")

    typography_plan = clip.get("typography_plan", [])
    siapkan_font_tipografi(cfg)
    h_main = os.path.join(out_dir, f"h_{rank}.mp4")
    m_main = os.path.join(out_dir, f"m_{rank}.mp4")
    a_hook = os.path.join(out_dir, f"ah_{rank}.ass")
    a_main = os.path.join(out_dir, f"am_{rank}.ass")
    h_silent = os.path.join(out_dir, f"h_silent_{rank}.mp4")
    m_silent = os.path.join(out_dir, f"m_silent_{rank}.mp4")

    file_hook_src = cfg.file_video_asli
    custom_hook = clip.get("custom_hook_info")
    if custom_hook:
        file_hook_src = custom_hook["file_path"]
        h_start = float(getattr(cfg, "hook_source_start", 0.0) or 0.0)
        h_end = h_start + float(cfg.durasi_hook)

    broll_aktif = []
    if getattr(cfg, "use_broll", True) and clip.get("broll_list"):
        print(f"   Fetching {len(clip['broll_list'])} B-roll clips from Pexels...")
        for i, br in enumerate(clip["broll_list"]):
            path = download_pexels_broll(
                br.get("search_query", "city night"),
                rasio,
                os.path.join(out_dir, f"temp_broll_{rank}_{i}.mp4"),
                getattr(cfg, "pexels_api_key", ""),
            )
            if path:
                item = dict(br)
                item["filepath"] = path
                broll_aktif.append(item)

    bgm_file = None
    if getattr(cfg, "use_auto_bgm", True):
        mood = clip.get("bgm_mood", "chill")
        if mood not in getattr(cfg, "bgm_moods", ["chill"]):
            mood = "chill"
        bgm_dir = getattr(cfg, "bgm_dir", os.path.join(cfg.base_dir, "assets", "bgm"))
        bgm_file = get_local_bgm_file(mood, bgm_dir) or get_local_bgm_file("chill", bgm_dir)
        if bgm_file:
            print(f"   BGM: {os.path.basename(bgm_file)} ({mood})")

    created = []
    try:
        # ------------------------------------------------------------- HOOK
        hook_parts = []
        if getattr(cfg, "hook_v2", False):
            print("   [Hook V2] Rendering multi-hook intro...")
            items = (clip.get("hook_v2") or {}).get("items") or []
            if not items:
                count = int(getattr(cfg, "hook_v2_items", 3) or 3)
                span = max(0.5, (h_end - h_start) / count)
                items = [
                    {"start_time": h_start + i * span,
                     "end_time": min(h_end, h_start + (i + 1) * span)}
                    for i in range(count)
                ]
            flash = float(getattr(cfg, "white_flash_duration", 0.12) or 0.12)
            trans_type = (clip.get("hook_v2") or {}).get("transition", {}).get("type", "white_flash")
            for i, item in enumerate(items):
                s, e = float(item["start_time"]), float(item["end_time"])
                silent = os.path.join(out_dir, f"h_v2_{rank}_{i}.mp4")
                buat_video_hybrid(file_hook_src, silent, s, e, rasio, cfg, label=f"Rank {rank} HookV2 {i}")
                created.append(silent)
                ass = os.path.join(out_dir, f"h_v2_{rank}_{i}.ass")
                if not getattr(cfg, "no_subs", False) and not custom_hook:
                    buat_file_ass(data_segmen, s, e, ass, rasio, cfg,
                                  typography_plan=typography_plan,
                                  gunakan_advanced=cfg.use_advanced_text_on_hook,
                                  source_dim=source_dim)
                    created.append(ass)
                piece = os.path.join(out_dir, f"h_v2_piece_{rank}_{i}.mp4")
                _burn_mux(silent, file_hook_src, s, e, ass if os.path.exists(ass) else None,
                          piece, cfg, video_encoder, dims, bgm_file=None)
                created.append(piece)
                hook_parts.append(piece)

                trans = os.path.join(out_dir, f"h_v2_trans_{rank}_{i}.mp4")
                if "glitch" in str(trans_type):
                    create_glitch_transition(trans, flash, dims[0], dims[1])
                else:
                    create_white_flash_transition(trans, flash, dims[0], dims[1])
                created.append(trans)
                hook_parts.append(trans)

            if hook_parts:
                _concat(hook_parts, h_main, cfg=cfg, encoder=video_encoder, dims=dims)
                created.append(h_main)
        elif getattr(cfg, "use_hook_glitch", True):
            print("   [Hook] Rendering teaser...")
            buat_video_hybrid(file_hook_src, h_silent, h_start, h_end, rasio, cfg,
                              label=f"Rank {rank} Hook")
            created.append(h_silent)
            if not getattr(cfg, "no_subs", False) and not custom_hook:
                buat_file_ass(data_segmen, h_start, h_end, a_hook, rasio, cfg,
                              typography_plan=typography_plan,
                              gunakan_advanced=cfg.use_advanced_text_on_hook,
                              source_dim=source_dim)
                created.append(a_hook)
            _burn_mux(
                h_silent, file_hook_src, h_start, h_end,
                a_hook if os.path.exists(a_hook) else None,
                h_main, cfg, video_encoder, dims, bgm_file=None,
            )
            created.append(h_main)

        # ------------------------------------------------------------- MAIN
        keep_segments = clip.get("keep_segments") or []
        use_segments = len(keep_segments) > 1 and not getattr(cfg, "no_segment_trim", False)

        if use_segments:
            print(f"   [Main] Rendering {len(keep_segments)} keep-segments...")
            seg_parts = []
            for idx, seg in enumerate(keep_segments):
                s, e = float(seg["start_time"]), float(seg["end_time"])
                silent = os.path.join(out_dir, f"m_seg_{rank}_{idx}.mp4")
                ass = os.path.join(out_dir, f"m_seg_{rank}_{idx}.ass")
                buat_video_hybrid(cfg.file_video_asli, silent, s, e, rasio, cfg,
                                  broll_aktif, label=f"Rank {rank} Seg {idx}")
                created.append(silent)
                if not getattr(cfg, "no_subs", False):
                    buat_file_ass(data_segmen, s, e, ass, rasio, cfg,
                                  typography_plan=typography_plan, gunakan_advanced=True,
                                  source_dim=source_dim)
                    created.append(ass)
                seg_out = os.path.join(out_dir, f"m_seg_out_{rank}_{idx}.mp4")
                _burn_mux(silent, cfg.file_video_asli, s, e,
                          ass if os.path.exists(ass) else None, seg_out, cfg,
                          video_encoder, dims, bgm_file=None)
                created.append(seg_out)
                seg_parts.append(seg_out)

            _concat(seg_parts, m_main, cfg=cfg, encoder=video_encoder, dims=dims)
            created.append(m_main)
            seg_total = sum(float(s["end_time"]) - float(s["start_time"]) for s in keep_segments)
            _attach_bgm(m_main, bgm_file, cfg, seg_total)
        else:
            print("   [Main] Rendering smart-framed main clip...")
            buat_video_hybrid(cfg.file_video_asli, m_silent, m_start, m_end, rasio, cfg,
                              broll_aktif, label=f"Rank {rank} Main")
            created.append(m_silent)
            if not getattr(cfg, "no_subs", False):
                buat_file_ass(data_segmen, m_start, m_end, a_main, rasio, cfg,
                              typography_plan=typography_plan, gunakan_advanced=True,
                              source_dim=source_dim)
                created.append(a_main)
            _burn_mux(
                m_silent, cfg.file_video_asli, m_start, m_end,
                a_main if os.path.exists(a_main) else None,
                m_main, cfg, video_encoder, dims, bgm_file=bgm_file,
            )
            created.append(m_main)

        # ----------------------------------------------------------- CONCAT
        parts = []
        if os.path.exists(h_main):
            parts.append(h_main)
            if getattr(cfg, "use_hook_glitch", True) and not getattr(cfg, "hook_v2", False):
                if glitch_ts and os.path.exists(glitch_ts):
                    parts.append(glitch_ts)
        parts.append(m_main)

        ensure_parent(out_vid)
        _concat(parts, out_vid, cfg=cfg, encoder=video_encoder, dims=dims)

        # -------------------------------------------------------- WATERMARK
        if getattr(cfg, "watermark_enabled", False):
            mp4_args = get_mp4_encode_args(video_encoder, fps=30, target_h=dims[1])
            apply_watermark(out_vid, cfg, dims[0], dims[1], mp4_args)

        # -------------------------------------------------------- THUMBNAIL
        try:
            buat_thumbnail(out_vid, out_thm, judul_en or judul or f"Highlight {rank}", cfg)
        except Exception as exc:
            print(f"      Thumbnail skipped: {exc}")

        manifest["status"] = "success"
        manifest["video_exists"] = os.path.exists(out_vid)
        manifest["thumbnail_exists"] = os.path.exists(out_thm)
        manifest["file_size_mb"] = (
            round(os.path.getsize(out_vid) / (1024 * 1024), 2) if os.path.exists(out_vid) else 0
        )
        manifest["duration"] = round(probe_duration(out_vid) or (m_end - m_start), 2)
        print(f"[Rank {rank}] Done -> {os.path.basename(out_vid)}")
        return manifest

    except subprocess.CalledProcessError as exc:
        print(f"\nERROR: FFmpeg failed. {exc}")
        manifest.update(status="failed", error=str(exc),
                        video_exists=os.path.exists(out_vid),
                        thumbnail_exists=os.path.exists(out_thm))
        return manifest
    except Exception as exc:
        print(f"\nERROR: Unexpected renderer failure. {exc}")
        manifest.update(status="failed", error=str(exc),
                        video_exists=os.path.exists(out_vid),
                        thumbnail_exists=os.path.exists(out_thm))
        return manifest
    finally:
        for path in created:
            try:
                if path and os.path.exists(path) and path != out_vid:
                    os.remove(path)
            except OSError:
                pass
        for item in broll_aktif:
            try:
                if os.path.exists(item.get("filepath", "")):
                    os.remove(item["filepath"])
            except OSError:
                pass


def estimate_speaker_count_from_video(video_path, cfg, samples=8):
    """Rough visual speaker estimate used for diarization bounds."""
    import cv2

    from .face_detection import get_face_detector

    detector = get_face_detector(cfg)
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    max_faces = 1
    for i in range(samples):
        if total:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(total * (i + 0.5) / samples))
        ok, frame = cap.read()
        if not ok:
            continue
        try:
            max_faces = max(max_faces, len(detector(frame)))
        except Exception:
            pass
    cap.release()
    return max_faces


def download_google_font(url, dest):
    import urllib.request

    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as exc:
        print(f"      Font download failed ({os.path.basename(dest)}): {exc}")
    return dest


def register_fonts_for_libass(font_dir):
    return os.path.abspath(font_dir)


def siapkan_font_tipografi(cfg):
    """Ensure the active preset's two fonts exist locally."""
    info = cfg.daftar_font[cfg.gaya_font_aktif]
    for key in ("utama", "khusus"):
        item = info[key]
        download_google_font(item["url"], os.path.join(cfg.font_dir, item["file"]))
