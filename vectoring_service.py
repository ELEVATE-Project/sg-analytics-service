import os
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.http import models as qdrant_models
from sentence_transformers import SentenceTransformer

import sys
from app.config import settings
from app.database.database import get_qdrant_client

ROOT = Path(__file__).resolve().parent


def data_dir() -> Path:
    """Resolve DATA_DIR relative to the project root (or as absolute)."""
    raw = os.getenv("DATA_DIR", "data")
    p = Path(raw)
    return p if p.is_absolute() else ROOT / p

DATA_DIR            = data_dir()
CHALLENGES_GLOB     = os.getenv("CHALLENGES_GLOB", "discussion-challenges.csv")
SOLUTIONS_GLOB      = os.getenv("SOLUTIONS_GLOB",  "new-solutions.csv")

MODEL_NAME          = os.getenv("MODEL_NAME", "all-MiniLM-L6-v2")
BATCH_SIZE          = int(os.getenv("BATCH_SIZE", "256"))

CHALLENGE_ID_OFFSET = int(os.getenv("CHALLENGE_ID_OFFSET", "0"))
SOLUTION_ID_OFFSET  = int(os.getenv("SOLUTION_ID_OFFSET",  "10000000"))
SCORE_BATCH_SIZE    = int(os.getenv("SCORE_BATCH_SIZE", "50"))
SCORE_CANDIDATE_POOL_SIZE = int(os.getenv("SCORE_CANDIDATE_POOL_SIZE", "50"))


def format_duration(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    millis = int((seconds - int(seconds)) * 1000)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}.{millis:03d}s"


def discover_csvs(pattern: str) -> list[Path]:

    matches = sorted(DATA_DIR.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"No CSV files found in '{DATA_DIR}' matching pattern '{pattern}'. "
            "Check DATA_DIR, CHALLENGES_GLOB, and SOLUTIONS_GLOB in your .env."
        )
    return matches

def clean_id(raw_id) -> int:
    """Parse an id cell to int, stripping commas and whitespace."""
    try:
        return int(str(raw_id).replace(",", "").strip())
    except ValueError:
        return 0


def str_or_empty(val) -> str:
    """Return stripped string value, or empty string for NaN/None."""
    if val is None:
        return ""
    s = str(val).strip()
    return "" if s.lower() == "nan" else s


def load_challenge_records(filepath: Path) -> list[dict]:
    """Load challenge records from a single CSV file.

    Expected columns: id, State, District, Challenges, Solutions
    Each row is one challenge statement (no pipe-splitting needed).
    """
    df = pd.read_csv(filepath, usecols=lambda c: c in {"id", "State", "District", "Challenges"})
    df = df.dropna(subset=["Challenges"])
    df["id"] = df["id"].apply(clean_id)

    records = []
    for _, row in df.iterrows():
        text = str_or_empty(row["Challenges"])
        if not text:
            continue
        records.append({
            "real_id":  row["id"],
            "text":     text,
            "role":     "",
            "district": str_or_empty(row.get("District")),
            "state":    str_or_empty(row.get("State")),
            "bot_type": "discussion",
        })
    return records


def load_discussion_solution_records(filepath: Path) -> list[dict]:
    """Load discussion solution records from a challenge/discussion CSV file.

    Expected columns: id, State, District, Solutions
    """
    df = pd.read_csv(filepath, usecols=lambda c: c in {"id", "State", "District", "Solutions"})
    df = df.dropna(subset=["Solutions"])
    df["id"] = df["id"].apply(clean_id)

    records = []
    for _, row in df.iterrows():
        text = str_or_empty(row["Solutions"])
        if not text:
            continue
        records.append({
            "real_id":  row["id"],
            "text":     text,
            "role":     "",
            "district": str_or_empty(row.get("District")),
            "state":    str_or_empty(row.get("State")),
            "bot_type": "discussion",
        })
    return records


def load_solution_records(filepath: Path) -> list[dict]:
    """Load solution records from a single CSV file.

    Expected columns: id, Role, State, District, Solution
    """
    df = pd.read_csv(filepath, usecols=lambda c: c in {"id", "Role", "State", "District", "Solution"})
    df = df.dropna(subset=["Solution"])
    df["id"] = df["id"].apply(clean_id)

    records = []
    for _, row in df.iterrows():
        text = str_or_empty(row["Solution"])
        if not text:
            continue
        records.append({
            "real_id":  row["id"],
            "text":     text,
            "role":     str_or_empty(row.get("Role")),
            "district": str_or_empty(row.get("District")),
            "state":    str_or_empty(row.get("State")),
            "bot_type": "story",
        })
    return records


def load_all_challenge_records() -> list[dict]:
    """Discover and load challenge CSVs from all matching files in DATA_DIR."""
    csv_files = discover_csvs(CHALLENGES_GLOB)
    print(f"  → Found {len(csv_files)} challenge CSV(s):")
    all_records: list[dict] = []
    for f in csv_files:
        print(f"      • {f.name}")
        all_records.extend(load_challenge_records(f))
    return all_records


def load_all_solution_records() -> list[dict]:
    """Discover and load solution CSVs from all matching files in DATA_DIR."""
    csv_files = discover_csvs(SOLUTIONS_GLOB)
    print(f"  → Found {len(csv_files)} solution CSV(s):")
    all_records: list[dict] = []
    for f in csv_files:
        print(f"      • {f.name}")
        all_records.extend(load_solution_records(f))
    return all_records


def load_all_discussion_solution_records() -> list[dict]:
    """Discover and load discussion solutions from challenge CSVs."""
    csv_files = discover_csvs(CHALLENGES_GLOB)
    print(f"  → Found {len(csv_files)} discussion solution CSV(s):")
    all_records: list[dict] = []
    for f in csv_files:
        print(f"      • {f.name}")
        all_records.extend(load_discussion_solution_records(f))
    return all_records


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def dedupe_records(records: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    order: list[str] = []
    for rec in records:
        key = normalize_text(rec["text"])
        if key not in seen:
            seen[key] = dict(rec)
            order.append(key)
    return [seen[k] for k in order]


def best_valid_match_score(source_statement: str, response) -> float:
    """Pick the best non-identical match within the configured score band."""
    source_key = normalize_text(source_statement)
    for point in response.points:
        score = float(point.score or 0.0)
        if not (settings.MIN_MATCH_SCORE <= score <= settings.MAX_MATCH_SCORE):
            continue
        payload = point.payload or {}
        if normalize_text(payload.get("statement", "")) == source_key:
            continue
        return score
    return 0.0


# QDRANT STORAGE

def recreate_collection(client: QdrantClient, name: str, vector_size: int):
    existing = [c.name for c in client.get_collections().collections]
    if name in existing:
        client.delete_collection(name)
        print(f" Deleted existing collection '{name}'")
    client.create_collection(
        collection_name=name,
        vectors_config=qdrant_models.VectorParams(size=vector_size, distance=qdrant_models.Distance.COSINE),
    )
    print(f" Created collection '{name}'")


def build_payload(rec: dict, point_type: str) -> dict:
    return {
        "id": rec["real_id"],
        "type": point_type,
        "bot_type": rec.get("bot_type"),
        "statement": rec["text"],
        "embedded_score": 0.0,   # filled in by scoring below
        "meta": {
            "role": rec.get("role", "") or None,
            "district": rec.get("district", "") or None,
            "state": rec.get("state", "") or None,
        },
    }


def upsert_type(client: QdrantClient, records: list[dict], embeddings: np.ndarray,
                 point_type: str, id_offset: int) -> None:
    points = [
        qdrant_models.PointStruct(id=id_offset + idx, vector=emb.tolist(),
                                   payload=build_payload(rec, point_type))
        for idx, (rec, emb) in enumerate(zip(records, embeddings))
    ]
    chunk = 1000
    for start in range(0, len(points), chunk):
        client.upsert(collection_name=settings.MATCHING_COLLECTION, points=points[start:start + chunk])
    print(f" Upserted {len(points)} '{point_type}' points")


def ensure_payload_index(client: QdrantClient, field_name: str, schema) -> None:
    try:
        client.create_payload_index(collection_name=settings.MATCHING_COLLECTION,
                                     field_name=field_name, field_schema=schema)
    except Exception:
        pass  


# OFFLINE SCORING — each challenge's best-known match strength

def score_challenges(client: QdrantClient) -> dict:

    solution_filter = qdrant_models.Filter(
        must=[qdrant_models.FieldCondition(key="type", match=qdrant_models.MatchValue(value=settings.TYPE_SOLUTION))]
    )

    stats = {"scored": 0, "nonzero": 0, "zero": 0}
    offset = None
    while True:
        challenge_points, offset = client.scroll(
            collection_name=settings.MATCHING_COLLECTION,
            scroll_filter=qdrant_models.Filter(
                must=[qdrant_models.FieldCondition(key="type", match=qdrant_models.MatchValue(value=settings.TYPE_CHALLENGE))]
            ),
            limit=SCORE_BATCH_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not challenge_points:
            break

        requests = [
            qdrant_models.QueryRequest(
                query=p.vector,
                filter=solution_filter,
                limit=SCORE_CANDIDATE_POOL_SIZE,
                with_payload=True,
                score_threshold=settings.MIN_MATCH_SCORE,
            )
            for p in challenge_points
        ]
        responses = client.query_batch_points(collection_name=settings.MATCHING_COLLECTION, requests=requests)

        for chal_point, response in zip(challenge_points, responses):
            chal_payload = chal_point.payload or {}
            best_score = best_valid_match_score(chal_payload.get("statement", ""), response)
            client.set_payload(
                collection_name=settings.MATCHING_COLLECTION,
                payload={"embedded_score": round(float(best_score), 4)},
                points=[chal_point.id],
            )
            stats["scored"] += 1
            if best_score > 0:
                stats["nonzero"] += 1
            else:
                stats["zero"] += 1

        if offset is None:
            break

    return stats


def score_solutions(client: QdrantClient) -> dict:

    challenge_filter = qdrant_models.Filter(
        must=[qdrant_models.FieldCondition(key="type", match=qdrant_models.MatchValue(value=settings.TYPE_CHALLENGE))]
    )

    stats = {"scored": 0, "nonzero": 0, "zero": 0}
    offset = None
    while True:
        solution_points, offset = client.scroll(
            collection_name=settings.MATCHING_COLLECTION,
            scroll_filter=qdrant_models.Filter(
                must=[qdrant_models.FieldCondition(key="type", match=qdrant_models.MatchValue(value=settings.TYPE_SOLUTION))]
            ),
            limit=SCORE_BATCH_SIZE,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )
        if not solution_points:
            break

        requests = [
            qdrant_models.QueryRequest(
                query=p.vector,
                filter=challenge_filter,
                limit=SCORE_CANDIDATE_POOL_SIZE,
                with_payload=True,
                score_threshold=settings.MIN_MATCH_SCORE,
            )
            for p in solution_points
        ]
        responses = client.query_batch_points(collection_name=settings.MATCHING_COLLECTION, requests=requests)

        for sol_point, response in zip(solution_points, responses):
            sol_payload = sol_point.payload or {}
            best_score = best_valid_match_score(sol_payload.get("statement", ""), response)
            client.set_payload(
                collection_name=settings.MATCHING_COLLECTION,
                payload={"embedded_score": round(float(best_score), 4)},
                points=[sol_point.id],
            )
            stats["scored"] += 1
            if best_score > 0:
                stats["nonzero"] += 1
            else:
                stats["zero"] += 1

        if offset is None:
            break

    return stats

# MAIN

def main():
    total_start = time.perf_counter()
    print(f"\nConfig loaded from: {ROOT / '.env'}")
    print(f"  DATA_DIR            = {DATA_DIR}")
    print(f"  CHALLENGES_GLOB     = {CHALLENGES_GLOB}")
    print(f"  SOLUTIONS_GLOB      = {SOLUTIONS_GLOB}")
    print(f"  QDRANT_HOST:PORT    = {settings.QDRANT_HOST}:{settings.QDRANT_PORT}")
    print(f"  MATCHING_COLLECTION = {settings.MATCHING_COLLECTION}")
    print(f"  MODEL_NAME          = {MODEL_NAME}")

    step_start = time.perf_counter()
    print("\n[1/4] Loading + deduping data...")
    challenges = dedupe_records(load_all_challenge_records())
    discussion_solutions = load_all_discussion_solution_records()
    story_solutions = load_all_solution_records()
    solutions = dedupe_records(discussion_solutions + story_solutions)
    print(
        f"      {len(challenges):,} unique challenges, "
        f"{len(solutions):,} unique solutions "
        f"({len(discussion_solutions):,} discussion rows + {len(story_solutions):,} story rows before dedupe)"
    )
    print(f"      step_time_consumed={format_duration(time.perf_counter() - step_start)}")

    step_start = time.perf_counter()
    print(f"\n[2/4] Embedding with '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)
    vector_size = model.get_embedding_dimension()
    challenge_embeddings = np.asarray(model.encode(
        [r["text"] for r in challenges], batch_size=BATCH_SIZE, show_progress_bar=True))
    solution_embeddings = np.asarray(model.encode(
        [r["text"] for r in solutions], batch_size=BATCH_SIZE, show_progress_bar=True))
    print(f"      step_time_consumed={format_duration(time.perf_counter() - step_start)}")

    step_start = time.perf_counter()
    print(f"\n[3/4] Storing into single collection '{settings.MATCHING_COLLECTION}'...")
    client = get_qdrant_client()
    recreate_collection(client, settings.MATCHING_COLLECTION, vector_size)
    upsert_type(client, challenges, challenge_embeddings, settings.TYPE_CHALLENGE, CHALLENGE_ID_OFFSET)
    upsert_type(client, solutions, solution_embeddings, settings.TYPE_SOLUTION, SOLUTION_ID_OFFSET)
    print(" embedded_score is 0.0 immediately after upsert; scoring updates it in [4/4].")

    ensure_payload_index(client, "type", qdrant_models.PayloadSchemaType.KEYWORD)
    ensure_payload_index(client, "embedded_score", qdrant_models.PayloadSchemaType.FLOAT)
    print(f"      step_time_consumed={format_duration(time.perf_counter() - step_start)}")

    step_start = time.perf_counter()
    print(f"\n[4/4] Scoring challenges and solutions (best-known match strength)...")
    challenge_stats = score_challenges(client)
    print(
        f" Scored {challenge_stats['scored']:,} challenges "
        f"({challenge_stats['nonzero']:,} in-band non-duplicate, {challenge_stats['zero']:,} zero/no valid match)"
    )
    solution_stats = score_solutions(client)
    print(
        f" Scored {solution_stats['scored']:,} solutions "
        f"({solution_stats['nonzero']:,} in-band non-duplicate, {solution_stats['zero']:,} zero/no valid match)"
    )
    print(f"      step_time_consumed={format_duration(time.perf_counter() - step_start)}")

    print(f" Done. '{settings.MATCHING_COLLECTION}' ready for the live API.")
    print(f" total_time_consumed={format_duration(time.perf_counter() - total_start)}")


if __name__ == "__main__":
    main()
