"""Local BGM pool with sidechain ducking or constant background mix."""

import os
import random


def get_local_bgm_file(mood: str, bgm_dir: str):
    folder = os.path.join(bgm_dir, mood)
    if not os.path.isdir(folder):
        return None
    files = [
        os.path.join(folder, f)
        for f in os.listdir(folder)
        if f.lower().endswith((".mp3", ".wav", ".m4a", ".aac"))
    ]
    return random.choice(files) if files else None


def build_bgm_filter(mode: str, base_volume: float, audio_input_voc="[0:a]", audio_input_bgm="[1:a]"):
    """Return a filter_complex fragment producing [a_out].

    ducking: sidechaincompress so the BGM drops under speech.
    background: constant low-volume mix.
    """
    vol = max(0.0, min(1.0, float(base_volume if base_volume is not None else 0.25)))
    if mode == "background":
        return (
            f"{audio_input_bgm}volume={vol}[bgm];"
            f"{audio_input_voc}[bgm]amix=inputs=2:duration=first:dropout_transition=2:"
            f"normalize=0[a_out]"
        )
    return (
        f"{audio_input_voc}asplit=2[voc_mix][voc_key];"
        f"{audio_input_bgm}volume={vol}[bgm];"
        f"[bgm][voc_key]sidechaincompress=threshold=0.045:ratio=9:attack=20:release=350"
        f":makeup=1[bgm_ducked];"
        f"[voc_mix][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=2:"
        f"normalize=0[a_out]"
    )
