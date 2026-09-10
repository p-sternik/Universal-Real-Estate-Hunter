import asyncio

from loguru import logger

from config import settings
from src.services.config_manager import config_manager
from src.services.pipeline import ScraperPipeline


class SchedulerRunner:
    """
    Manages periodic execution of the scraping & analytical pipeline.
    Supports dynamic intervals (day vs night mode), CLI overrides,
    and runtime configuration changes from the web dashboard.
    """

    def __init__(self, interval_minutes: int | None = None, profile: str | None = None):
        self._cli_interval = interval_minutes
        self.target_profile = profile
        self.pipeline = ScraperPipeline()
        self.running = False
        self._shutdown_event = asyncio.Event()

    def get_effective_interval(self) -> int:
        """Returns the effective interval in minutes, respecting CLI override and night mode."""
        if self._cli_interval is not None and self._cli_interval > 0:
            return self._cli_interval
        try:
            cfg = config_manager.get_config()
            return cfg.scheduler.get_current_interval_minutes()
        except Exception as e:
            logger.debug(f"[Scheduler] Could not read scheduler config: {e}")
            return settings.CHECK_INTERVAL_MINUTES

    async def _job_wrapper(self):
        try:
            interval = self.get_effective_interval()
            prof_str = f" dla profilu '{self.target_profile}'" if self.target_profile else ""
            logger.info(f"[Scheduler] Uruchamianie cyklu scrapowania (aktywny interwał: {interval}m){prof_str}...")
            await self.pipeline.run_cycle(target_profile=self.target_profile)
        except Exception as e:
            logger.error(f"[Scheduler] Nieoczekiwany błąd podczas cyklu: {e}", exc_info=True)

    def stop(self):
        logger.info("[Scheduler] Otrzymano sygnał zatrzymania.")
        self.running = False
        self._shutdown_event.set()

    async def start(self):
        self.running = True
        init_interval = self.get_effective_interval()
        logger.info(f"[Scheduler] Uruchomiono harmonogram zadań. Aktualny interwał: {init_interval} minut.")

        # Natychmiastowy pierwszy cykl
        await self._job_wrapper()

        while self.running:
            interval = self.get_effective_interval()
            logger.info(f"[Scheduler] Oczekiwanie na następny cykl: {interval} minut...")
            try:
                await asyncio.wait_for(
                    self._shutdown_event.wait(),
                    timeout=interval * 60,
                )
                break
            except TimeoutError:
                if self.running:
                    await self._job_wrapper()

        logger.info("[Scheduler] Harmonogram zadań zakończył pracę pomyślnie.")
