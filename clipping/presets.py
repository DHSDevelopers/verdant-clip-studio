"""Creator workflow presets.

Each preset only sets parameters the backend already accepts; every value
remains editable in Studio, and the CLI exposes the same knobs as flags.
"""

PRESETS = [
    {
        "id": "gaming_highlights",
        "name": "Gaming Highlights",
        "tagline": "Fast cuts, punchy hooks, dense captions.",
        "accent": "#34F5A8",
        "settings": {
            "clips": 8,
            "ratio": "9:16",
            "words_per_sub": 4,
            "hook_duration": 2,
            "hook_v2": True,
            "hook_v2_items": 4,
            "white_flash_duration": 0.1,
            "use_broll": False,
            "use_auto_bgm": True,
            "bgm_mode": "ducking",
            "use_karaoke_effect": True,
            "font_style": "HORMOZI",
            "video_crf": 18,
            "video_cq": 20,
            "silence_trim": True,
            "output_naming": "highlight_rank_{rank}_ready.mp4",
        },
    },
    {
        "id": "action_moments",
        "name": "Action Moments",
        "tagline": "Hard hooks, glitch transitions, high bitrate.",
        "accent": "#52FFA8",
        "settings": {
            "clips": 6,
            "ratio": "9:16",
            "words_per_sub": 3,
            "hook_duration": 2,
            "hook_v2": False,
            "use_broll": True,
            "use_auto_bgm": True,
            "bgm_mode": "ducking",
            "font_style": "CINEMATIC",
            "video_crf": 17,
            "video_cq": 19,
            "video_preset": "slow",
            "silence_trim": True,
            "output_naming": "moment_{rank}_{date}.mp4",
        },
    },
    {
        "id": "podcast_clips",
        "name": "Podcast / Commentary",
        "tagline": "Longer context, speaker logic, softer captions.",
        "accent": "#B8FFE3",
        "settings": {
            "clips": 5,
            "ratio": "9:16",
            "words_per_sub": 7,
            "hook_duration": 4,
            "use_broll": False,
            "use_auto_bgm": True,
            "bgm_mode": "background",
            "use_karaoke_effect": True,
            "font_style": "STORYTELLER",
            "camera_switch": True,
            "diarization_speakers": "auto",
            "switch_hold_duration": 2.0,
            "silence_trim": False,
            "output_naming": "podcast_{rank}_{date}.mp4",
        },
    },
    {
        "id": "vertical_shorts",
        "name": "Vertical Reels / Shorts",
        "tagline": "Batch-ready 9:16 exports with clean naming.",
        "accent": "#34F5A8",
        "settings": {
            "clips": 10,
            "ratio": "9:16",
            "words_per_sub": 4,
            "hook_duration": 3,
            "hook_v2": True,
            "hook_v2_items": 3,
            "use_broll": True,
            "use_auto_bgm": True,
            "bgm_mode": "ducking",
            "use_karaoke_effect": True,
            "font_style": "HORMOZI",
            "render_height": "1080",
            "output_naming": "reel_{rank}_{slug}_{date}.mp4",
        },
    },
]

PRESET_BY_ID = {p["id"]: p for p in PRESETS}


def apply_preset(payload: dict, preset_id: str) -> dict:
    preset = PRESET_BY_ID.get(preset_id)
    if not preset:
        raise ValueError(f"Unknown preset: {preset_id}")
    merged = dict(payload)
    merged.update(preset["settings"])
    merged["preset"] = preset_id
    return merged
