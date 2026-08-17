import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator

# Base directory for the project (two levels up from core directory, to sg-analytics-service)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    # Qdrant settings
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    MATCHING_COLLECTION: str = "storing_pairs_bot-specific"

    # Redis cache
    REDIS_URL: str = "redis://localhost:6379/0"

    # Postgres database URL (required — no default so startup fails fast if missing)
    DATABASE_URL: str
    
    # Matching Logic Constants
    TYPE_CHALLENGE: str = "challenge"
    TYPE_SOLUTION: str = "solution"
    FINAL_RESULT_SIZE: int = 10
    PRE_LLM_FETCH_SIZE: int = 50
    TOP_SOLUTIONS_PER_CHALLENGE: int = 5
    SOLUTION_CANDIDATE_POOL_SIZE: int = 50
    CACHE_TTL_HOURS: float = 2.0
    MAX_PER_TOPIC: int = 1
    MIN_MATCH_SCORE: float = 0.85
    MAX_MATCH_SCORE: float = 0.99
    # Per-challenge fallback: retry with this lower threshold when primary fetch returns 0 solutions
    FALLBACK_MATCH_SCORE: float = 0.70

    # Solution bot_type filter: "story", "discussion", or "hybrid" (both)
    SOLUTION_BOT_TYPE: str = "story"

    # Rate limiting configuration
    RATE_LIMIT: str = "10/minute"
    
    # Topic keywords for deduplication
    TOPIC_KEYWORDS: dict = {
        "aadhaar": ["aadhaar", "aadhar", "adhaar", "adhar"],
    }
    
    # Gemini API
    GEMINI_API_KEY: str = ""
    # Minimum LLM score (1-5) for a pair to be accepted.
    # 3 is intentionally chosen over 4: score=4 rejects too many
    # borderline-but-valid pairs and reduces output volume significantly.
    MIN_LLM_SCORE: int = 3
    # How long (seconds) to cache the active prompt before re-querying Postgres.
    PROMPT_TTL_SECONDS: int = 300  # 5 minutes

    # API Auth Token – callers must send this value in the X-Auth-Token header.
    # If left blank the auth middleware will reject every request at startup.
    API_TOKEN: str = ""

    # CORS settings
    ALLOWED_ORIGINS: list[str] | str = ["http://localhost:3000"]
    ALLOWED_METHODS: list[str] | str = ["GET", "POST", "OPTIONS"]
    ALLOWED_HEADERS: list[str] | str = ["Content-Type", "Authorization", "X-Auth-Token"]
    
    # Debug Logging
    DEBUG_LOG_DIR: Path = BASE_DIR / "pre_llm_logs"

    @field_validator("SOLUTION_BOT_TYPE", mode="before")
    @classmethod
    def validate_bot_type(cls, v: str) -> str:
        v = v.strip().lower()
        valid = {"story", "discussion", "hybrid"}
        if v not in valid:
            raise ValueError(
                f"Invalid SOLUTION_BOT_TYPE='{v}'. "
                f"Must be one of: {sorted(valid)}"
            )
        return v

    @field_validator("ALLOWED_ORIGINS", "ALLOWED_METHODS", "ALLOWED_HEADERS", mode="before")
    @classmethod
    def parse_cors_lists(cls, v) -> list[str]:
        if isinstance(v, str):
            parsed = [item.strip() for item in v.split(",") if item.strip()]
        elif isinstance(v, list):
            parsed = v
        else:
            raise ValueError("Must be a list or comma-separated string")
            
        if "*" in parsed:
            raise ValueError("Wildcard '*' is not allowed for CORS configuration")
        return parsed

settings = Settings()
