from pydantic import BaseModel

class PairJudgement(BaseModel):
    rank: int
    best_sol_id: str | None = None
    score: int          # 1 (no match) - 5 (excellent, specific match)
    pii_detected: bool  # true if challenge/solution text names a person, village, address, or phone number
    verdict: str        # "PASS" or "FAIL"
    reason: str


class ValidationResponse(BaseModel):
    judgements: list[PairJudgement]
