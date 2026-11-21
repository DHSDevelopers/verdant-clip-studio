"""
clipping.metadata — metadata normalization and QA preview.

Maps the AI output to the final platform fields (YouTube / TikTok, EN + ID),
adds warnings, sorts by viral score and reassigns sequential ranks.
"""

import json


def _normalize_spaces(text):
    return " ".join(str(text or "").split()).strip()


def _trim_title(text, max_len=100):
    text = _normalize_spaces(text)
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].strip()
    return cut if cut else text[:max_len].strip()


def _normalize_hashtags(text, min_tags=2, max_tags=3):
    parts = _normalize_spaces(text).split()
    clean, seen = [], set()
    for p in parts:
        if not p:
            continue
        if not p.startswith("#"):
            p = "#" + p.lstrip("#")
        key = p.lower()
        if key not in seen:
            seen.add(key)
            clean.append(p)
        if len(clean) >= max_tags:
            break
    return " ".join(clean), len(clean)


def _normalize_keyword_tags(tags, min_items=5, max_items=8):
    if not isinstance(tags, list):
        tags = []
    out, seen = [], set()
    for t in tags:
        x = _normalize_spaces(t)
        if not x:
            continue
        key = x.lower()
        if key not in seen:
            seen.add(key)
            out.append(x)
        if len(out) >= max_items:
            break
    return out


def _build_youtube_description(hook, context, hashtags, source_url=None):
    parts = [_normalize_spaces(hook), _normalize_spaces(context), _normalize_spaces(hashtags)]
    desc = "\n\n".join([p for p in parts if p]).strip()
    if source_url:
        desc += f"\n\nSource: {source_url}"
    return desc


def _build_tiktok_caption(caption, hashtags):
    caption = _normalize_spaces(caption)
    hashtags = _normalize_spaces(hashtags)
    if caption and hashtags:
        return f"{caption}\n{hashtags}"
    return caption or hashtags


def _looks_indonesian(text):
    text = f" {_normalize_spaces(text).lower()} "
    indikator = [
        " yang ", " dan ", " untuk ", " dengan ", " karena ", " adalah ",
        " bisa ", " tidak ", " lebih ", " dalam ", " pada ", " agar ",
        " dari ", " ini ", " itu ", " juga ", " kalau ", " saat ",
        " tentang ", " bikin ", " banget ", " jadi ", " sudah ",
    ]
    return any(w in text for w in indikator)


def normalize_and_validate(hasil_json: list[dict], *, report: list[dict] | None = None) -> list[dict]:
    valid_items = []
    laporan = []
    for item in hasil_json:
        if not isinstance(item, dict):
            print(f"Skipping invalid metadata item (not a dict): {type(item)}")
            continue

        # Flatten models that nest everything under "metadata".
        if isinstance(item.get("metadata"), dict):
            for k, v in item["metadata"].items():
                if k not in item:
                    item[k] = v

        item["rank"] = item.get("rank") or item.get("peringkat") or item.get("no") or "?"
        item["viral_score"] = item.get("viral_score", 0)

        it_st = (
            item.get("start_time")
            or item.get("timing_klip_start")
            or item.get("clip_start")
            or item.get("start")
        )
        it_en = (
            item.get("end_time")
            or item.get("timing_klip_end")
            or item.get("clip_end")
            or item.get("end")
        )
        item["start_time"] = float(it_st) if it_st is not None else 0.0
        item["end_time"] = float(it_en) if it_en is not None else 0.0

        if isinstance(item.get("hook"), str) and "hook_start_time" in item:
            item["hook"] = {
                "text": item["hook"],
                "start_time": item.get("hook_start_time", item["start_time"]),
                "end_time": item.get("hook_end_time", item["end_time"]),
            }
        if not isinstance(item.get("hook"), dict):
            item["hook"] = {
                "text": str(item.get("hook", "")),
                "start_time": item["start_time"],
                "end_time": item["start_time"] + 3.0,
            }

        item["title_indonesia"] = _trim_title(item.get("title_indonesia", ""))
        item["title_inggris"] = _trim_title(item.get("title_inggris", ""))
        item["description_hook"] = _normalize_spaces(item.get("description_hook", ""))
        item["description_context"] = _normalize_spaces(item.get("description_context", ""))
        item["hastag"] = _normalize_spaces(item.get("hastag") or item.get("hashtag") or "")
        item["tiktok_title_id"] = _normalize_spaces(item.get("tiktok_title_id", ""))
        item["tiktok_caption_id"] = _normalize_spaces(item.get("tiktok_caption_id", ""))
        item["tiktok_caption"] = _normalize_spaces(item.get("tiktok_caption", ""))
        item["keyword_tags"] = _normalize_keyword_tags(item.get("keyword_tags", []))

        item["hastag"], hashtag_count = _normalize_hashtags(item["hastag"])

        item["youtube_title_final"] = item["title_inggris"]
        item["youtube_description_final"] = _build_youtube_description(
            item.get("description_hook", ""),
            item.get("description_context", ""),
            item.get("hastag", ""),
            source_url=item.get("source_url"),
        )
        item["youtube_tags_final"] = item.get("keyword_tags", [])
        item["tiktok_caption_final"] = _build_tiktok_caption(
            item.get("tiktok_caption", ""), item.get("hastag", "")
        )
        item["tiktok_title_id_final"] = (
            item.get("tiktok_title_id", "") or item.get("title_indonesia", "")
        )
        item["tiktok_caption_id_final"] = _build_tiktok_caption(
            item.get("tiktok_caption_id", ""), item.get("hastag", "")
        )

        warning = []
        if not item["title_indonesia"]:
            warning.append("title_indonesia empty")
        if len(item["title_indonesia"]) > 100:
            warning.append("title_indonesia > 100 chars")
        if not item["title_inggris"]:
            warning.append("title_inggris empty")
        if len(item["title_inggris"]) > 100:
            warning.append("title_inggris > 100 chars")
        if hashtag_count < 2 or hashtag_count > 3:
            warning.append("hashtag count is not 2-3")
        if not item["description_hook"]:
            warning.append("description_hook empty")
        if not item["description_context"]:
            warning.append("description_context empty")
        if len(item["keyword_tags"]) < 5:
            warning.append("too few keyword_tags")
        if not item["tiktok_title_id"]:
            warning.append("tiktok_title_id empty")
        if not item["tiktok_caption_id"]:
            warning.append("tiktok_caption_id empty")
        if not item["tiktok_caption"]:
            warning.append("tiktok_caption empty")
        if len(item.get("youtube_description_final", "")) < 30:
            warning.append("youtube description shorter than 30 chars")
        if _looks_indonesian(item["title_inggris"]):
            warning.append("title_inggris does not look English")
        if _looks_indonesian(item["description_hook"]):
            warning.append("description_hook does not look English")
        if _looks_indonesian(item["description_context"]):
            warning.append("description_context does not look English")
        if _looks_indonesian(item["tiktok_caption"]):
            warning.append("tiktok_caption does not look English")
        if item["tiktok_title_id"] and not _looks_indonesian(item["tiktok_title_id"]):
            warning.append("tiktok_title_id does not look Indonesian")
        if item["tiktok_caption_id"] and not _looks_indonesian(item["tiktok_caption_id"]):
            warning.append("tiktok_caption_id does not look Indonesian")

        item["_warnings_temp"] = " | ".join(warning) if warning else "OK"
        valid_items.append(item)

    valid_items = sorted(valid_items, key=lambda x: x.get("viral_score", 0), reverse=True)
    for idx, item in enumerate(valid_items):
        item["rank"] = idx + 1
        klasifikasi = item.get("klasifikasi_akun", {}) or {}
        laporan.append(
            {
                "rank": item["rank"],
                "viral_score": item.get("viral_score", 0),
                "durasi": round(float(item.get("end_time", 0)) - float(item.get("start_time", 0)), 2),
                "akun_tujuan": klasifikasi.get("akun_tujuan", ""),
                "title_indonesia": item["title_indonesia"],
                "title_inggris": item["title_inggris"],
                "tiktok_title_id": item["tiktok_title_id"],
                "hashtags": item["hastag"],
                "warnings": item.pop("_warnings_temp", "OK"),
            }
        )

    if report is not None:
        report.extend(laporan)
    return valid_items


def print_preview(hasil_json: list[dict]) -> None:
    print("Metadata preview ready.")
    print("Generated fields: youtube_title_final, youtube_description_final, youtube_tags_final,")
    print("tiktok_caption_final, tiktok_title_id_final, tiktok_caption_id_final")
    for item in hasil_json:
        print(f"\n--- Rank {item['rank']} (Viral Score: {item.get('viral_score', '?')}) ---")
        print(f"Title EN  : {item['title_inggris']}")
        print(f"Title ID  : {item['title_indonesia']}")
        print(f"Hashtags  : {item['hastag']}")


def save_metadata_preview(hasil_json: list[dict], path: str = "metadata_preview.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(hasil_json, f, ensure_ascii=False, indent=2)
    print(f"Saved to {path}")
