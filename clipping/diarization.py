"""Speaker diarization for podcast modes (optional; requires HF_TOKEN)."""

import os
import subprocess


def extract_audio(video_path: str, audio_path: str) -> str:
    os.makedirs(os.path.dirname(os.path.abspath(audio_path)), exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "pcm_s16le", audio_path,
        ],
        check=True,
    )
    return audio_path


def run_diarization(audio_path, hf_token=None, num_speakers="auto", min_speakers=None, max_speakers=None):
    """Return [{"start", "end", "speaker"}] turns, or raise with a clear reason."""
    if not hf_token:
        raise RuntimeError("HF_TOKEN is required for pyannote diarization.")

    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1", use_auth_token=hf_token
    )
    try:
        import torch

        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
    except Exception:
        pass

    kwargs = {}
    if str(num_speakers).lower() != "auto":
        kwargs["num_speakers"] = int(num_speakers)
    else:
        if min_speakers:
            kwargs["min_speakers"] = int(min_speakers)
        if max_speakers:
            kwargs["max_speakers"] = int(max_speakers)

    annotation = pipeline(audio_path, **kwargs)
    turns = []
    for turn, _, speaker in annotation.itertracks(yield_label=True):
        turns.append({"start": float(turn.start), "end": float(turn.end), "speaker": speaker})
    if not turns:
        raise RuntimeError("Diarization produced no speaker turns.")
    return turns
