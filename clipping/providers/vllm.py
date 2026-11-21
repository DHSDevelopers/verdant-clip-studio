"""Self-hosted vLLM provider (OpenAI-compatible, JSON-schema constrained)."""

import json
import time

from .base import InvalidOutputError, ProviderConfigError
from .config import vllm_config_values
from .parsing import parse_clips
from .validation import transcript_end, validate_clips

MAX_ATTEMPTS = 3


class VllmProvider:
    name = "vllm"

    def __init__(self, values):
        self.model = values["vllm_model"]
        self.base_url = values["vllm_base_url"]
        self.api_key = values.get("api_key_vllm", "")
        self.max_tokens = values["local_max_tokens"]
        self.context_limit = values.get("vllm_context_limit")
        self.timeout = values["vllm_timeout"]
        self.deadline = None

    @classmethod
    def from_cfg(cls, cfg):
        return cls(vllm_config_values(vars(cfg)))

    def __enter__(self):
        self.deadline = time.monotonic() + self.timeout
        return self

    def __exit__(self, *exc):
        return False

    # ------------------------------------------------------------------ http
    def _request(self, method, path, payload=None):
        import httpx

        url = f"{self.base_url}{path}"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        remaining = max(1.0, (self.deadline or (time.monotonic() + self.timeout)) - time.monotonic())
        try:
            with httpx.Client(
                timeout=min(remaining, 60.0), follow_redirects=False, trust_env=False
            ) as client:
                response = client.request(method, url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise ProviderConfigError(f"Cannot reach the vLLM server at {url}: {exc}") from None
        if response.status_code == 401:
            raise ProviderConfigError("vLLM server rejected the configured API key.")
        if response.status_code == 404:
            raise ProviderConfigError(f"vLLM endpoint not found: {path}")
        if response.status_code >= 400:
            raise ProviderConfigError(
                f"vLLM returned HTTP {response.status_code}: {response.text[:300]}"
            )
        return response.json()

    def validate(self):
        models = self._request("GET", "/v1/models")
        available = [m.get("id") for m in models.get("data", [])]
        if self.model not in available:
            raise ProviderConfigError(
                f"vLLM model '{self.model}' is not served. Available: {available}"
            )

    def _token_count(self, messages):
        result = self._request("POST", "/tokenize", {"model": self.model, "messages": messages})
        tokens = result.get("count") or result.get("tokens")
        if isinstance(tokens, list):
            tokens = len(tokens)
        if not isinstance(tokens, int):
            raise ProviderConfigError("vLLM /tokenize returned no reliable token count.")
        return tokens

    # -------------------------------------------------------------- generate
    def generate_clips(
        self,
        prompt: str,
        schema: dict,
        *,
        transcript: str,
        requested_clips: int,
        min_duration: int,
        max_duration: int,
    ):
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a professional video editor and strategist. "
                    "Return JSON only, following the requested schema."
                ),
            },
            {"role": "user", "content": prompt},
        ]
        wrapped = {
            "type": "object",
            "properties": {"clips": schema},
            "required": ["clips"],
            "additionalProperties": False,
        }

        prompt_tokens = self._token_count(messages)
        if self.context_limit and prompt_tokens + self.max_tokens > self.context_limit:
            raise ProviderConfigError(
                f"Prompt needs {prompt_tokens + self.max_tokens} tokens but the configured "
                f"context limit is {self.context_limit}. Shorten the source video or raise "
                "the operator's context limit."
            )

        last_error = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = self._request(
                    "POST",
                    "/v1/chat/completions",
                    {
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.4,
                        "max_tokens": self.max_tokens,
                        "response_format": {
                            "type": "json_schema",
                            "json_schema": {
                                "name": "clips",
                                "schema": wrapped,
                                "strict": True,
                            },
                        },
                        "chat_template_kwargs": {"thinking": False},
                    },
                )
                choice = response["choices"][0]
                if choice.get("finish_reason") == "length":
                    raise ProviderConfigError(
                        "vLLM stopped at the output token limit; raise VLLM_MAX_TOKENS."
                    )
                clips = parse_clips(choice["message"]["content"], wrapped)
                validate_clips(
                    clips,
                    source_end=transcript_end(transcript),
                    requested_clips=requested_clips,
                    min_duration=min_duration,
                    max_duration=max_duration,
                )
                return clips
            except (InvalidOutputError, KeyError, TypeError) as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    break
                print(f"[vLLM] Attempt {attempt} returned invalid output: {exc}. Repairing...")
        raise InvalidOutputError(f"vLLM did not produce valid clips: {last_error}")

    def generate_text(self, prompt: str, system: str = "Return only the requested text.") -> str:
        response = self._request(
            "POST",
            "/v1/chat/completions",
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7,
                "max_tokens": min(self.max_tokens, 2048),
            },
        )
        return response["choices"][0]["message"]["content"]
