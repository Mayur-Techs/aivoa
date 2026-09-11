from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import get_settings
from .models import Base

settings = get_settings()


def async_database_url(url: str) -> str:
    """Accept standard managed-Postgres URLs while retaining async SQLAlchemy drivers."""
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgres://")
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql://")
    return url


engine = create_async_engine(async_database_url(settings.database_url), future=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def create_tables() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
