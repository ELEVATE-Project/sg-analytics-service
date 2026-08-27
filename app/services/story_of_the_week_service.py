import logging
from sqlalchemy import text
from ..database.postgres import async_session

logger = logging.getLogger(__name__)


async def get_story_of_the_week_from_db() -> list[dict] | None:
    query = text("""
        WITH latest_stories AS (
            SELECT
                s.submission_id,
                s.submission_date,
                ROW_NUMBER() OVER (
                    ORDER BY
                        s.submission_date DESC NULLS LAST,
                        s.submission_id
                ) AS story_number
            FROM submissions s
            WHERE EXISTS (
                SELECT 1
                FROM story_submissions ss
                WHERE ss.submission_id = s.submission_id
            )
        )

        SELECT
            ss.submission_id,
            ss.tenant_code,
            ss.title,
            ss.content,
            ss.image_urls,
            ss.pdf_urls,
            s.role,
            s.district,
            s.state,
            s.submission_date,
            ls.story_number
        FROM story_submissions ss
        JOIN submissions s
            ON s.submission_id = ss.submission_id
        JOIN latest_stories ls
            ON ls.submission_id = s.submission_id
        WHERE ls.story_number <= 54
        ORDER BY
            ls.story_number,
            ss.tenant_code;
    """)

    try:
        async with async_session() as session:
            result = await session.execute(query)
            rows = result.fetchall()

            stories = []
            for row in rows:
                stories.append({
                    "submission_id": str(row.submission_id) if row.submission_id else None,
                    "tenant_code": row.tenant_code,
                    "title": row.title,
                    "content": row.content,
                    "image_urls": list(row.image_urls) if row.image_urls else None,
                    "pdf_urls": list(row.pdf_urls) if row.pdf_urls else None,
                    "role": row.role,
                    "district": row.district,
                    "state": row.state,
                    "submission_date": row.submission_date.isoformat() if row.submission_date else None,
                    "story_number": row.story_number,
                })

            return stories
    except Exception as e:
        logger.error(f"Error fetching story of the week: {e}")
        return None
