"""API schemas for jobs, clips, settings and health."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SourcePlatform(str, enum.Enum):
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    INSTAGRAM = "instagram"
    GDRIVE = "gdrive"


class AspectRatio(str, enum.Enum):
    RATIO_9_16 = "9:16"
    RATIO_16_9 = "16:9"
    RATIO_1_1 = "1:1"
    RATIO_3_4 = "3:4"
    RATIO_4_5 = "4:5"


class FontStyle(str, enum.Enum):
    DEFAULT = "DEFAULT"
    STORYTELLER = "STORYTELLER"
    HORMOZI = "HORMOZI"
    CINEMATIC = "CINEMATIC"


class FaceDetector(str, enum.Enum):
    MEDIAPIPE = "mediapipe"
    YOLO = "yolo"


class AIProvider(str, enum.Enum):
    GEMINI = "gemini"
    NVIDIA = "nvidia"
    VLLM = "vllm"


class WhisperDevice(str, enum.Enum):
    CUDA = "cuda"
    CPU = "cpu"
    AUTO = "auto"


class JobCreateRequest(BaseModel):
    """Payload to create a clipping job. Mirrors the CLI flag set."""

    # Source
    url: Optional[str] = Field(None, description="Video URL to process")
    upload_filename: Optional[str] = Field(None, description="Filename from /api/upload")
    source: SourcePlatform = Field(SourcePlatform.YOUTUBE)
    reuse_job_id: Optional[str] = Field(None, pattern=r"^[a-zA-Z0-9_-]{1,64}$")

    # Preset (new UI layer; every underlying value remains overridable)
    preset: Optional[str] = Field(None, max_length=64)

    # Main settings
    clips: int = Field(7, ge=1, le=30)
    ratio: AspectRatio = Field(AspectRatio.RATIO_9_16)
    source_height: str = Field("max")
    render_height: str = Field("1080")

    # Content & hook
    words_per_sub: int = Field(5, ge=1, le=15)
    hook_duration: int = Field(3, ge=1, le=10)
    use_broll: bool = True
    use_hook_glitch: bool = True
    use_auto_bgm: bool = True
    bgm_mode: str = Field("ducking", pattern=r"^(ducking|background)$")
    use_karaoke_effect: bool = True
    use_split_screen: bool = False
    use_camera_switch: bool = False
    split_trigger: str = Field("diarization", pattern=r"^(diarization|face)$")
    diarization_speakers: str = "auto"
    switch_hold_duration: float = Field(2.0, ge=0, le=30)
    no_subs: bool = False
    no_segment_trim: bool = False
    silence_trim: bool = False

    # Hook V2
    hook_v2: bool = False
    hook_v2_items: int = Field(3, ge=2, le=6)
    white_flash_duration: float = Field(0.12, ge=0.02, le=1.0)

    # Subtitle & typography
    font_style: FontStyle = FontStyle.HORMOZI

    # Whisper
    whisper_model: str = "large-v3"
    whisper_device: WhisperDevice = WhisperDevice.CUDA
    whisper_compute_type: str = "float16"
    use_dlp_subs: bool = False

    # AI
    ai_provider: AIProvider = AIProvider.GEMINI
    gemini_model: str = "gemini-3-flash-preview"
    nvidia_model: str = "deepseek-ai/deepseek-v4-pro"
    vllm_model: Optional[str] = Field(None, min_length=1, max_length=256)
    local_max_tokens: Optional[int] = Field(None, ge=1, le=131072)
    face_detector: FaceDetector = FaceDetector.MEDIAPIPE
    load_gemini_json: bool = False

    # Encode
    video_crf: int = Field(20, ge=0, le=51)
    video_cq: int = Field(23, ge=0, le=51)
    video_bitrate: str = "auto"
    video_sharpen: bool = False
    video_preset: str = "auto"
    video_scale_algo: str = Field("lanczos", pattern=r"^(lanczos|bicubic|bilinear|area)$")
    static_crop: bool = False

    # Voice-over
    voiceover: bool = False
    voiceover_voice: str = "en-GB-MaisieNeural"
    voiceover_lang: str = Field("en", pattern=r"^(id|en)$")
    voiceover_style: str = Field("analysis", pattern=r"^(analysis|reaction|lesson|summary)$")
    voiceover_length: str = Field("short", pattern=r"^(short|normal|long)$")
    voiceover_volume: float = Field(1.0, ge=0, le=3)
    edge_glow: bool = False

    # Watermark
    watermark: bool = False
    text: Optional[str] = None
    image: Optional[str] = None
    opacity: int = Field(70, ge=1, le=100)
    position: str = Field(
        "center-right",
        pattern=r"^(top|center|bottom)-(left|center|right)$",
    )
    padding: int = Field(0, ge=0)
    watermark_font_size: int = Field(0, ge=0)
    watermark_scale: int = Field(15, ge=1, le=100)

    # Batch output naming
    output_naming: Optional[str] = Field(None, max_length=120)

    @field_validator("upload_filename")
    @classmethod
    def validate_upload_filename(cls, value):
        if value is not None and (
            not value or value in {".", ".."} or any(ch in value for ch in "/\\:\x00")
        ):
            raise ValueError("upload_filename must be a filename, not a path")
        return value

    @field_validator("diarization_speakers")
    @classmethod
    def validate_speakers(cls, value):
        if str(value).lower() == "auto":
            return "auto"
        if not str(value).isdigit():
            raise ValueError("diarization_speakers must be 'auto' or an integer")
        return str(value)

    @field_validator("source_height")
    @classmethod
    def validate_source_height(cls, value):
        if value == "max" or (str(value).isdigit() and int(value) > 0):
            return value
        raise ValueError("source_height must be 'max' or a positive integer")

    @field_validator("render_height")
    @classmethod
    def validate_render_height(cls, value):
        if value == "source" or (str(value).isdigit() and int(value) > 0):
            return value
        raise ValueError("render_height must be 'source' or a positive integer")


class JobProgressEvent(BaseModel):
    step: str
    step_number: int
    total_steps: int
    message: str
    percent: float = 0.0
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClipDetail(BaseModel):
    rank: int
    viral_score: Optional[int] = None
    title: Optional[str] = None
    title_en: Optional[str] = None
    filename: str
    duration: Optional[float] = None
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    download_url: str
    thumbnail_url: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    url: Optional[str] = None
    upload_filename: Optional[str] = None
    source: SourcePlatform = SourcePlatform.YOUTUBE
    config: dict = Field(default_factory=dict)
    progress: Optional[JobProgressEvent] = None
    clips: list[ClipDetail] = Field(default_factory=list)
    error: Optional[str] = None
    cancel_requested: bool = False
    log: list[str] = Field(default_factory=list)


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int


class SettingsRequest(BaseModel):
    google_api_key: Optional[str] = None
    pexels_api_key: Optional[str] = None
    hf_token: Optional[str] = None
    nvidia_api_key: Optional[str] = None
    default_clips: Optional[int] = None
    default_ratio: Optional[AspectRatio] = None
    default_font_style: Optional[FontStyle] = None
    default_whisper_model: Optional[str] = None
    default_whisper_device: Optional[WhisperDevice] = None
    default_ai_provider: Optional[AIProvider] = None


class SettingsResponse(BaseModel):
    google_api_key_set: bool = False
    pexels_api_key_set: bool = False
    hf_token_set: bool = False
    nvidia_api_key_set: bool = False
    vllm_api_key_set: bool = False
    vllm_model: str = ""
    local_max_tokens: int = 4096
    default_clips: int = 7
    default_ratio: str = "9:16"
    default_font_style: str = "HORMOZI"
    default_whisper_model: str = "large-v3"
    default_whisper_device: str = "cuda"
    default_ai_provider: str = "gemini"
    gpu_available: bool = False


class SystemHealthResponse(BaseModel):
    status: str = "ok"
    version: str
    gpu_available: bool
    ffmpeg_available: bool
    jobs_running: int
    jobs_queued: int
