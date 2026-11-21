"""NVIDIA NIM transport; request fields and parsing match the reference."""

import json
import re


class NvidiaNimProvider:
    name = "nvidia"

    def __init__(self, cfg):
        self.cfg = cfg

    @classmethod
    def from_cfg(cls, cfg):
        return cls(cfg)

    def generate_clips(self, prompt: str, schema: dict) -> list[dict]:
        cfg = self.cfg
        from openai import OpenAI

        print(
            f"[3/3] Analyzing the top {cfg.jumlah_clip} moments with NVIDIA ({cfg.nvidia_model})..."
        )
        if not cfg.api_key_nvidia:
            raise ValueError("NVIDIA_API_KEY is not set in the environment.")

        client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=cfg.api_key_nvidia,
        )
        completion = client.chat.completions.create(
            model=cfg.nvidia_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a professional video editor and strategist. "
                        "Return JSON only. Follow the provided JSON schema exactly."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.5,
            top_p=1,
            max_tokens=16384,
            extra_body={
                "chat_template_kwargs": {"thinking": False},
                "nvext": {"guided_json": schema},
            },
        )
        content = completion.choices[0].message.content
        if not content:
            raise ValueError("NVIDIA returned an empty completion.")

        if "```" in content:
            content = re.sub(r"```(json)?", "", content).strip()
            content = content.split("```")[0].strip()

        hasil = json.loads(content)
        if isinstance(hasil, dict):
            for key in ["clips", "data", "highlights"]:
                if key in hasil and isinstance(hasil[key], list):
                    hasil = hasil[key]
                    break
        if not isinstance(hasil, list):
            if isinstance(hasil, dict):
                return [hasil]
            raise ValueError(f"NVIDIA returned a non-list/dict payload: {type(hasil)}")
        return hasil
