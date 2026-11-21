"""Clip JSON schemas shared by the providers.

The NVIDIA dialect is the canonical contract; the Gemini dialect keeps the
legacy field list used by the original pipeline.
"""

_GEMINI_FIELDS = [
    "rank", "viral_score", "hook_start_time", "hook_end_time",
    "start_time", "end_time", "typography_plan",
    "broll_list", "recommended_visual_broll_hook", "alasan", "bgm_mood",
    "title_indonesia", "title_inggris", "hastag",
    "description_hook", "description_context", "keyword_tags", "tiktok_title_id",
    "tiktok_caption_id", "tiktok_caption", "klasifikasi_akun", "hook_v2", "keep_segments",
]


def build_clips_schema(accounts: dict) -> dict:
    """Return the canonical JSON Schema used for guided/local generation."""
    return {
        "type": "array",
        "items": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "rank": {"type": "integer"},
                "viral_score": {"type": "integer"},
                "start_time": {"type": "number"},
                "end_time": {"type": "number"},
                "hook_start_time": {"type": "number"},
                "hook_end_time": {"type": "number"},
                "bgm_mood": {"type": "string", "enum": ["chill", "epic", "sad", "upbeat", "suspense"]},
                "typography_plan": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "kata_utama": {"type": "string"},
                            "scale_level": {"type": "integer"},
                            "style": {"type": "string"},
                            "animasi": {"type": "string"},
                        },
                        "required": ["kata_utama", "scale_level", "style", "animasi"],
                    },
                },
                "broll_list": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                            "search_query": {"type": "string"},
                        },
                        "required": ["start_time", "end_time", "search_query"],
                    },
                },
                "recommended_visual_broll_hook": {"type": "array"},
                "hook_v2": {"type": "object"},
                "keep_segments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "start_time": {"type": "number"},
                            "end_time": {"type": "number"},
                        },
                        "required": ["start_time", "end_time"],
                    },
                },
                "title_indonesia": {"type": "string"},
                "title_inggris": {"type": "string"},
                "hastag": {"type": "string"},
                "description_hook": {"type": "string"},
                "description_context": {"type": "string"},
                "keyword_tags": {"type": "array", "items": {"type": "string"}},
                "tiktok_title_id": {"type": "string"},
                "tiktok_caption_id": {"type": "string"},
                "tiktok_caption": {"type": "string"},
                "alasan": {"type": "string"},
                "klasifikasi_akun": {
                    "type": "object",
                    "properties": {
                        "tipe_akun": {"type": "string", "enum": list(accounts)},
                        "akun_tujuan": {"type": "string"},
                        "confidence": {"type": "integer"},
                        "angle_utama": {"type": "string"},
                        "alasan": {"type": "string"},
                        "kata_kunci_pendukung": {"type": "array", "items": {"type": "string"}},
                        "bio_akun": {"type": "string"},
                        "alternatif_akun": {"type": "object"},
                    },
                    "required": ["tipe_akun", "akun_tujuan", "confidence"],
                },
            },
            "required": _GEMINI_FIELDS,
        },
    }


def build_gemini_schema(accounts: dict) -> dict:
    """The legacy Gemini response schema (array of clips, same field list)."""
    return build_clips_schema(accounts)
