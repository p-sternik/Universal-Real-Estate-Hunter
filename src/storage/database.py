import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from loguru import logger
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings
from .models import Base

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_url = settings.DATABASE_URL
        # For sqlite ensure directory exists if path is provided
        if db_url.startswith("sqlite+aiosqlite:///"):
            path = db_url.replace("sqlite+aiosqlite:///", "")
            dirname = os.path.dirname(path)
            if dirname:
                os.makedirs(dirname, exist_ok=True)

        _engine = create_async_engine(
            db_url,
            echo=False,
            future=True,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        engine = get_engine()
        _sessionmaker = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _sessionmaker


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager providing an isolated session."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


from sqlalchemy import text


async def _migrate_sqlite_columns(conn) -> None:
    """Safely adds missing columns to existing SQLite tables."""
    def _do_migrate(sync_conn):
        try:
            res = sync_conn.execute(text("PRAGMA table_info(listings)")).fetchall()
            existing_cols = {row[1] for row in res}
            if existing_cols:  # table exists
                if "is_exact_coords" not in existing_cols:
                    logger.info("Migrating schema: adding 'is_exact_coords' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN is_exact_coords BOOLEAN DEFAULT 1"))
                if "user_status" not in existing_cols:
                    logger.info("Migrating schema: adding 'user_status' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN user_status VARCHAR(30) DEFAULT 'NEW'"))
                if "user_notes" not in existing_cols:
                    logger.info("Migrating schema: adding 'user_notes' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN user_notes TEXT"))
                if "finish_condition" not in existing_cols:
                    logger.info("Migrating schema: adding 'finish_condition' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN finish_condition VARCHAR(50) DEFAULT 'nieokreślony'"))
                if "has_visualisations" not in existing_cols:
                    logger.info("Migrating schema: adding 'has_visualisations' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN has_visualisations BOOLEAN DEFAULT 0"))
                if "sewerage" not in existing_cols:
                    logger.info("Migrating schema: adding 'sewerage' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN sewerage VARCHAR(50) DEFAULT 'nieznana'"))
                if "heating" not in existing_cols:
                    logger.info("Migrating schema: adding 'heating' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN heating VARCHAR(50) DEFAULT 'nieznane'"))
                if "has_fiber" not in existing_cols:
                    logger.info("Migrating schema: adding 'has_fiber' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN has_fiber BOOLEAN DEFAULT 0"))
                if "category" not in existing_cols:
                    logger.info("Migrating schema: adding 'category' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN category VARCHAR(50) DEFAULT 'dom'"))
                if "rooms" not in existing_cols:
                    logger.info("Migrating schema: adding 'rooms' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN rooms INTEGER"))
                if "floor" not in existing_cols:
                    logger.info("Migrating schema: adding 'floor' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN floor INTEGER"))
                if "floors_in_building" not in existing_cols:
                    logger.info("Migrating schema: adding 'floors_in_building' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN floors_in_building INTEGER"))
                if "last_scraped_at" not in existing_cols:
                    logger.info("Migrating schema: adding 'last_scraped_at' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN last_scraped_at DATETIME"))
                if "is_private_owner" not in existing_cols:
                    logger.info("Migrating schema: adding 'is_private_owner' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN is_private_owner BOOLEAN"))
                if "profile_id" not in existing_cols:
                    logger.info("Migrating schema: adding 'profile_id' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN profile_id VARCHAR(100)"))
                    sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_listings_profile_id ON listings (profile_id)"))
                    sync_conn.execute(text("UPDATE listings SET profile_id = 'default' WHERE profile_id IS NULL"))
                if "profile_name" not in existing_cols:
                    logger.info("Migrating schema: adding 'profile_name' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN profile_name VARCHAR(100)"))
                if "gallery_images" not in existing_cols:
                    logger.info("Migrating schema: adding 'gallery_images' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN gallery_images TEXT DEFAULT '[]'"))
                if "parcel_id" not in existing_cols:
                    logger.info("Migrating schema: adding 'parcel_id' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN parcel_id VARCHAR(100)"))
                if "cadastral_area" not in existing_cols:
                    logger.info("Migrating schema: adding 'cadastral_area' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN cadastral_area FLOAT"))
                if "geoportal_url" not in existing_cols:
                    logger.info("Migrating schema: adding 'geoportal_url' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN geoportal_url VARCHAR(500)"))
        except Exception as e:
            logger.warning(f"Schema migration note: {e}")

    await conn.run_sync(_do_migrate)


async def init_db() -> None:
    """Initialize database tables and run lightweight migrations."""
    engine = get_engine()
    logger.info("Initializing database tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_sqlite_columns(conn)
    logger.info("Database tables initialized and up-to-date.")

