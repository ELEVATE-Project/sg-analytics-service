import logging
from sqlalchemy import text
from ..database.postgres import async_session

logger = logging.getLogger(__name__)


async def get_community_feed_from_db() -> list[dict] | None:
    query = text("""
        WITH latest_stories AS (
            SELECT DISTINCT ON (s.submission_id)
                s.submission_id,
                s.submission_date,
                s.role,
                s.district,
                s.state,
                ss.action_steps,
                ss.impact
            FROM submissions s
            JOIN story_submissions ss
                ON ss.submission_id = s.submission_id
            WHERE s.submission_date IS NOT NULL
              AND ss.action_steps IS NOT NULL
              AND CARDINALITY(ss.action_steps) > 0
              AND ss.impact IS NOT NULL
              AND TRIM(ss.impact) <> ''
            ORDER BY
                s.submission_id,
                s.submission_date DESC
        )

        SELECT
            submission_id,
            array_to_string(action_steps, ', ') AS action_step,
            impact,
            role,
            district,
            state,
            submission_date
        FROM latest_stories
        ORDER BY
            submission_date DESC
        LIMIT 20;
    """)

    try:
        async with async_session() as session:
            result = await session.execute(query)
            rows = result.fetchall()

            stories = []
            for row in rows:
                stories.append({
                    "submission_id": str(row.submission_id) if row.submission_id else None,
                    "action_step": row.action_step,
                    "impact": row.impact,
                    "role": row.role,
                    "district": row.district,
                    "state": row.state,
                    "submission_date": row.submission_date.isoformat() if row.submission_date else None,
                })

            return stories
    except Exception as e:
        logger.error(f"Error fetching community feed: {e}")
        return None
