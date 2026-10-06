import math
from typing import Annotated, Literal
from urllib.parse import urlsplit
from pydantic import BaseModel, Field, field_validator, model_validator

class LoginInput(BaseModel):
    username: str = Field(min_length=1)
    password: str = Field(min_length=1)

class SetupInput(LoginInput):
    setup_token: str

class UserInput(LoginInput):
    role: Literal["admin", "user"] = "user"

class UserPatch(BaseModel):
    active: bool | None = None
    role: Literal["admin", "user"] | None = None
    password: str | None = Field(default=None, min_length=1)

class ModelInput(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["vision", "image", "video", "transcription"]
    protocol: Literal["openai", "anthropic", "volcengine"]
    base_url: str = Field(max_length=1000)
    model_id: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=4096)
    enabled: bool = True
    max_duration: int = Field(default=15, ge=4, le=15)
    price_per_second: float = Field(default=0, ge=0, le=1000, allow_inf_nan=False)

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        u = urlsplit(value.strip())
        if u.scheme not in {"http", "https"} or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("填写带 http(s) 的 API 基础地址，不包含密钥、查询参数")
        return value.strip().rstrip("/")

    @model_validator(mode="after")
    def compatible(self):
        if self.kind == "video" and self.protocol != "volcengine":
            raise ValueError("Seedance 视频需选择火山方舟协议；中转站必须兼容其任务 API")
        if self.kind == "image" and self.protocol == "anthropic":
            raise ValueError("Anthropic Messages 不提供图片生成功能")
        if self.kind == "transcription" and self.protocol != "openai":
            raise ValueError("语音转写目前支持 OpenAI 兼容音频转写接口")
        return self

class StorageInput(BaseModel):
    enabled: bool = False
    endpoint: str = Field(default="", max_length=300)
    region: str = Field(default="cn-beijing", max_length=100)
    bucket: str = Field(default="", max_length=100)
    access_key_id: str = Field(default="", max_length=300)
    secret_access_key: str = Field(default="", max_length=1000)
    url_ttl: int = Field(default=86400, ge=3600, le=604800)

    @model_validator(mode="after")
    def required_fields(self):
        if self.enabled and not all([self.endpoint, self.region, self.bucket, self.access_key_id]):
            raise ValueError("启用 TOS 需要完整填写 endpoint、region、bucket 和 AK")
        if self.endpoint:
            u = urlsplit(self.endpoint if "://" in self.endpoint else "https://" + self.endpoint)
            if u.scheme != "https" or not u.hostname or u.path not in {"", "/"} or u.username or u.query or u.fragment:
                raise ValueError("TOS endpoint 需为 HTTPS 主机地址")
        return self

class Options(BaseModel):
    site: Literal["BR", "original"] = "BR"
    level: Literal["inspired", "balanced", "faithful", "strict"] = "balanced"
    replicate_music: bool = True
    replicate_voice: bool = True
    reference_audio: bool = True
    replicate_subtitles: bool = True
    duration: float | None = Field(default=None, ge=4, le=300, allow_inf_nan=False)
    ratio: Literal["9:16", "16:9", "1:1", "4:3", "3:4"] = "9:16"
    resolution: Literal["480p", "720p", "1080p"] = "720p"

class ProjectInput(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    product_description: str = Field(default="", max_length=12000)
    options: Options = Field(default_factory=Options)
    vision_model_id: str
    video_model_id: str
    image_model_id: str | None = None
    transcription_model_id: str | None = None

class AudioOptionsInput(BaseModel):
    replicate_music: bool
    replicate_voice: bool
    reference_audio: bool

ReferenceImageIndex = Annotated[int, Field(ge=0, le=7)]
NonnegativeTime = Annotated[float, Field(ge=0, allow_inf_nan=False)]
GenerationStrategy = Literal["direct", "keyframe", "adapt", "needs_reference"]

class ProductProfile(BaseModel):
    features: list[str] = Field(default_factory=list)
    parts: list[str] = Field(default_factory=list)
    known_views: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    forbidden_traits: list[str] = Field(default_factory=list)

class ShotPlan(BaseModel):
    model_config = {"extra": "allow"}
    start: NonnegativeTime = 0
    end: NonnegativeTime = 0
    description: str = ""
    adaptation: str = ""
    product_visibility: Literal["full", "partial", "background", "occluded", "absent", "uncertain"] = "uncertain"
    visible_parts: list[str] = Field(default_factory=list)
    missing_views: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    interaction: str = ""
    strategy: GenerationStrategy = "direct"
    reference_image_indices: list[ReferenceImageIndex] = Field(default_factory=list)

    @model_validator(mode="after")
    def ordered_times(self):
        if self.end < self.start:
            raise ValueError("镜头结束时间不能早于开始时间")
        return self

class QualityIssue(BaseModel):
    time: NonnegativeTime
    category: Literal["original_product", "mixed_identity", "geometry", "action", "text", "uncertain"]
    severity: Literal["warning", "error"] = "warning"
    description: str
    suggestion: str = ""

class QualityReport(BaseModel):
    status: Literal["pass", "issues", "uncertain"]
    summary: str = ""
    issues: list[QualityIssue] = Field(default_factory=list)
    sampled_times: list[NonnegativeTime] = Field(default_factory=list)

class SegmentRepairInput(BaseModel):
    strategy: Literal["direct", "keyframe", "adapt"]
    repair_prompt: str = Field(min_length=1, max_length=6000)

    @field_validator("repair_prompt")
    @classmethod
    def nonblank_prompt(cls, value):
        if not value.strip():
            raise ValueError("请说明此次修复需要解决的问题")
        return value

class PlanSegment(BaseModel):
    index: int = Field(ge=0)
    start: float = Field(ge=0, allow_inf_nan=False)
    duration: float = Field(gt=0, le=15, allow_inf_nan=False)
    generation_duration: int = Field(default=4, ge=4, le=15)
    prompt: str = Field(min_length=1, max_length=12000)
    voiceover: str = Field(default="", max_length=2000)
    subtitle: str = Field(default="", max_length=2000)
    risk: str = Field(default="", max_length=2000)
    strategy: GenerationStrategy = "direct"
    shot_indices: list[Annotated[int, Field(ge=0)]] = Field(default_factory=list)
    reference_image_indices: list[ReferenceImageIndex] = Field(default_factory=list)
    repair_prompt: str = Field(default="", max_length=6000)

class AnalysisPlan(BaseModel):
    summary: str = Field(default="", max_length=16000)
    product_identity: str = Field(default="", max_length=16000)
    risks: list[str] = Field(default_factory=list, max_length=100)
    product_profile: ProductProfile = Field(default_factory=ProductProfile)
    sampling: dict = Field(default_factory=dict)
    shots: list[ShotPlan] = Field(default_factory=list, max_length=200)
    segments: list[PlanSegment] = Field(min_length=1, max_length=80)
    transcript: str = Field(default="", max_length=60000)
    image_assessment: str = Field(default="", max_length=10000)
    estimated_cost: float | None = None
    estimated_cost_note: str = "仅为管理员配置的输出秒单价估算，不含参考视频输入、分析、修图和重试费用"

    @model_validator(mode="after")
    def timeline(self):
        end = 0.0
        for i, seg in enumerate(self.segments):
            if seg.index != i or abs(seg.start - end) > 0.03:
                raise ValueError("片段 index 必须从 0 顺序排列，时间线必须连续且不重叠")
            seg.generation_duration = max(4, math.ceil(seg.duration - 0.001))
            end += seg.duration
        if self.shots:
            for shot in self.shots:
                if shot.end <= shot.start or shot.end > end + 0.05 or shot.start > end + 0.05:
                    raise ValueError("镜头必须有正时长，且不能超出分镜总时长")
            for seg in self.segments:
                # Links follow edited timing rather than trusting stale model/UI indices.
                seg.shot_indices = [i for i, shot in enumerate(self.shots)
                                    if min(shot.end, seg.start + seg.duration) - max(shot.start, seg.start) > 0.000001]
        return self

class PlanInput(BaseModel):
    analysis: AnalysisPlan
