import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from loguru import logger
from sqlalchemy import event, text
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
_sqlite_write_lock: asyncio.Lock | None = None


def get_sqlite_write_lock() -> asyncio.Lock:
    global _sqlite_write_lock
    if _sqlite_write_lock is None:
        _sqlite_write_lock = asyncio.Lock()
    return _sqlite_write_lock


def is_sqlite_lock_error(exc: BaseException) -> bool:
    """Checks if an exception is a transient SQLite lock, busy, or readonly contention error."""
    msg = str(exc).lower()
    return any(
        k in msg
        for k in (
            "database is locked",
            "readonly database",
            "attempt to write a readonly database",
            "database is busy",
            "disk i/o error",
            "cantlock",
            "locked",
            "busy",
        )
    )


async def safe_commit(session: AsyncSession, max_retries: int = 7, initial_backoff: float = 0.25) -> None:
    """Commit with retry and write-lock protection for SQLite against locks & readonly contention."""
    is_sqlite = "sqlite" in settings.DATABASE_URL
    if not is_sqlite:
        await session.commit()
        return

    write_lock = get_sqlite_write_lock()
    async with write_lock:
        for attempt in range(max_retries):
            try:
                await session.commit()
                return
            except Exception as exc:
                if is_sqlite_lock_error(exc) and attempt < max_retries - 1:
                    backoff = min(5.0, initial_backoff * (1.8**attempt))
                    logger.warning(
                        f"[Database] SQLite lock/readonly contention ({exc}) during commit, "
                        f"retrying in {backoff:.2f}s (attempt {attempt + 1}/{max_retries})..."
                    )
                    await asyncio.sleep(backoff)
                else:
                    raise


def verify_and_repair_sqlite_permissions(db_path_str: str) -> None:
    """
    Proactively checks and heals SQLite directory/file permissions.
    If the directory or file is read-only (e.g. Docker host bind-mount permission mismatch),
    attempts automatic chmod healing or outputs an actionable diagnostic message.
    """
    p_db = Path(db_path_str).resolve()
    directory = p_db.parent
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"[Database] Nie można utworzyć katalogu bazy '{directory}': {e}")
        return

    # Proactive write test to confirm WAL/SHM file creation is allowed
    test_file = directory / f".write_test_{os.getpid()}"
    can_write = False
    try:
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        can_write = True
    except (PermissionError, OSError):
        try:
            directory.chmod(0o777)
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
            can_write = True
        except Exception:
            pass

    if not can_write:
        logger.critical(
            f"[Database] 🚨 BŁĄD UPRAWNIEŃ: Katalog '{directory}' nie zezwala na zapis dla tego procesu!\n"
            f"SQLite nie będzie mógł zapisać bazy danych ani utworzyć plików WAL/SHM (attempt to write a readonly database).\n"
            f"Rozwiązanie na maszynie hosta:\n"
            f"  sudo chmod -R 777 {directory}"
        )

    if p_db.exists():
        try:
            with p_db.open("r+b"):
                pass
        except (PermissionError, OSError):
            try:
                p_db.chmod(0o666)
            except Exception:
                logger.error(f"[Database] Plik bazy '{p_db}' jest tylko do odczytu. Rozwiązanie: sudo chmod 666 {p_db}")

    for ext in ("-wal", "-shm"):
        p_aux = Path(f"{db_path_str}{ext}")
        if p_aux.exists():
            try:
                p_aux.chmod(0o666)
            except Exception:
                pass


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        db_url = settings.DATABASE_URL
        connect_args = {}
        # For sqlite ensure directory exists if path is provided
        if "sqlite" in db_url:
            if db_url.startswith("sqlite+aiosqlite:///"):
                path = db_url.replace("sqlite+aiosqlite:///", "")
                verify_and_repair_sqlite_permissions(path)
            connect_args = {
                "timeout": 60.0,
            }

        _engine = create_async_engine(
            db_url,
            echo=False,
            future=True,
            connect_args=connect_args,
        )

        if "sqlite" in db_url:

            @event.listens_for(_engine.sync_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA busy_timeout=60000")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA journal_mode=WAL")
                    row = cursor.fetchone()
                    mode = str(row[0]).upper() if row else ""
                    if mode != "WAL":
                        logger.warning(
                            f"[Database] WAL journal mode unsupported by filesystem ({mode}), falling back to TRUNCATE."
                        )
                        cursor.execute("PRAGMA journal_mode=TRUNCATE")
                except Exception as e:
                    logger.warning(f"[Database] SQLite pragma warning: {e}")
                finally:
                    cursor.close()

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
    """Async context manager providing an isolated session with write-lock & retry protection for SQLite."""
    session_factory = get_session_factory()
    async with session_factory() as session:
        try:
            yield session
            await safe_commit(session)
        except Exception:
            await session.rollback()
            raise


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
                    sync_conn.execute(
                        text("ALTER TABLE listings ADD COLUMN finish_condition VARCHAR(50) DEFAULT 'nieokreślony'")
                    )
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
                    sync_conn.execute(
                        text("CREATE INDEX IF NOT EXISTS ix_listings_profile_id ON listings (profile_id)")
                    )
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
                if "ai_summary" not in existing_cols:
                    logger.info("Migrating schema: adding 'ai_summary' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN ai_summary TEXT"))
                if "ai_questions" not in existing_cols:
                    logger.info("Migrating schema: adding 'ai_questions' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN ai_questions TEXT DEFAULT '[]'"))
                if "contact_phone" not in existing_cols:
                    logger.info("Migrating schema: adding 'contact_phone' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN contact_phone VARCHAR(50)"))
                if "contact_person" not in existing_cols:
                    logger.info("Migrating schema: adding 'contact_person' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN contact_person VARCHAR(150)"))
                if "ai_verdict" not in existing_cols:
                    logger.info("Migrating schema: adding 'ai_verdict' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN ai_verdict TEXT"))
                if "worth_interest" not in existing_cols:
                    logger.info("Migrating schema: adding 'worth_interest' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN worth_interest BOOLEAN"))
                if "mpzp_zone" not in existing_cols:
                    logger.info("Migrating schema: adding 'mpzp_zone' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN mpzp_zone VARCHAR(250)"))
                if "mpzp_status" not in existing_cols:
                    logger.info("Migrating schema: adding 'mpzp_status' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN mpzp_status VARCHAR(50)"))
                if "flood_risk_zone" not in existing_cols:
                    logger.info("Migrating schema: adding 'flood_risk_zone' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN flood_risk_zone VARCHAR(100)"))
                if "gesut_networks" not in existing_cols:
                    logger.info("Migrating schema: adding 'gesut_networks' to listings table")
                    sync_conn.execute(text("ALTER TABLE listings ADD COLUMN gesut_networks TEXT"))
                tier1_cols = [
                    ("landslide_risk", "VARCHAR(100)"),
                    ("egib_building_status", "VARCHAR(100)"),
                    ("egib_soil_class", "VARCHAR(100)"),
                    ("noise_level_db", "FLOAT"),
                    ("noise_zone", "VARCHAR(100)"),
                    ("nature_protected_zone", "VARCHAR(250)"),
                    ("monument_zone", "VARCHAR(250)"),
                    ("cemetery_buffer_zone", "VARCHAR(100)"),
                    ("broadband_status", "VARCHAR(100)"),
                    ("broadband_details", "VARCHAR(250)"),
                    ("parcel_front_width_m", "FLOAT"),
                    ("parcel_length_m", "FLOAT"),
                    ("parcel_aspect_ratio", "FLOAT"),
                    ("parcel_shape_type", "VARCHAR(100)"),
                    ("terrain_slope_pct", "FLOAT"),
                    ("terrain_aspect", "VARCHAR(50)"),
                    ("walkability_pka_dist_m", "INTEGER"),
                    ("walkability_pka_name", "VARCHAR(150)"),
                    ("power_lines_risk", "VARCHAR(150)"),
                ]
                for col_name, col_type in tier1_cols:
                    if col_name not in existing_cols:
                        logger.info(f"Migrating schema: adding '{col_name}' to listings table")
                        sync_conn.execute(text(f"ALTER TABLE listings ADD COLUMN {col_name} {col_type}"))
        except Exception as e:
            logger.warning(f"Schema migration note: {e}")

    await conn.run_sync(_do_migrate)


async def init_db() -> None:
    """Initialize database tables and run lightweight migrations with contention retry."""
    engine = get_engine()
    logger.info("Initializing database tables...")
    max_retries = 5
    for attempt in range(max_retries):
        try:
            async with engine.begin() as conn:
                if "sqlite" in settings.DATABASE_URL:
                    await conn.execute(text("PRAGMA journal_mode=WAL;"))
                    await conn.execute(text("PRAGMA busy_timeout=60000;"))
                    await conn.execute(text("PRAGMA synchronous=NORMAL;"))
                await conn.run_sync(Base.metadata.create_all)
                await _migrate_sqlite_columns(conn)
            logger.info("Database tables initialized and up-to-date.")
            return
        except Exception as exc:
            if is_sqlite_lock_error(exc) and attempt < max_retries - 1:
                backoff = 0.5 * (2**attempt)
                logger.warning(f"[Database] SQLite contention during init_db ({exc}), retrying in {backoff:.2f}s...")
                await asyncio.sleep(backoff)
            else:
                raise
