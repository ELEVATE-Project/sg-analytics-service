from pydantic import BaseModel, ConfigDict
from ..core.config import settings as _settings


class PairJudgement(BaseModel):
    rank: int
    best_sol_id: str | None = None
    score: int          # 1 (no match) - 5 (excellent, specific match)
    pii_detected: bool  # true if challenge/solution text names a person, village, address, or phone number
    verdict: str        # "PASS" or "FAIL"
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
