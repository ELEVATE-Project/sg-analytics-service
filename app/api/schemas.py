from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from ..core.config import settings as _settings


class PairJudgement(BaseModel):
    rank: int
    best_sol_id: str | None = None
    score: int = Field(ge=1, le=5)  # 1 (no match) - 5 (excellent, specific match)
    pii_detected: bool  # true if challenge/solution text names a person, village, address, or phone number
    verdict: Literal["PASS", "FAIL"]        # "PASS" or "FAIL"
    reason: str


class ValidationResponse(BaseModel):
    judgements: list[PairJudgement]


# Route query schemas (extra="forbid" rejects unknown query parameters)

class AnimationsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = _settings.FINAL_RESULT_SIZE
    reset: bool = False


class BigNumbersQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: bool = False

class ThemeQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: bool = False

class ThemeVoiceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=4, ge=1, le=100)
    reset: bool = False


# Typed sub-models for pair items

class PairParticipant(BaseModel):
    """Common fields for a challenge or solution participant in an animation pair."""
    id: str | int
    text: str | None = None
    bot_type: str | None = None
    role: str | None = None
    district: str | None = None
    state: str | None = None


class AnimationPairItem(BaseModel):
    """A single validated challenge-solution pair returned by the animations endpoint."""
    rank: int
    match_score: float
    challenge: PairParticipant
    solution: PairParticipant


class BigNumbersData(BaseModel):
    """Aggregated big-number metrics returned by the metrics endpoint."""
    shiksha_chaupals: int
    community_members_participating_in_dialogues: int
    local_challenges_identified: int
    local_solutions_identified: int
    local_solutions_implemented: int


# Route response schemas

class AnimationsResponse(BaseModel):
    data: list[AnimationPairItem]


class BigNumbersResponse(BaseModel):
    data: BigNumbersData

class ThemeVoice(BaseModel):
    analysis_result_id: str | int | None = None
    description: str | None = None
    voice_by: str | None = None
    district: str | None = None
    state: str | None = None
    voice_number: int | None = None
    theme_id: str | int | None = None

class ThemeWithVoices(BaseModel):
    theme_id: str | int
    theme_name: str | None = None
    voice_count: int = 0
    voices: list[ThemeVoice] = []

class ThemesResponse(BaseModel):
    data: list[ThemeWithVoices]

class ThemeVoicesPaginatedData(BaseModel):
    voices: list[ThemeVoice]
    total_voices: int
    page: int
    page_size: int

class ThemeVoicesPaginatedResponse(BaseModel):
    data: ThemeVoicesPaginatedData


class CommunityFeedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: bool = False


class CommunityFeedStory(BaseModel):
    """A single story entry returned by the community feed endpoint."""
    submission_id: str | int
    action_step: str | None = None
    impact: str | None = None
    role: str | None = None
    district: str | None = None
    state: str | None = None
    submission_date: str | None = None



class CommunityFeedResponse(BaseModel):
    data: list[CommunityFeedStory]


class StoryOfTheWeekQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: bool = False


class StoryOfTheWeekItem(BaseModel):
    """A single story entry returned by the story-of-the-week endpoint."""
    submission_id: str | int
    tenant_code: str | None = None
    title: str | None = None
    content: str | None = None
    image_urls: list[str] | None = None
    pdf_urls: list[str] | None = None
    role: str | None = None
    district: str | None = None
    state: str | None = None
    submission_date: str | None = None
    story_number: int | None = None


class StoryOfTheWeekResponse(BaseModel):
    data: list[StoryOfTheWeekItem]
