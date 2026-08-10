import logging
from sqlalchemy import text
from ..database.connection import async_session

logger = logging.getLogger(__name__)

async def get_big_numbers_from_db() -> dict | None:
    query = text("""
        WITH -- 1. Shiksha Chaupals
        shiksha_chaupals AS (
            SELECT COUNT(DISTINCT submission_id) AS total
            FROM submissions
            WHERE submission_type = 'discussion'
        ),
        -- 2. Community Members Participating in Dialogues
        community_members AS (
            SELECT COALESCE(SUM(sm.numeric_value), 0) AS total
            FROM submissions s
            JOIN submission_metrics sm ON s.submission_id = sm.submission_id
            WHERE s.submission_type = 'discussion' 
            AND sm.metric_code IN ('men', 'women', 'children', 'teacher')
        ),
        -- 3. Local Challenges Identified
        local_challenges AS (
            SELECT COUNT(*) AS total
            FROM analysis_results
            WHERE LOWER(statement_type) = 'challenges'
        ),
        -- 4. Local Solutions Identified
        local_solutions AS (
            SELECT COUNT(*) AS total
            FROM discussion_submissions
            WHERE solutions IS NOT NULL 
            AND TRIM(solutions::text) <> '{}'  -- Cast array to text and check against empty array string
            AND TRIM(solutions::text) <> ''    -- Ensures it catches any accidental blank string conversions
        ),
        -- 5. Local Solutions Implemented
        implemented_solutions AS (
            SELECT COUNT(DISTINCT submission_id) AS total
            FROM story_submissions
        )
        SELECT 
            sc.total AS shiksha_chaupals,
            cm.total AS community_members_participating_in_dialogues,
            lc.total AS local_challenges_identified,
            ls.total AS local_solutions_identified,
            ims.total AS local_solutions_implemented
        FROM shiksha_chaupals sc
        CROSS JOIN community_members cm
        CROSS JOIN local_challenges lc
        CROSS JOIN local_solutions ls
        CROSS JOIN implemented_solutions ims;
    """)
    
    try:
        async with async_session() as session:
            result = await session.execute(query)
            row = result.fetchone()
            if row:
                return {
                    "shiksha_chaupals": int(row.shiksha_chaupals),
                    "community_members_participating_in_dialogues": int(row.community_members_participating_in_dialogues),
                    "local_challenges_identified": int(row.local_challenges_identified),
                    "local_solutions_identified": int(row.local_solutions_identified),
                    "local_solutions_implemented": int(row.local_solutions_implemented),
                }
            return None
    except Exception as e:
        logger.error(f"Error fetching big numbers: {e}")
        return None
