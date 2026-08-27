import logging
from sqlalchemy import text
from ..database.postgres import async_session

logger = logging.getLogger(__name__)

async def get_top_themes_with_voices_from_db() -> list[dict] | None:
    query = text("""
        WITH theme_voices AS (
            SELECT
                ar.theme_id,
                ar.id AS analysis_result_id,
                ar.statements,
                s.role,
                s.district,
                s.state,
                ROW_NUMBER() OVER (
                    PARTITION BY ar.theme_id
                    ORDER BY ar.id
                ) AS voice_number
            FROM analysis_results ar
            JOIN submissions s
                ON s.submission_id = ar.submission_id
               AND s.tenant_code = ar.tenant_code
        ),
        theme_counts AS (
            SELECT
                theme_id,
                COUNT(*) AS voice_count
            FROM analysis_results
            WHERE theme_id IS NOT NULL
            GROUP BY theme_id
        )
        SELECT
            t.id AS theme_id,
            t.name AS theme_name,
            COALESCE(tc.voice_count, 0) AS voice_count,
            tv.analysis_result_id,
            tv.statements AS description,
            tv.role AS voice_by,
            tv.district,
            tv.state,
            tv.voice_number
        FROM themes t
        LEFT JOIN theme_counts tc
            ON tc.theme_id = t.id
        LEFT JOIN theme_voices tv
            ON tv.theme_id = t.id
           AND tv.voice_number <= 4
        ORDER BY
            COALESCE(tc.voice_count, 0) DESC,
            t.id,
            tv.voice_number;
    """)
    
    try:
        async with async_session() as session:
            result = await session.execute(query)
            rows = result.fetchall()
            
            themes_dict = {}
            for row in rows:
                theme_id = str(row.theme_id) if row.theme_id else None
                if theme_id and theme_id not in themes_dict:
                    themes_dict[theme_id] = {
                        "theme_id": theme_id,
                        "theme_name": row.theme_name,
                        "voice_count": row.voice_count,
                        "voices": []
                    }
                
                if row.analysis_result_id and theme_id:
                    themes_dict[theme_id]["voices"].append({
                        "analysis_result_id": str(row.analysis_result_id),
                        "description": row.description,
                        "voice_by": row.voice_by,
                        "district": row.district,
                        "state": row.state,
                        "voice_number": row.voice_number
                    })
            
            return list(themes_dict.values())
    except Exception as e:
        logger.error(f"Error fetching top themes with voices: {e}")
        return None

async def get_theme_voices_paginated_from_db(theme_id: str, page: int, page_size: int) -> dict | None:
    query = text("""
        WITH total_count AS (
            SELECT COUNT(*) AS total_voices
            FROM analysis_results ar
            JOIN submissions s
                ON s.submission_id = ar.submission_id
               AND s.tenant_code = ar.tenant_code
            WHERE ar.theme_id = :theme_id
        ),
        paged AS (
            SELECT
                ar.id AS analysis_result_id,
                ar.theme_id,
                ar.statements AS description,
                s.role AS voice_by,
                s.district,
                s.state
            FROM analysis_results ar
            JOIN submissions s
                ON s.submission_id = ar.submission_id
               AND s.tenant_code = ar.tenant_code
            WHERE ar.theme_id = :theme_id
            ORDER BY ar.id
            LIMIT :page_size
            OFFSET :offset
        )
        SELECT
            p.analysis_result_id,
            p.theme_id,
            p.description,
            p.voice_by,
            p.district,
            p.state,
            t.total_voices
        FROM total_count t
        LEFT JOIN paged p ON TRUE;
    """)
    
    offset = (page - 1) * page_size
    
    try:
        async with async_session() as session:
            result = await session.execute(query, {"theme_id": theme_id, "page_size": page_size, "offset": offset})
            rows = result.fetchall()
            
            voices = []
            total_voices = 0
            if rows:
                total_voices = rows[0].total_voices
                for row in rows:
                    if row.analysis_result_id is not None:
                        voices.append({
                            "analysis_result_id": str(row.analysis_result_id) if row.analysis_result_id else None,
                            "theme_id": str(row.theme_id) if row.theme_id else None,
                            "description": row.description,
                            "voice_by": row.voice_by,
                            "district": row.district,
                            "state": row.state
                        })
            
            return {
                "voices": voices,
                "total_voices": total_voices,
                "page": page,
                "page_size": page_size
            }
    except Exception as e:
        logger.error(f"Error fetching paginated theme voices: {e}")
        return None
