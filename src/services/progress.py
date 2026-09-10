from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn


class ProgressTracker:
    """
    Central progress tracker broadcasting state to:
    1. Rich terminal progress bars
    2. Web dashboard real-time API (/api/scrape/status)
    """

    def __init__(self):
        self.is_running = False
        self.current_portal = ""
        self.current_step = "Bezczynny"
        self.current_page = 0
        self.total_pages = 0
        self.items_scraped = 0
        self.items_qualified = 0
        self.duplicates_found = 0
        self.percentage = 0
        self.logs: list[dict[str, str]] = []
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        self._rich_progress: Progress | None = None
        self._task_id: Any | None = None
        self._session_started_at: datetime | None = None
        self._total_steps = 1
        self._portal_base_pct = 0
        self._portal_share = 85

    def start_session(self, total_portals: int = 3):
        self.is_running = True
        self.current_portal = ""
        self.current_step = "Inicjalizacja scrapingu..."
        self.items_scraped = 0
        self.items_qualified = 0
        self.duplicates_found = 0
        self.percentage = 5
        self.logs = []
        self._session_started_at = datetime.now(UTC)
        self._total_steps = max(total_portals, 1)
        self._portal_share = 85 / self._total_steps
        self._portal_base_pct = 0
        self.add_log("🚀 Rozpoczęto cykl scrapingu i analizy ofert.")

        try:
            self._rich_progress = Progress(
                SpinnerColumn(),
                TextColumn("[bold cyan]{task.description}"),
                BarColumn(bar_width=35),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
                console=Console(),
                transient=False,
            )
            self._rich_progress.start()
            self._task_id = self._rich_progress.add_task("Monitorowanie...", total=100)
        except Exception as e:
            logger.debug(f"Rich progress init skipped: {e}")

    def _refresh_rich(self):
        if self._rich_progress and self._task_id is not None:
            self._rich_progress.update(
                self._task_id,
                description=f"[{self.current_portal or '...'}] {self.current_step}",
                completed=self.percentage,
            )

    def update_portal(self, portal_name: str, current_page: int, total_pages: int, percent: int):
        self.current_portal = portal_name
        self.current_page = current_page
        self.total_pages = total_pages
        self._portal_base_pct = percent
        self.percentage = min(95, max(self.percentage, percent))
        self.current_step = f"Pobieranie {portal_name} (strona {current_page}/{total_pages})..."
        self.add_log(f"[{portal_name}] Pobieranie strony {current_page}/{total_pages}...")
        self._refresh_rich()

    def update_portal_page(
        self,
        page: int,
        total_pages: int,
        items_done: int = 0,
        items_total: int = 0,
        phase: str = "search",
    ):
        """Live progress within a single portal scrape (called by scrapers)."""
        self.current_page = page
        self.total_pages = max(total_pages, 1)
        frac = (page - 1) / self.total_pages
        if phase == "detail" and items_total > 0:
            frac += (items_done / items_total) / self.total_pages
        self.percentage = min(95, self._portal_base_pct + int(frac * self._portal_share))

        if phase == "detail":
            self.current_step = (
                f"Pobieranie {self.current_portal} · strona {page}/{self.total_pages} · "
                f"szczegóły {items_done}/{items_total}..."
            )
        else:
            self.current_step = (
                f"Pobieranie {self.current_portal} · strona {page}/{self.total_pages} · {items_done} ogłoszeń"
            )
        self._refresh_rich()

    def update_processing(self, done: int, total: int):
        """Progress during qualification/analysis of scraped listings."""
        self.current_step = f"Analiza ofert ({self.current_portal}): {done}/{total}..."
        self.percentage = min(95, self._portal_base_pct + int(self._portal_share))
        self._refresh_rich()

    def record_items(self, count: int, qualified: int = 0, duplicates: int = 0):
        self.items_scraped += count
        self.items_qualified += qualified
        self.duplicates_found += duplicates

    def add_log(self, message: str, level: str = "info"):
        now_str = datetime.now(UTC).strftime("%H:%M:%S")
        entry = {"time": now_str, "message": message, "level": level}
        self.logs.append(entry)
        if len(self.logs) > 60:
            self.logs.pop(0)

    def complete_session(self, summary: dict[str, Any]):
        self.is_running = False
        self.percentage = 100
        self.current_step = "Zakończono pomyślnie!"
        self.add_log(
            f"✅ Cykl zakończony. Pobrane: {summary.get('total_scraped', 0)}, "
            f"Nowe: {summary.get('new_listings', 0)}, Zakwalifikowane: {summary.get('qualified', 0)}"
        )

        if self._rich_progress and self._task_id is not None:
            self._rich_progress.update(
                self._task_id,
                description="[bold green]Ukończono!",
                completed=100,
            )
            self._rich_progress.stop()
            self._rich_progress = None

    def get_status_payload(self) -> dict[str, Any]:
        elapsed = 0
        if self.is_running and self._session_started_at:
            elapsed = int((datetime.now(UTC) - self._session_started_at).total_seconds())
        return {
            "is_running": self.is_running,
            "current_portal": self.current_portal,
            "current_step": self.current_step,
            "percentage": self.percentage,
            "current_page": self.current_page,
            "total_pages": self.total_pages,
            "elapsed_seconds": elapsed,
            "items_scraped": self.items_scraped,
            "items_qualified": self.items_qualified,
            "duplicates_found": self.duplicates_found,
            "logs": self.logs[-20:],
        }


# Global singleton tracker
global_tracker = ProgressTracker()
