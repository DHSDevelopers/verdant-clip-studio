"""Karaoke ASS subtitle generation (Hormozi / Veed style)."""

import os
import string

from .utils import _get_render_dims, _is_vertical_ratio


def _fmt_time(d: float) -> str:
    d = max(0.0, float(d))
    return f"{int(d // 3600)}:{int((d % 3600) // 60):02d}:{int(d % 60):02d}.{int((d - int(d)) * 100):02d}"


def buat_file_ass(
    data_segmen,
    start_clip,
    end_clip,
    nama_file_ass,
    rasio,
    cfg,
    typography_plan=None,
    gunakan_advanced=True,
    get_x_func=None,
    source_dim=None,
):
    """Write an ASS file with per-word highlight and optional kinetic emphasis."""
    typography_plan = typography_plan or []
    typo_dict = {}
    for plan in typography_plan:
        clean = str(plan.get("kata_utama", "")).lower().strip(string.punctuation)
        if clean:
            typo_dict[clean] = plan

    pakai_advanced = bool(getattr(cfg, "use_advanced_text", False)) and gunakan_advanced
    pakai_karaoke = bool(getattr(cfg, "use_karaoke_effect", True))

    outline_val = 3 if pakai_karaoke else 0.2
    shadow_val = 2.5 if pakai_karaoke else 0.2

    daftar_font = cfg.daftar_font
    gaya = cfg.gaya_font_aktif
    font_dir = cfg.font_dir
    font_utama = daftar_font[gaya]["utama"]["nama"]
    font_khusus = daftar_font[gaya]["khusus"]["nama"]

    scale_base_khusus = (
        cfg.scale_kata_khusus_916 if _is_vertical_ratio(rasio) else cfg.scale_kata_khusus_169
    )
    warna_khusus = cfg.warna_kata_khusus

    def get_scale_value(level):
        if level == 3:
            return scale_base_khusus
        if level == 2:
            return int((scale_base_khusus + 100) / 2)
        return 110

    play_res_x, play_res_y = _get_render_dims(
        cfg, rasio, source_h=source_dim[1] if source_dim else 1080
    )
    scale_factor = play_res_y / (1920 if _is_vertical_ratio(rasio) else 1080)
    align = cfg.ass_align_916 if _is_vertical_ratio(rasio) else cfg.ass_align_169
    margin_v = int(
        (cfg.ass_margin_916 if _is_vertical_ratio(rasio) else cfg.ass_margin_169) * scale_factor
    )
    font_sz = int(
        (cfg.ass_font_916 if _is_vertical_ratio(rasio) else cfg.ass_font_169) * scale_factor
    )
    margin_lr = int((60 if _is_vertical_ratio(rasio) else 40) * scale_factor)

    header = (
        "[Script Info]\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        "WrapStyle: 1\n"
        "ScriptType: v4.00+\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, "
        "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_utama},{font_sz},&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,"
        f"100,100,0,0,1,{outline_val},{shadow_val},{align},{margin_lr},{margin_lr},{margin_v},1\n"
        f"Style: Emphasis,{font_khusus},{font_sz},{warna_khusus},&H00000000,&H80000000,1,0,0,0,"
        f"100,100,0,0,1,{outline_val},{shadow_val},{align},{margin_lr},{margin_lr},{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    os.makedirs(os.path.dirname(os.path.abspath(nama_file_ass)), exist_ok=True)
    with open(nama_file_ass, "w", encoding="utf-8") as f:
        f.write(header)

        for seg in data_segmen:
            words = seg.get("words") or []
            if not words:
                continue
            # A segment may straddle the clip boundary; clip it.
            if seg["end"] <= start_clip or seg["start"] >= end_clip:
                continue

            for i, word in enumerate(words):
                w_s = max(0.0, word["start"] - start_clip)
                if i < len(words) - 1:
                    w_e = min(end_clip - start_clip, words[i + 1]["start"] - start_clip)
                else:
                    w_e = min(end_clip - start_clip, word["end"] - start_clip)
                w_s = min(w_s, end_clip - start_clip)
                if w_e <= w_s:
                    continue

                parts = []
                for j, other in enumerate(words):
                    text = other["word"]
                    plan = typo_dict.get(str(text).lower().strip(string.punctuation))
                    if pakai_karaoke:
                        if j == i:
                            parts.append(f"{{\\c&H00FFFF&}}{text}{{\\c&HFFFFFF&}}")
                        else:
                            parts.append(text)
                    elif j <= i:
                        parts.append(text)
                    else:
                        parts.append(f"{{\\alpha&HFF&}}{text}{{\\alpha&H00&}}")

                    if plan and pakai_advanced and get_scale_value(plan.get("scale_level", 1)) > 110:
                        scale = get_scale_value(plan.get("scale_level", 1)) / 100.0
                        style = "Emphasis" if plan.get("style") == "khusus" else "Default"
                        anim = plan.get("animasi", "bounce_pop")
                        effect = (
                            f"\\t(0,120,\\fscx{int(scale * 100)}\\fscy{int(scale * 100)})"
                            if anim == "bounce_pop"
                            else f"\\fscx{int(scale * 100)}\\fscy{int(scale * 100)}"
                        )
                        parts[-1] = f"{{\\style{style}{effect}}}{parts[-1]}"

                f.write(
                    f"Dialogue: 0,{_fmt_time(w_s)},{_fmt_time(w_e)},Default,,0,0,0,,"
                    f"{' '.join(parts)}\n"
                )
