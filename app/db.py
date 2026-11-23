from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Create sync engine for migrations and simple queries
engine = create_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Create async engine for fastapi-users
async_engine = create_async_engine(get_settings().database_url)
AsyncSessionLocal = async_sessionmaker(bind=async_engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
