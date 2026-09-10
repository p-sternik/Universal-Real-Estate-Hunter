import asyncio

import pytest

from src.models.enums import FinishCondition, HeatingType, SewerageType
from src.scrapers.otodom import OtodomScraper


def test_otodom_extract_next_data():
    scraper = OtodomScraper()

    dummy_html = """
    <!DOCTYPE html>
    <html>
      <head><title>Otodom Test</title></head>
      <body>
        <script id="__NEXT_DATA__" type="application/json">
          {"props": {"pageProps": {"data": {"searchAds": {"items": [{"id": 12345, "title": "Test House"}]}}}}}
        </script>
      </body>
    </html>
    """

    data = scraper._extract_next_data(dummy_html)
    assert data is not None
    assert "props" in data
    items = data["props"]["pageProps"]["data"]["searchAds"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == 12345


def test_clean_html_description():
    scraper = OtodomScraper()
    raw_html = "<p>Piękny dom <b>szeregowy</b>.</p><br/><p>Dojazd: asfalt.</p>"
    clean = scraper._clean_html_description(raw_html)
    assert "<p>" not in clean
    assert "Piękny dom szeregowy." in clean
    assert "Dojazd: asfalt." in clean


def _base_item():
    return {
        "id": 123,
        "slug": "test-slug",
        "title": "Testowy dom",
        "totalPrice": {"value": 500000},
        "areaInSquareMeters": 100,
        "location": {},
    }


def test_collect_ai_params():
    scraper = OtodomScraper()
    detail = {
        "enrichment": {
            "aiParamsList": [
                {"key": "construction_status", "value": "ready_to_use", "rejected": False},
                {"key": "construction_status", "value": "developer", "rejected": True},
                {"key": "heating_types", "value": "gas", "rejected": False},
                {"key": "media_types", "value": "sewage", "rejected": False},
            ]
        }
    }
    params = scraper._collect_ai_params(detail)
    assert params["construction_status"] == ["ready_to_use"]
    assert params["heating_types"] == ["gas"]
    assert params["media_types"] == ["sewage"]


@pytest.mark.asyncio
async def test_finish_condition_from_characteristics(monkeypatch):
    scraper = OtodomScraper()

    async def fake_detail(slug):
        return {
            "target": {"Area": "100"},
            "characteristics": [
                {"key": "construction_status", "value": "to_completion"},
            ],
        }

    monkeypatch.setattr(scraper, "fetch_listing_detail", fake_detail)
    listing = await scraper.parse_search_item(_base_item(), asyncio.Semaphore(1))
    assert listing.finish_condition == FinishCondition.DO_WYKONCZENIA


@pytest.mark.asyncio
async def test_finish_condition_from_ai_params(monkeypatch):
    scraper = OtodomScraper()

    async def fake_detail(slug):
        return {
            "target": {},
            "enrichment": {
                "aiParamsList": [
                    {"key": "construction_status", "value": "ready_to_use", "rejected": False},
                    {"key": "heating_types", "value": "gas", "rejected": False},
                    {"key": "media_types", "value": "sewage", "rejected": False},
                ]
            },
        }

    monkeypatch.setattr(scraper, "fetch_listing_detail", fake_detail)
    listing = await scraper.parse_search_item(_base_item(), asyncio.Semaphore(1))
    assert listing.finish_condition == FinishCondition.DO_ZAMIESZKANIA
    assert listing.heating == HeatingType.GAZOWE
    assert listing.sewerage == SewerageType.MIEJSKA


@pytest.mark.asyncio
async def test_finish_condition_prefers_target(monkeypatch):
    scraper = OtodomScraper()

    async def fake_detail(slug):
        return {
            "target": {"Construction_status": ["unfinished_close"]},
            "characteristics": [
                {"key": "construction_status", "value": "to_completion"},
            ],
        }

    monkeypatch.setattr(scraper, "fetch_listing_detail", fake_detail)
    listing = await scraper.parse_search_item(_base_item(), asyncio.Semaphore(1))
    assert listing.finish_condition == FinishCondition.SUROWY_ZAMKNIETY


@pytest.mark.asyncio
async def test_skip_detail_when_fresh(monkeypatch):
    scraper = OtodomScraper(skip_detail_urls={"https://www.otodom.pl/pl/oferta/test-slug"})
    called = False

    async def fake_detail(slug):
        nonlocal called
        called = True
        return {"target": {"Construction_status": ["to_completion"]}}

    monkeypatch.setattr(scraper, "fetch_listing_detail", fake_detail)
    listing = await scraper.parse_search_item(_base_item(), asyncio.Semaphore(1))

    assert called is False
    assert listing.skip_detail is True
    assert listing.finish_condition == FinishCondition.NIEOKRESLONY


def test_base_delay_throttle():
    scraper = OtodomScraper()
    assert scraper.delay(1.0) == 1.0
    scraper._throttle_multiplier = 2.0
    assert scraper.delay(0.4) == 0.8
