"""AI voice-over commentary: script generation + edge-tts synthesis."""

import asyncio
import os

LENGTH_HINTS = {
    "short": "about 10 seconds, 2-3 sentences",
    "normal": "about 30 seconds, 5-7 sentences",
    "long": "about 50 seconds, 8-10 sentences",
}


def generate_commentary_script(snippet_text, cfg, style="analysis", language="en", length="short"):
    provider = getattr(cfg, "ai_provider", "gemini")
    language_name = "Indonesian" if language == "id" else "English"
    prompt = (
        "You are a short-form video commentator. Write a spoken commentary script "
        f"in {language_name} in a {style} style, {LENGTH_HINTS.get(length, LENGTH_HINTS['short'])}. "
        "No markdown, no stage directions, no speaker labels. Return plain text only.\n\n"
        f"Clip transcript:\n{snippet_text[:6000]}"
    )

    if provider == "vllm":
        from .providers.vllm import VllmProvider

        with VllmProvider.from_cfg(cfg) as local:
            return local.generate_text(prompt).strip()

    if not getattr(cfg, "api_key_gemini", ""):
        raise RuntimeError("GOOGLE_API_KEY is required for voice-over scripts.")

    import google.genai as genai

    client = genai.Client(api_key=cfg.api_key_gemini)
    response = client.models.generate_content(model=cfg.gemini_model, contents=prompt)
    return (getattr(response, "text", "") or "").strip()


def _synthesize(text: str, voice: str, output_path: str):
    import edge_tts

    async def _run():
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)

    asyncio.run(_run())


def synthesize_voice(script: str, voice: str, outputs_dir: str, rank: str):
    os.makedirs(outputs_dir, exist_ok=True)
    audio_path = os.path.join(outputs_dir, f"voiceover_rank_{rank}.mp3")
    _synthesize(script, voice, audio_path)
    # edge-tts has no word timings; estimate 2.6 words/second for karaoke.
    words = script.split()
    seconds_per_word = 1 / 2.6
    segments = []
    for i in range(0, len(words), 5):
        chunk = words[i:i + 5]
        start = i * seconds_per_word
        end = (i + len(chunk)) * seconds_per_word
        segments.append(
            {
                "start": start,
                "end": end,
                "words": [
                    {
                        "word": w,
                        "start": start + j * seconds_per_word,
                        "end": start + (j + 1) * seconds_per_word,
                    }
                    for j, w in enumerate(chunk)
                ],
            }
        )
    return audio_path, segments
