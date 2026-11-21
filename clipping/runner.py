"""clipping.runner — pipeline orchestrator.

1 download  2 transcribe  3 AI analysis  4 metadata  5 diarization
6 encoder/glitch preparation  7 render + manifest.
"""

import glob
import json
import os

from . import engine, hook_manager, metadata, studio, voiceover
from . import diarization as diarization_mod


def run_pipeline(cfg, whisper_model_instance=None) -> list[dict]:
    from .providers.metadata import save_run_metadata
    from .providers.validation import validate_analysis_config

    validate_analysis_config(cfg, probe=getattr(cfg, "ai_provider", "gemini") == "vllm")

    # Step 1 — download
    source_platform = getattr(cfg, "source_platform", "youtube")
    if getattr(cfg, "upload_filename", None) and os.path.exists(cfg.file_video_asli):
        print("[1/3] Using the uploaded source video.")
    elif getattr(cfg, "skip_download", False) and os.path.exists(cfg.file_video_asli):
        print("[1/3] Reusing the existing source video.")
    else:
        engine.download_video(
            cfg.url_youtube,
            cfg.file_video_asli,
            getattr(cfg, "use_dlp_subs", False),
            getattr(cfg, "download_source_height", "max"),
            source_platform=source_platform,
            yt_cookies=getattr(cfg, "yt_cookies", None),
        )

    # Step 2 — transcript
    transkrip_lengkap = ""
    data_segmen = []
    json3_files = glob.glob(cfg.file_video_asli.replace(".mp4", ".*.json3"))
    file_json3 = json3_files[0] if json3_files else None

    if (
        source_platform == "youtube"
        and getattr(cfg, "use_dlp_subs", False)
        and file_json3
        and os.path.exists(file_json3)
    ):
        transkrip_lengkap, data_segmen = engine.parse_youtube_json3_subs(
            file_json3, max_words_per_subtitle=cfg.max_kata_per_subtitle
        )
        if transkrip_lengkap and data_segmen:
            print(f"Using YouTube subtitles ({os.path.basename(file_json3)}); Whisper skipped.")

    if not transkrip_lengkap or not data_segmen:
        transkrip_lengkap, data_segmen = engine.transcribe_video(
            cfg.file_video_asli,
            max_words_per_subtitle=cfg.max_kata_per_subtitle,
            model_size=cfg.whisper_model,
            device=cfg.whisper_device,
            compute_type=cfg.whisper_compute_type,
            whisper_model_instance=whisper_model_instance,
        )

    # Step 3 — AI analysis
    gemini_output_path = os.path.join(cfg.outputs_dir, "gemini_response.json")
    if getattr(cfg, "load_gemini_json", False) and os.path.exists(gemini_output_path):
        print(f"\n[3/3] Loading cached AI output: {gemini_output_path}")
        with open(gemini_output_path, "r", encoding="utf-8") as f:
            hasil_json = json.load(f)
        save_run_metadata(cfg, cached=True)
    else:
        try:
            hasil_json = engine.analyze_with_ai(transkrip_lengkap, cfg)
        except Exception:
            if getattr(cfg, "ai_run_meta", None):
                try:
                    save_run_metadata(cfg)
                except (OSError, TypeError, ValueError):
                    print("[AI] Failure metadata could not be written.")
            raise
        with open(gemini_output_path, "w", encoding="utf-8") as f:
            json.dump(hasil_json, f, indent=4, ensure_ascii=False)
        print(f"Raw AI response saved to: {gemini_output_path}")
        save_run_metadata(cfg)

    # Step 4 — metadata normalization
    hasil_json = metadata.normalize_and_validate(hasil_json)
    metadata.print_preview(hasil_json)
    metadata.save_metadata_preview(
        hasil_json, path=os.path.join(cfg.outputs_dir, "metadata_preview.json")
    )

    # Step 5 — diarization (podcast modes)
    diarization_data = None
    if (
        (getattr(cfg, "use_split_screen", False) and cfg.split_trigger == "diarization")
        or getattr(cfg, "use_camera_switch", False)
    ) and studio._is_vertical_ratio(cfg.pilihan_rasio):
        try:
            print("\n[5/7] Running speaker diarization...")
            audio_path = cfg.file_video_asli.replace(".mp4", "_audio.wav")
            diarization_mod.extract_audio(cfg.file_video_asli, audio_path)
            num_speakers_arg = getattr(cfg, "diarization_num_speakers", 2)
            min_spk = max_spk = None
            if str(num_speakers_arg).lower() == "auto":
                max_faces = studio.estimate_speaker_count_from_video(cfg.file_video_asli, cfg)
                min_spk = max(1, max_faces)
                max_spk = min_spk + 2
                print(f"   Pyannote bounds: {min_spk} to {max_spk} speakers.")
            diarization_data = diarization_mod.run_diarization(
                audio_path,
                hf_token=cfg.hf_token,
                num_speakers=num_speakers_arg,
                min_speakers=min_spk,
                max_speakers=max_spk,
            )
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except Exception as exc:
            print(f"Diarization failed: {exc}")
            print("   Falling back to standard framing.")
            diarization_data = None

    # Step 6 — encoder + glitch
    os.environ["OSC_VIDEO_SCALE_ALGO"] = str(getattr(cfg, "video_scale_algo", "lanczos"))
    import cv2

    cap = cv2.VideoCapture(cfg.file_video_asli)
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    _w, target_h = studio._get_render_dims(cfg, cfg.pilihan_rasio, source_h=src_h)
    video_encoder = studio.detect_video_encoder(cfg, target_h=target_h)

    file_glitch_ts = None
    if cfg.use_hook_glitch:
        print("Preparing the glitch transition...")
        file_glitch_ts = studio.siapkan_glitch_video(
            cfg.pilihan_rasio, cfg, video_encoder, source_h=src_h
        )

    # Step 6b — custom hook + voice-over
    custom_hook_path = None
    if getattr(cfg, "hook_source", None):
        print("\nResolving the custom hook source...")
        custom_hook_path = hook_manager.download_custom_hook(cfg)

    if getattr(cfg, "voiceover", False):
        print(f"\nGenerating voice-over for {len(hasil_json)} clips...")
        for klip in hasil_json:
            try:
                start, end = float(klip["start_time"]), float(klip["end_time"])
                snippet = []
                for seg in data_segmen:
                    if float(seg["end"]) > start and float(seg["start"]) < end:
                        text = seg.get("text") or " ".join(w["word"] for w in seg.get("words", []))
                        if text:
                            snippet.append(text)
                script = voiceover.generate_commentary_script(
                    " ".join(snippet),
                    cfg,
                    style=cfg.voiceover_style,
                    language=cfg.voiceover_lang,
                    length=cfg.voiceover_length,
                )
                if script:
                    audio_path, segments = voiceover.synthesize_voice(
                        script, cfg.voiceover_voice, cfg.outputs_dir, str(klip["rank"])
                    )
                    if os.path.exists(audio_path):
                        klip["voiceover"] = {
                            "script": script,
                            "audio_path": audio_path,
                            "segments": segments,
                            "voice": cfg.voiceover_voice,
                        }
            except Exception as exc:
                print(f"   Voice-over failed for Rank {klip['rank']}: {exc}")

    # Step 7 — render
    render_manifest: list[dict] = []
    for klip in sorted(hasil_json, key=lambda x: x["rank"]):
        if custom_hook_path:
            klip["custom_hook_info"] = {"file_path": custom_hook_path}
        result = studio.proses_klip(
            klip["rank"],
            klip,
            cfg.pilihan_rasio,
            file_glitch_ts,
            data_segmen,
            cfg,
            video_encoder,
            diarization_data=diarization_data,
        )
        if result:
            render_manifest.append(result)

    for row in render_manifest:
        if not row.get("source_url"):
            row["source_url"] = getattr(cfg, "url_youtube", None)

    manifest_path = os.path.join(cfg.outputs_dir, "render_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(render_manifest, f, ensure_ascii=False, indent=2)
    print(f"\nRender manifest saved to {manifest_path} ({len(render_manifest)} items)")
    return render_manifest
