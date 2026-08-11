from pydantic import BaseModel, ConfigDict
from ...config import settings as _settings


class PairJudgement(BaseModel):
    rank: int
    best_sol_id: str | None = None
    score: int          # 1 (no match) - 5 (excellent, specific match)
    pii_detected: bool  # true if challenge/solution text names a person, village, address, or phone number
    verdict: str        # "PASS" or "FAIL"
    reason: str


class ValidationResponse(BaseModel):
    judgements: list[PairJudgement]


# ---------------------------------------------------------------------------
# Route query schemas (extra="forbid" rejects unknown query parameters)
# ---------------------------------------------------------------------------

class AnimationsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = _settings.FINAL_RESULT_SIZE
    reset: bool = False


class BigNumbersQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reset: bool = False


# ---------------------------------------------------------------------------
# Route response schemas
# ---------------------------------------------------------------------------

class AnimationsResponse(BaseModel):
    data: list[dict]


class BigNumbersResponse(BaseModel):
    data: dict
