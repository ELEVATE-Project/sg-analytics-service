import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DB_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://user:password@localhost/dbname")
# Ensure the URL uses asyncpg
if DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(DB_URL, echo=False)
async_session = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db():
    async with async_session() as session:
        yield session
