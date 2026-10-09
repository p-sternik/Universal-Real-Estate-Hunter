import asyncio
import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from src.services.config_manager import config_manager
from src.services.pipeline import ScraperPipeline
from src.storage import init_db


def get_heartbeat_path() -> Path:
    from config import settings

    db_url = settings.DATABASE_URL
    if "sqlite" in db_url and db_url.startswith("sqlite+aiosqlite:///"):
        path = db_url.replace("sqlite+aiosqlite:///", "")
        p = Path(path)
        if p.parent and str(p.parent) not in (".", ""):
            return p.parent / ".scheduler_heartbeat.json"
    return Path("data") / ".scheduler_heartbeat.json"


def write_heartbeat(status: str = "running", interval_minutes: int = 20) -> None:
    try:
        p = get_heartbeat_path().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "status": status,
            "interval_minutes": interval_minutes,
            "timestamp": datetime.now(UTC).isoformat(),
            "time_epoch": time.time(),
        }
        temp_p = p.parent / f"{p.name}.tmp.{os.getpid()}"
        temp_p.write_text(json.dumps(payload), encoding="utf-8")
        temp_p.replace(p)
    except Exception as e:
        logger.debug(f"[Scheduler] Failed to write heartbeat: {e}")


def is_scheduler_active(max_age_seconds: float = 60.0) -> bool:
    try:
        p = get_heartbeat_path()
        if not p.exists():
            return False
        content = p.read_text(encoding="utf-8")
        data = json.loads(content)
        if data.get("status") == "stopped":
            return False
        age = time.time() - float(data.get("time_epoch", 0.0))
        return age <= max_age_seconds
    except Exception:
        return False


class SchedulerRunner:
    """
    Manages periodic execution of the scraping & analytical pipeline.
    Supports dynamic intervals (day vs night mode), CLI overrides,
    and runtime configuration changes from the web dashboard.
    """

    def __init__(
        self,
        interval_minutes: int | None = None,
        profile: str | None = None,
        idle_poll_seconds: float = 15.0,
    ):
        self._cli_interval = interval_minutes
        self.target_profile = profile
        self.idle_poll_seconds = idle_poll_seconds
        self.pipeline = ScraperPipeline()
        self.running = False
        self._shutdown_event = asyncio.Event()

    def is_enabled(self) -> bool:
        """Dashboard master switch; an explicit CLI interval always means 'run'."""
        if self._cli_interval is not None and self._cli_interval > 0:
            return True
        try:
            return bool(config_manager.get_config().scheduler.enabled)
        except Exception as e:
            logger.debug(f"[Scheduler] Could not read scheduler switch: {e}")
            return True

    def get_effective_interval(self) -> int:
        """Returns the effective interval in minutes, respecting CLI override and night mode."""
        if self._cli_interval is not None and self._cli_interval > 0:
            return self._cli_interval
        try:
            cfg = config_manager.get_config()
            return cfg.scheduler.get_current_interval_minutes()
        except Exception as e:
            logger.debug(f"[Scheduler] Could not read scheduler config: {e}")
            return 20

    async def _job_wrapper(self):
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            interval = self.get_effective_interval()
            prof_str = f" dla profilu '{self.target_profile}'" if self.target_profile else ""
            logger.info(f"[Scheduler] Uruchamianie cyklu scrapowania (aktywny interwał: {interval}m){prof_str}...")
            write_heartbeat(status="scraping", interval_minutes=interval)
            heartbeat_task = asyncio.create_task(self._refresh_scraping_heartbeat())
            await self.pipeline.run_cycle(target_profile=self.target_profile)
        except Exception as e:
            logger.error("[Scheduler] Nieoczekiwany błąd podczas cyklu: {}", e, exc_info=True)
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _refresh_scraping_heartbeat(self) -> None:
        """Keep the daemon heartbeat fresh while a potentially long cycle runs."""
        refresh_seconds = min(max(self.idle_poll_seconds, 1.0), 30.0)
        while True:
            await asyncio.sleep(refresh_seconds)
            write_heartbeat(status="scraping", interval_minutes=self.get_effective_interval())

    def stop(self):
        logger.info("[Scheduler] Otrzymano sygnał zatrzymania.")
        self.running = False
        self._shutdown_event.set()
        write_heartbeat(status="stopped", interval_minutes=self.get_effective_interval())

    async def start(self):
        await init_db()
        self.running = True

        while self.running:
            if not self.is_enabled():
                logger.info(
                    "[Scheduler] Harmonogram wyłączony w konfiguracji — daemon wstrzymuje cykle "
                    "(oczekiwanie na włączenie w panelu lub sygnał zatrzymania)..."
                )
                while self.running and not self.is_enabled():
                    write_heartbeat(status="disabled", interval_minutes=self.get_effective_interval())
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=self.idle_poll_seconds)
                        self.running = False
                        break
                    except TimeoutError:
                        pass
                if not self.running:
                    break
                logger.info("[Scheduler] Wykryto włączenie harmonogramu — rozpoczynam cykle scrapowania.")

            init_interval = self.get_effective_interval()
            logger.info(f"[Scheduler] Uruchomiono harmonogram zadań. Aktualny interwał: {init_interval} minut.")

            # Natychmiastowy pierwszy cykl po uruchomieniu / włączeniu
            await self._job_wrapper()

            # Pętla cykliczna z dynamicznym sprawdzaniem interwału
            while self.running and self.is_enabled():
                interval = self.get_effective_interval()
                logger.info(f"[Scheduler] Oczekiwanie na następny cykl: {interval} minut...")
                target_mono = time.monotonic() + (interval * 60)

                while self.running and self.is_enabled() and time.monotonic() < target_mono:
                    write_heartbeat(status="waiting", interval_minutes=interval)
                    current_interval = self.get_effective_interval()
                    if current_interval != interval:
                        diff_seconds = (current_interval - interval) * 60
                        target_mono = max(time.monotonic(), target_mono + diff_seconds)
                        interval = current_interval
                        logger.info(f"[Scheduler] Wykryto zmianę interwału: nowy interwał to {interval} minut.")

                    sleep_chunk = min(self.idle_poll_seconds, max(0.1, target_mono - time.monotonic()))
                    try:
                        await asyncio.wait_for(self._shutdown_event.wait(), timeout=sleep_chunk)
                        self.running = False
                        break
                    except TimeoutError:
                        pass

                if not self.running or not self.is_enabled():
                    break

                await self._job_wrapper()

        write_heartbeat(status="stopped", interval_minutes=self.get_effective_interval())
        logger.info("[Scheduler] Harmonogram zadań zakończył pracę pomyślnie.")
