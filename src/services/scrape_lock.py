import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from config import settings

_scrape_lock_instance: "ScrapeLock | None" = None


def get_default_lock_path() -> str:
    """Resolve lockfile path inside the database directory (shared across containers)."""
    db_url = settings.DATABASE_URL
    if "sqlite" in db_url and db_url.startswith("sqlite+aiosqlite:///"):
        path = db_url.replace("sqlite+aiosqlite:///", "")
        p = Path(path)
        if p.parent:
            return str(p.parent / ".scrape.lock")
    return str(Path("data") / ".scrape.lock")


class ScrapeLock:
    """
    Cross-process & cross-container file lock ensuring only one scraping cycle runs at a time.
    Uses POSIX fcntl.flock on Linux/Docker and msvcrt.locking on Windows.
    Kernel automatically cleans locks if a process dies unexpectedly.
    """

    def __init__(self, lock_path: str | None = None):
        self.lock_path = lock_path or get_default_lock_path()
        self._fd: int | None = None

    def acquire(self, metadata: dict[str, Any] | None = None) -> bool:
        """Attempts to acquire exclusive lock immediately. Returns True if acquired, False otherwise."""
        Path(self.lock_path).resolve().parent.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                import msvcrt

                self._fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT | os.O_BINARY)
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                self._fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o666)
                fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            meta = {
                "pid": os.getpid(),
                "host": os.environ.get("HOSTNAME", "localhost"),
                "locked_at": datetime.now(UTC).isoformat(),
                **(metadata or {}),
            }
            data = json.dumps(meta).encode("utf-8")
            os.ftruncate(self._fd, 0)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, data)
            return True
        except (BlockingIOError, PermissionError, OSError):
            if self._fd is not None:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None
            return False

    def release(self) -> None:
        """Releases the held lock and closes file descriptor."""
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            except Exception as e:
                logger.debug(f"[ScrapeLock] Release notice: {e}")
            finally:
                try:
                    os.close(self._fd)
                except Exception:
                    pass
                self._fd = None

    def is_locked(self) -> bool:
        """Checks if another process currently holds the lock."""
        if self._fd is not None:
            return True
        p = Path(self.lock_path)
        if not p.exists():
            return False
        # Probe acquire
        if self.acquire():
            self.release()
            return False
        return True

    def get_lock_info(self) -> dict[str, Any] | None:
        """Reads lock metadata if file exists."""
        p = Path(self.lock_path)
        if not p.exists():
            return None
        try:
            content = p.read_text(encoding="utf-8").strip()
            if content:
                return json.loads(content)
        except Exception:
            pass
        return None


def get_scrape_lock() -> ScrapeLock:
    """Singleton getter for scraper file lock."""
    global _scrape_lock_instance
    if _scrape_lock_instance is None:
        _scrape_lock_instance = ScrapeLock()
    return _scrape_lock_instance
