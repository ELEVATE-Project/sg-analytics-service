"""
Postgres async engine and session factory.

The engine is created lazily on first use so that importing this module
does not raise if DATABASE_URL is not yet in the environment (e.g. during
test discovery or IDE imports).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from ..core.config import settings  # pydantic-settings loads .env for us

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker | None = None


def get_db_url() -> str:
    """Return the asyncpg-compatible DATABASE_URL from settings."""
    url = settings.DATABASE_URL
    if not url:
        raise ValueError("DATABASE_URL environment variable is required")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_db_url(), echo=False)
    return _engine


def async_session() -> AsyncSession:  # type: ignore[return]
    """Return a new async session from the lazily-created session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _session_factory()


async def get_db():
    """FastAPI dependency that yields an AsyncSession."""
    async with async_session() as session:
        yield session
