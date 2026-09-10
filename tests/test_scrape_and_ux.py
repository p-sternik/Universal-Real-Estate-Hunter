import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

from src.models.enums import QualificationStatus
from src.models.listing import FilterResult, ListingSchema
from src.services.live_dashboard import LiveDashboardServer
from src.services.pipeline import ScraperPipeline
from src.services.progress import global_tracker
from src.storage import ListingRepository, get_session, init_db


@pytest.mark.asyncio
async def test_global_tracker_cancellation_flow():
    global_tracker.start_session(total_portals=2)
    assert global_tracker.is_running is True
    assert global_tracker.is_cancelled() is False

    global_tracker.request_cancel()
    assert global_tracker.is_cancelled() is True
    assert global_tracker.cancel_requested is True

    payload = global_tracker.get_status_payload()
    assert payload["is_running"] is True
    assert payload["cancel_requested"] is True
    assert any("🛑" in l["message"] for l in payload["logs"])

    global_tracker.cancel_session()
    assert global_tracker.is_running is False
    assert global_tracker.is_cancelled() is False

    final_payload = global_tracker.get_status_payload()
    assert final_payload["is_running"] is False
    assert "Zatrzymano" in final_payload["current_step"]


@pytest.mark.asyncio
async def test_pipeline_run_cycle_cooperative_cancellation():
    mock_scraper = AsyncMock()
    mock_scraper.name = "MockPortal"
    mock_scraper.max_pages = 1

    async def mock_scrape():
        global_tracker.request_cancel()
        return [
            ListingSchema(
                id="canc-1",
                portal="MockPortal",
                title="Test Cancellation",
                url="https://example.com/canc-1",
                price=500_000,
                price_per_m2=5_000,
                area_home=100.0,
                location_raw="Rzeszów",
            )
        ]

    mock_scraper.scrape = mock_scrape
    mock_scraper.close = AsyncMock()

    pipeline = ScraperPipeline(scrapers=[mock_scraper])

    with patch.object(pipeline, "process_listing", new_callable=AsyncMock) as mock_proc:
        summary = await pipeline.run_cycle()
        assert summary.get("cancelled") is True
        assert global_tracker.is_running is False
        mock_proc.assert_not_called()


@pytest.mark.asyncio
async def test_live_dashboard_scrape_endpoints_and_cancellation():
    await init_db()
    server = LiveDashboardServer(port=8089)

    async with TestClient(TestServer(server.app)) as client:
        # 1. Test scrape status when idle
        st_resp = await client.get("/api/scrape/status")
        assert st_resp.status == 200
        st_data = await st_resp.json()
        assert "is_running" in st_data
        assert "cancel_requested" in st_data
        assert "logs" in st_data

        # 2. Mock pipeline.run_cycle to simulate running background work
        async def slow_cycle(*args, **kwargs):
            global_tracker.start_session(total_portals=2)
            while not global_tracker.is_cancelled():
                await asyncio.sleep(0.05)
            global_tracker.cancel_session()
            return {"cancelled": True}

        with patch.object(ScraperPipeline, "run_cycle", side_effect=slow_cycle):
            # Trigger scrape -> should return 200 started immediately (non-blocking!)
            trig_resp = await client.post("/api/scrape")
            assert trig_resp.status == 200
            trig_data = await trig_resp.json()
            assert trig_data["status"] == "started"

            await asyncio.sleep(0.06)

            # Check status while running
            running_st = await client.get("/api/scrape/status")
            running_data = await running_st.json()
            assert running_data["is_running"] is True

            # Triggering again while running -> 409 already_running
            conflict_resp = await client.post("/api/scrape")
            assert conflict_resp.status == 409
            conflict_data = await conflict_resp.json()
            assert conflict_data["status"] == "already_running"

            # Cancel scrape
            cancel_resp = await client.post("/api/scrape/cancel")
            assert cancel_resp.status == 200
            cancel_data = await cancel_resp.json()
            assert cancel_data["status"] == "cancelling"

            # Wait for background task to complete cooperative cancellation
            await asyncio.sleep(0.12)
            after_cancel_st = await client.get("/api/scrape/status")
            after_data = await after_cancel_st.json()
            assert after_data["is_running"] is False


@pytest.mark.asyncio
async def test_live_dashboard_listings_includes_gunb_and_gesut():
    await init_db()
    async with get_session() as session:
        repo = ListingRepository(session)
        listing = ListingSchema(
            id="geo-gunb-test-1",
            portal="Otodom",
            title="Działka budowlana GUNB test",
            url="https://otodom.pl/oferta/geo-gunb-test-1",
            price=350_000,
            price_per_m2=350.0,
            area_home=100.0,
            area_plot=1000.0,
            latitude=50.0375,
            longitude=22.0047,
            location_raw="Rzeszów",
        )
        filt = FilterResult(
            is_qualified=True, status=QualificationStatus.QUALIFIED, passed_stage1=True, passed_stage2=True
        )
        model, _, _ = await repo.save_or_update(listing, filt)
        model.parcel_id = "181609_2.0001.2643/7"
        model.cadastral_area = 1000.0
        model.geoportal_url = "https://mapy.geoportal.gov.pl/imap/Imgp_2.html?identifyParcel=181609_2.0001.2643/7"
        await session.commit()

    server = LiveDashboardServer(port=8091)
    async with TestClient(TestServer(server.app)) as client:
        resp = await client.get("/api/listings")
        assert resp.status == 200
        data = await resp.json()
        item = next((x for x in data if x.get("portal_id") == "geo-gunb-test-1"), None)
        assert item is not None
        assert "identifyParcel=181609_2.0001.2643/7" in item["geoportal_url"]
        assert item["parcel_id"] == "181609_2.0001.2643/7"
        assert "land_audit" in item
        assert item["land_audit"]["search_packet"]["voivodeship"] == "Podkarpackie"
        assert item["land_audit"]["search_packet"]["parcel_short"] == "2643/7"
        assert "tco_audit" in item["land_audit"]
        assert "commute_audit" in item["land_audit"]
        assert "risk_shield" in item["land_audit"]
        assert "gesut_audit" in item["land_audit"]
        assert item["land_audit"]["tco_audit"]["total_acquisition_cost"] >= 350_000


@pytest.mark.asyncio
async def test_global_tracker_logging_categories_and_retention():
    """Verify log categorization, retention, and payload formatting."""
    tracker = global_tracker
    tracker.start_session(total_portals=1)

    tracker.add_log("📍 [Geokoder] Słocina: (50.04, 22.01) [precyzyjny punkt]", level="info", category="geo")
    tracker.add_log("🏛️ [Rejestry] Dom: działka 123/4 | FTTH: TAK", level="info", category="geo")
    tracker.add_log("❌ [Odrzucono] Działka: cena za wysoka", level="warning", category="rejected")
    tracker.add_log("🤖 [AI Audit] Gotowe dla Dom w 2.1s", level="info", category="ai")
    tracker.add_log("⭐ [Zakwalifikowano] Super dom (750 000 zł) — Wynik: 95 pkt", level="success", category="success")

    payload = tracker.get_status_payload()
    logs = payload["logs"]
    assert len(logs) >= 5

    categories = [l.get("category") for l in logs]
    assert "geo" in categories
    assert "rejected" in categories
    assert "ai" in categories
    assert "success" in categories


@pytest.mark.asyncio
async def test_sqlite_get_session_retry_on_locked(monkeypatch):
    """Verify get_session retries on SQLite database is locked error before succeeding."""
    from src.storage.database import get_session

    attempts = 0

    async def mock_commit():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            import sqlite3

            raise sqlite3.OperationalError("database is locked")

    async with get_session() as session:
        monkeypatch.setattr(session, "commit", mock_commit)

    # Commits twice failing with 'database is locked', then succeeds on 3rd attempt
    assert attempts == 3
