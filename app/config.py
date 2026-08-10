import os
from pathlib import Path
from dotenv import load_dotenv

# Base directory for the project (one level up from app directory)
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file from the project root
load_dotenv(BASE_DIR / ".env")

def parse_list(env_var: str, default: str) -> list[str]:
    """Split a comma-separated env var into a stripped list."""
    raw = os.getenv(env_var, default)
    return [item.strip() for item in raw.split(",") if item.strip()]

class Settings:
    # Qdrant settings
    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
    MATCHING_COLLECTION = os.getenv("MATCHING_COLLECTION", "storing_pairs_bot-specific")

    # Redis cache
    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    
    # Matching Logic Constants
    TYPE_CHALLENGE = "challenge"
    TYPE_SOLUTION = "solution"
    FINAL_RESULT_SIZE = int(os.getenv("FINAL_RESULT_SIZE", "10"))
    PRE_LLM_FETCH_SIZE = int(os.getenv("PRE_LLM_FETCH_SIZE", "50"))
    TOP_SOLUTIONS_PER_CHALLENGE = int(os.getenv("TOP_SOLUTIONS_PER_CHALLENGE", "5"))
    SOLUTION_CANDIDATE_POOL_SIZE = int(os.getenv("SOLUTION_CANDIDATE_POOL_SIZE", "50"))
    CACHE_TTL_HOURS = float(os.getenv("CACHE_TTL_HOURS", "2.0"))
    MAX_PER_TOPIC = int(os.getenv("MAX_PER_TOPIC", "1"))
    MIN_MATCH_SCORE = float(os.getenv("MIN_MATCH_SCORE", "0.85"))
    MAX_MATCH_SCORE = float(os.getenv("MAX_MATCH_SCORE", "0.99"))
    # Per-challenge fallback: retry with this lower threshold when primary fetch returns 0 solutions
    FALLBACK_MATCH_SCORE = float(os.getenv("FALLBACK_MATCH_SCORE", "0.70"))

    # Solution bot_type filter: "story", "discussion", or "hybrid" (both)
    _VALID_BOT_TYPES = {"story", "discussion", "hybrid"}
    SOLUTION_BOT_TYPE: str = os.getenv("SOLUTION_BOT_TYPE", "story").strip().lower()

    # Rate limiting configuration
    RATE_LIMIT = os.getenv("RATE_LIMIT", "10/minute")

    def __init__(self):
        if self.SOLUTION_BOT_TYPE not in self._VALID_BOT_TYPES:
            raise ValueError(
                f"Invalid SOLUTION_BOT_TYPE='{self.SOLUTION_BOT_TYPE}'. "
                f"Must be one of: {sorted(self._VALID_BOT_TYPES)}"
            )
    
    # Topic keywords for deduplication
    TOPIC_KEYWORDS = {
        "aadhaar": ["aadhaar", "aadhar", "adhaar", "adhar"],
    }
    
    # Gemini API
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

    # API Auth Token – callers must send this value in the X-API-Token header.
    # If left blank the auth middleware will reject every request at startup.
    API_TOKEN = os.getenv("API_TOKEN", "")

    # CORS settings
    ALLOWED_ORIGINS = parse_list("ALLOWED_ORIGINS", "http://localhost:3000")
    ALLOWED_METHODS = parse_list("ALLOWED_METHODS", "GET,POST,OPTIONS")
    ALLOWED_HEADERS = parse_list("ALLOWED_HEADERS", "Content-Type,Authorization,X-API-Token")
    
    # Debug Logging
    DEBUG_LOG_DIR = Path(os.getenv("DEBUG_LOG_DIR", str(BASE_DIR / "pre_llm_logs")))

settings = Settings()
