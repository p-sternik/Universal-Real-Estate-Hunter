import shutil
import subprocess
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse

import pytest
from aiohttp.test_utils import TestClient, TestServer
from pydantic import ValidationError

from src.filters.stage1_hard_rules import Stage1Filter
from src.models.enums import PropertyCategory
from src.models.listing import ListingSchema
from src.scrapers.otodom import OtodomScraper
from src.services.config_manager import ConfigManager, ScraperConfig, SearchProfile
from src.services.live_dashboard import LiveDashboardServer


@pytest.mark.parametrize("category", ["mieszkanie", "dzialka"])
def test_new_non_house_profile_has_no_house_area_limits(category: Literal["mieszkanie", "dzialka"]) -> None:
    profile = SearchProfile(category=category)
    assert profile.min_area_home is None
    assert profile.max_area_home is None
    assert profile.min_area_plot is None


@pytest.mark.parametrize("url_method", ["get_otodom_url", "get_olx_url"])
def test_zero_radius_survives_portal_url_generation(url_method: str) -> None:
    profile = SearchProfile(distance_radius=0)
    query = parse_qs(urlparse(getattr(profile, url_method)()).query)
    key = "distanceRadius" if url_method == "get_otodom_url" else "search[dist]"
    assert query[key] == ["0"]


@pytest.mark.parametrize(
    "values",
    [
        {"min_price": 900000, "max_price": 500000},
        {"min_area_home": -10},
        {"max_area_home": float("inf")},
        {"min_parcel_front_m": float("nan")},
        {"category": "unknown"},
        {"name": " "},
        {"city": " "},
    ],
)
def test_invalid_profile_is_rejected(values: dict) -> None:
    with pytest.raises(ValidationError):
        SearchProfile(**values)


def test_apartment_supports_basement_and_unlimited_budget() -> None:
    profile = SearchProfile(category="mieszkanie", min_floor=-1, max_floor=0, max_price=None)
    assert profile.min_floor == -1
    assert profile.max_floor == 0
    assert "priceMax=" not in profile.get_otodom_url()


@pytest.mark.parametrize("delay", [0.0, 0.5, 3.0])
def test_configured_scraper_delay_retains_adaptive_throttling(delay: float) -> None:
    scraper = OtodomScraper()
    scraper.request_delay_seconds = delay
    scraper._throttle_multiplier = 2.0
    assert scraper.delay(1.0) == delay * 2.0


@pytest.mark.parametrize("delay", [-1, 31, float("inf")])
def test_invalid_portal_delay_is_rejected(delay: float) -> None:
    with pytest.raises(ValidationError):
        ScraperConfig(delay_seconds=delay)


@pytest.mark.asyncio
async def test_invalid_settings_api_preserves_saved_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ConfigManager(tmp_path / "settings.json")
    manager.get_config()
    before = manager.get_config().model_dump()
    monkeypatch.setattr("src.services.live_dashboard.config_manager", manager)
    server = LiveDashboardServer()
    profile = dict(before["profiles"][0], min_price=900000, max_price=100000)
    async with TestClient(TestServer(server.app)) as client:
        response = await client.post("/api/config", json={"profiles": [profile]})
        assert response.status == 400
        error = await response.json()
        assert error["fields"][0]["field"] == "profiles.0"
    assert manager.get_config().model_dump() == before


def test_settings_form_behaviour_in_node() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node is required for settings form regression checks")
        return
    result = subprocess.run(
        [node, str(Path(__file__).with_name("settings-workspace.cjs"))],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_settings_template_has_unique_ids_and_no_dead_delay_control() -> None:
    from bs4 import BeautifulSoup

    template = Path("src/services/templates/dashboard.html").read_text(encoding="utf-8")
    root = BeautifulSoup(template, "html.parser").find(id="configModal")
    assert root is not None
    ids = [element["id"] for element in root.find_all(id=True)]
    assert len(ids) == len(set(ids))
    assert "cfgRequestDelay" not in ids
    for suffix in ("Otodom", "Olx", "Nieruchomosci", "Morizon"):
        assert f"cfgDelay{suffix}" in ids
    assert root.find(id="cfgResetScope") is not None


def test_apartment_year_filter_is_enforced() -> None:
    profile = SearchProfile(category="mieszkanie", min_year_built=2010)
    listing = ListingSchema(
        id="old-apartment",
        portal="Otodom",
        title="Mieszkanie",
        url="https://otodom.pl/old-apartment",
        category=PropertyCategory.MIESZKANIE,
        price=500000,
        price_per_m2=10000,
        area_home=50,
        location_raw="Rzeszów",
        year_built=1990,
    )
    passed, reasons, _ = Stage1Filter(profile=profile).evaluate(listing)
    assert not passed
    assert any("Rok budowy" in reason for reason in reasons)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"profiles": []}, {"profiles": [{"id": "duplicate"}, {"id": "duplicate"}]}])
async def test_settings_api_rejects_empty_or_duplicate_profiles(
    payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = ConfigManager(tmp_path / "settings.json")
    before = manager.get_config().model_dump()
    monkeypatch.setattr("src.services.live_dashboard.config_manager", manager)
    server = LiveDashboardServer()
    async with TestClient(TestServer(server.app)) as client:
        response = await client.post("/api/config", json=payload)
        assert response.status == 400
    assert manager.get_config().model_dump() == before
