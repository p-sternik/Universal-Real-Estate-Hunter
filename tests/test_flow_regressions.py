"""Regression coverage for ingestion provenance, profile isolation and durability."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy import select, text

from config import settings
from src.filters import QualificationEngine
from src.filters.fingerprint import generate_physical_fingerprint
from src.services.config_manager import SearchConfig
from src.services.geocoder import NominatimGeocoder
from src.services.live_dashboard import LiveDashboardServer
from src.services.pipeline import ScraperPipeline
from src.storage.database import get_session, init_db
from src.storage.models import ListingModel, ListingProfileModel
from src.storage.repository import ListingRepository
from tests.test_filters import PermissiveProfile, create_sample_listing
from tests.test_pipeline import async_session as async_session
from tests.test_pipeline import make_listing, make_qualified_result, make_unqualified_result


@pytest.mark.asyncio
async def test_llm_failure_and_early_rejection_cannot_reuse_previous_json():
    engine = QualificationEngine(llm_enabled=True)
    engine.llm = MagicMock()
    engine.llm.last_model = "test-model"
    engine.llm.last_prompt_version = "test-version"
    engine.llm.last_result_json = {"summary": "first"}
    engine.llm.analyze_description = AsyncMock(side_effect=[{"summary": "first"}, None])
    listing = create_sample_listing(raw_description="Segment skrajny z garażem. Dojazd asfaltowy.")
    first = await engine.evaluate_listing(listing.model_copy(deep=True), profile=PermissiveProfile())
    assert first.llm_json == {"summary": "first"}
    failed = await engine.evaluate_listing(listing.model_copy(deep=True), profile=PermissiveProfile())
    assert failed.llm_json is None
    assert failed.llm_skip_reason == "provider_error"
    rejected = await engine.evaluate_listing(
        listing.model_copy(update={"price": 99_000_000}), profile=PermissiveProfile()
    )
    assert not rejected.is_qualified
    assert rejected.llm_json is None
    assert rejected.llm_skip_reason is None


@pytest.mark.asyncio
async def test_concurrent_llm_success_does_not_contaminate_a_failed_call():
    engine = QualificationEngine(llm_enabled=True)
    success_finished = asyncio.Event()
    engine.llm = MagicMock()
    engine.llm.last_result_json = {"summary": "success"}
    engine.llm.last_model = "test"
    engine.llm.last_prompt_version = "v1"

    async def analyze(listing, **kwargs):
        if listing.id == "failure":
            await success_finished.wait()
            await asyncio.sleep(0)
            return None
        success_finished.set()
        return {"summary": "success"}

    engine.llm.analyze_description = analyze
    listing = create_sample_listing(raw_description="Segment skrajny z garażem. Dojazd asfaltowy.")
    success, failure = await asyncio.gather(
        engine.evaluate_listing(listing.model_copy(update={"id": "success"}), profile=PermissiveProfile()),
        engine.evaluate_listing(listing.model_copy(update={"id": "failure"}), profile=PermissiveProfile()),
    )
    assert success.llm_json == {"summary": "success"}
    assert failure.llm_json is None
    assert failure.llm_skip_reason == "provider_error"


@pytest.mark.asyncio
async def test_search_hit_does_not_refresh_detail_timestamp(async_session):
    repo = ListingRepository(async_session)
    listing = make_listing()
    listing.detail_fetched_at = datetime.now(UTC) - timedelta(days=2)
    model, _, _ = await repo.save_or_update(listing, make_qualified_result())
    original = model.detail_fetched_at
    search_hit = listing.model_copy(update={"skip_detail": True, "detail_fetched_at": datetime.now(UTC)})
    await repo.save_or_update(search_hit, make_qualified_result())
    assert model.detail_fetched_at == original
    assert await repo.get_fresh_urls([listing.portal]) == []
    refreshed = listing.model_copy(update={"detail_fetched_at": datetime.now(UTC)})
    await repo.save_or_update(refreshed, make_qualified_result())
    assert await repo.get_fresh_urls([listing.portal]) == [listing.url]


def test_skipped_details_restore_full_description_over_search_excerpt():
    from src.models.listing import restore_cached_details

    listing = make_listing().model_copy(update={"skip_detail": True, "raw_description": "Krótki fragment"})
    old = MagicMock(raw_description="Pełny opis i istotne zastrzeżenia", latitude=None, longitude=None)
    # Use a real stored model to avoid fake values for nullable enum fields.
    old = ListingModel(raw_description=old.raw_description)
    restore_cached_details(listing, old)
    assert listing.raw_description == "Pełny opis i istotne zastrzeżenia"


@pytest.mark.parametrize(
    "street, address, expected",
    [
        ("Długa", {"road": "Długa", "city": "Rzeszów"}, False),
        ("Długa 12", {"road": "Długa", "city": "Rzeszów", "house_number": "14"}, False),
        ("Długa 12", {"road": "Długa", "city": "Kraków", "house_number": "12"}, False),
        ("Długa 12", {"road": "Krótka", "city": "Rzeszów", "house_number": "12"}, False),
        ("Długa 12", {"road": "Długa", "city": "Rzeszów", "house_number": "12"}, True),
    ],
)
def test_geocoder_requires_matching_building_and_city(street, address, expected):
    assert NominatimGeocoder._is_building_match(street, "Rzeszów", {"address": address}) is expected


@pytest.mark.asyncio
async def test_street_geocode_and_cached_street_are_approximate():
    coder = NominatimGeocoder()
    coder._rate_limited_query = AsyncMock(
        return_value={"lat": "50.04", "lon": "22", "address": {"road": "Długa", "city": "Rzeszów"}}
    )

    async def remember(session, key, lat, lon, display):
        coder._mem_cache[key] = (lat, lon, display)

    coder.set_cache = remember
    first = await coder.geocode(street="Długa", city="Rzeszów")
    second = await coder.geocode(street="Długa", city="Rzeszów")
    assert first == second == (50.04, 22.0, False)
    assert coder._rate_limited_query.await_count == 1


def test_automatic_relisting_requires_precise_property_identity():
    args = {"area_home": 100, "city": "Rzeszów", "rooms": 4, "require_precise": True}
    assert generate_physical_fingerprint(**args) is None
    assert generate_physical_fingerprint(**args, street="Długa") is None
    assert generate_physical_fingerprint(**args, street="Długa 12", category="mieszkanie") is None
    assert generate_physical_fingerprint(**args, street="Długa 12/3", category="mieszkanie") is not None
    assert generate_physical_fingerprint(**args, street="Długa 12") != generate_physical_fingerprint(
        **args, street="Długa 14"
    )


@pytest.mark.asyncio
async def test_profile_qualification_notification_and_reset_are_independent(async_session):
    repo = ListingRepository(async_session)
    listing = make_listing().model_copy(update={"profile_id": "a", "profile_name": "A"})
    model, _, _ = await repo.save_or_update(listing, make_qualified_result(score=80))
    await repo.mark_as_notified(model.id, "a")
    await repo.save_or_update(
        listing.model_copy(update={"profile_id": "b", "profile_name": "B"}), make_unqualified_result(score=10)
    )
    first = await repo.get_profile_result(model.id, "a")
    second = await repo.get_profile_result(model.id, "b")
    assert first.result["is_qualified"] is True
    assert first.result["qualification_score"] == 80
    assert first.notified_at is not None
    assert second.result["is_qualified"] is False
    assert second.notified_at is None
    assert model.profile_id == "a"
    assert model.is_qualified is True
    assert model.qualification_score == 80
    assert await repo.delete_by_profile("a") == 1
    remaining = await repo.get_by_url(listing.url)
    assert remaining is not None
    assert remaining.profile_id == "b"
    assert remaining.is_qualified is False
    assert remaining.qualification_score == 10
    assert await repo.get_profile_result(model.id, "b") is not None
    assert await repo.get_profile_result(model.id, "a") is None


@pytest.mark.asyncio
async def test_legacy_profile_migration_is_idempotent():
    await init_db()
    async with get_session(write=True) as session:
        item = ListingModel(
            portal="Otodom",
            portal_id="legacy-profile-flow",
            url="https://otodom.pl/legacy-profile-flow",
            title="Legacy",
            price=1,
            price_per_m2=1,
            area_home=1,
            profile_id="legacy",
            qualification_score=42,
            is_qualified=True,
            pros=["Zaleta"],
        )
        session.add(item)
        await session.flush()
        listing_id = item.id
    await init_db()
    await init_db()
    async with get_session() as session:
        rows = (
            (await session.execute(select(ListingProfileModel).where(ListingProfileModel.listing_id == listing_id)))
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].profile_id == "legacy"
        assert rows[0].result["qualification_score"] == 42
        assert rows[0].result["pros"] == ["Zaleta"]


@pytest.mark.asyncio
async def test_profile_api_pagination_and_shared_reset(async_session, monkeypatch):
    import src.services.live_dashboard as dashboard

    @asynccontextmanager
    async def session_context(**kwargs):
        yield async_session
        await async_session.commit()

    monkeypatch.setattr(dashboard, "get_session", session_context)
    repo = ListingRepository(async_session)
    listing = make_listing().model_copy(update={"profile_id": "a", "profile_name": "A"})
    item, _, _ = await repo.save_or_update(listing, make_qualified_result(score=80))
    await repo.save_or_update(
        listing.model_copy(update={"profile_id": "b", "profile_name": "B"}), make_unqualified_result(score=10)
    )
    another = listing.model_copy(update={"id": "another", "url": listing.url + "-another"})
    await repo.save_or_update(another, make_qualified_result(score=70))
    await async_session.commit()
    server = LiveDashboardServer()
    async with TestClient(TestServer(server.app)) as client:
        a = await (await client.get("/api/listings?profile=a&limit=1")).json()
        b = await (await client.get("/api/listings?profile=b")).json()
        assert len(a) == 1
        assert len(b) == 1
        assert b[0]["is_qualified"] is False
        assert b[0]["qualification_score"] == 10
        assert b[0]["profile_results"]["a"]["qualification_score"] == 80
        detail = await (await client.get(f"/api/listings/{item.id}?profile=a")).json()
        assert detail["is_qualified"] is True
        assert detail["qualification_score"] == 80
        assert len(await (await client.get("/api/listings?limit=1&offset=1")).json()) == 1
        assert await (await client.get("/api/listings?limit=1&offset=2")).json() == []
        assert (await client.get("/api/listings?limit=bad")).status == 400


@pytest.mark.asyncio
async def test_dashboard_auth_and_cross_origin_write_protection(monkeypatch):
    monkeypatch.setattr(settings, "DASHBOARD_USERNAME", "owner")
    monkeypatch.setattr(settings, "DASHBOARD_PASSWORD", "test-password")
    server = LiveDashboardServer()
    async with TestClient(TestServer(server.app)) as client:
        assert (await client.get("/api/config")).status == 401
        assert (await client.get("/api/config", headers={"Authorization": "Basic invalid"})).status == 401
        auth = aiohttp.BasicAuth("owner", "test-password")
        assert (await client.get("/api/config", auth=auth)).status == 200
        blocked = await client.post(
            "/api/data/reset", auth=auth, headers={"Origin": "https://untrusted.example"}, json={"confirm": True}
        )
        assert blocked.status == 403
        assert (await client.get("/healthz")).status == 200


def test_valuation_cache_depends_on_area_finish_and_day(monkeypatch):
    import src.services.live_dashboard as dashboard

    item = ListingModel(
        price=1_000_000, area_home=100, finish_condition="pod_klucz", first_seen_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    stamp = LiveDashboardServer._valuation_stamp(item, "med", "cap", 0, 0, 1)
    item.area_home = 120
    assert LiveDashboardServer._valuation_stamp(item, "med", "cap", 0, 0, 1) != stamp
    item.area_home = 100
    item.finish_condition = "do_wykonczenia"
    assert LiveDashboardServer._valuation_stamp(item, "med", "cap", 0, 0, 1) != stamp

    class NextDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(UTC) + timedelta(days=1)

    item.finish_condition = "pod_klucz"
    monkeypatch.setattr(dashboard, "datetime", NextDay)
    assert LiveDashboardServer._valuation_stamp(item, "med", "cap", 0, 0, 1) != stamp


@pytest.mark.asyncio
async def test_sqlite_write_lock_covers_flush_and_releases_on_cancellation():
    await init_db()
    entered = asyncio.Event()

    async def second_writer():
        async with get_session(write=True) as session:
            entered.set()
            await session.execute(text("SELECT 1"))

    async with get_session(write=True) as session:
        session.add(
            ListingModel(
                portal="Otodom",
                portal_id="write-lock-flow",
                url="https://otodom.pl/write-lock-flow",
                title="Lock",
                price=1,
                price_per_m2=1,
                area_home=1,
            )
        )
        await session.flush()
        task = asyncio.create_task(second_writer())
        await asyncio.sleep(0.01)
        assert not entered.is_set()
    await asyncio.wait_for(task, timeout=2)
    with pytest.raises(asyncio.CancelledError):
        async with get_session(write=True):
            raise asyncio.CancelledError
    async with get_session(write=True) as session:
        await session.execute(text("SELECT 1"))


@pytest.mark.asyncio
async def test_expired_memory_spatial_cache_is_not_returned():
    from src.services import spatial_cache

    spatial_cache._memory_cache["flow-expired"] = (datetime.now(UTC) - timedelta(days=1), {"stale": True})
    assert await spatial_cache.get_spatial_cache("flow-expired") is None
    assert "flow-expired" not in spatial_cache._memory_cache


@pytest.mark.asyncio
async def test_cycle_keeps_other_listings_when_one_analysis_fails(monkeypatch):
    import src.filters
    import src.services.pipeline as pipeline_module
    from src.services.config_manager import config_manager

    cfg = SearchConfig(llm_analysis_enabled=False)
    cfg.notifications.enabled = False
    monkeypatch.setattr(config_manager, "get_config", lambda: cfg)
    scraper = MagicMock(name="scraper")
    scraper.name = "Otodom"
    scraper.max_pages = 1
    listings = [
        make_listing().model_copy(update={"id": name, "url": f"https://otodom.pl/flow-{name}"})
        for name in ("ok-first", "bad", "ok-last")
    ]
    scraper.scrape = AsyncMock(return_value=listings)
    scraper.close = AsyncMock()
    pipeline = ScraperPipeline(scrapers=[scraper])
    engine = MagicMock()
    engine.precheck_stage1.return_value = (True, [], None)
    engine.precheck_stage2.return_value = False
    engine.llm_calls = engine.llm_successes = engine.llm_failures = 0

    async def evaluate(listing, **kwargs):
        if listing.id == "bad":
            raise ValueError("broken listing")
        return make_qualified_result()

    engine.evaluate_listing = evaluate
    monkeypatch.setattr(src.filters, "QualificationEngine", lambda **kwargs: engine)
    monkeypatch.setattr(pipeline_module, "audit_and_apply_spatial_data", AsyncMock(return_value={}))
    monkeypatch.setattr(pipeline, "backfill_existing_spatial_data", AsyncMock(return_value=0))
    summary = await pipeline._do_run_cycle()
    assert summary["processing_errors"] == 1
    assert summary["new_listings"] == 2
    async with get_session() as session:
        repo = ListingRepository(session)
        assert await repo.get_by_url(listings[0].url) is not None
        assert await repo.get_by_url(listings[1].url) is None
        assert await repo.get_by_url(listings[2].url) is not None


@pytest.mark.asyncio
async def test_persist_batch_isolates_a_failed_record(async_session, monkeypatch):
    import src.services.pipeline as pipeline_module
    from src.services.config_manager import config_manager

    cfg = SearchConfig()
    cfg.notifications.enabled = False
    monkeypatch.setattr(config_manager, "get_config", lambda: cfg)

    @asynccontextmanager
    async def session_context(**kwargs):
        yield async_session
        await async_session.commit()

    monkeypatch.setattr(pipeline_module, "get_session", session_context)
    original = ListingRepository.save_or_update

    async def save(repo, listing, *args, **kwargs):
        if listing.id == "bad":
            raise ValueError("bad record")
        return await original(repo, listing, *args, **kwargs)

    monkeypatch.setattr(ListingRepository, "save_or_update", save)
    pending = []
    for name in ("ok-first", "bad", "ok-last"):
        listing = make_listing().model_copy(update={"id": name, "url": f"https://otodom.pl/batch-{name}"})
        pending.append(
            (
                listing,
                {
                    "is_new": False,
                    "qualified": True,
                    "_deferred_save": {
                        "listing": listing,
                        "filter_result": make_qualified_result(),
                        "is_exact_coords": True,
                    },
                },
            )
        )
    await ScraperPipeline(scrapers=[MagicMock()])._persist_batch(pending, None, {})
    assert pending[1][1]["processing_error"] == "bad record"
    assert pending[0][1]["is_new"] is True
    assert pending[2][1]["is_new"] is True
    repo = ListingRepository(async_session)
    assert await repo.get_by_url(pending[0][0].url) is not None
    assert await repo.get_by_url(pending[2][0].url) is not None


@pytest.mark.asyncio
async def test_backfill_applies_new_risk_without_stacking_old_bonus(async_session, monkeypatch):
    import src.services.pipeline as pipeline_module

    pipeline = ScraperPipeline(scrapers=[MagicMock()])
    model = ListingModel(
        portal="Otodom",
        portal_id="partial-spatial",
        url="https://otodom.pl/partial-spatial",
        title="Spatial",
        price=1,
        price_per_m2=1,
        area_home=100,
        latitude=50,
        longitude=22,
        is_exact_coords=True,
        broadband_status="ŚWIATŁOWÓD_AKTYWNY",
        qualification_score=65,
    )
    old_delta, old_pros, old_cons = pipeline.engine.apply_spatial_findings(
        listing=model, score=0, pros=[], cons=[], geo_audit={}
    )
    assert old_delta == 5
    model.pros, model.cons = old_pros, old_cons
    async_session.add(model)
    await async_session.commit()

    async def audit(item, **kwargs):
        item.terrain_slope_pct = 10
        return {}

    monkeypatch.setattr(pipeline_module, "audit_and_apply_spatial_data", audit)
    repo = ListingRepository(async_session)
    assert await pipeline.backfill_existing_spatial_data(async_session, repo) == 1
    assert model.qualification_score == 50
    model.spatial_audited_at = datetime.now(UTC) - timedelta(days=2)
    await async_session.commit()
    assert await pipeline.backfill_existing_spatial_data(async_session, repo) == 1
    assert model.qualification_score == 50


def test_precise_fingerprint_preserves_the_full_street_name():
    args = {"area_home": 100, "city": "Rzeszów", "require_precise": True}
    assert generate_physical_fingerprint(**args, street="Wojska Polskiego 12") != generate_physical_fingerprint(
        **args, street="Żołnierza Polskiego 12"
    )


@pytest.mark.asyncio
async def test_pipeline_does_not_trust_a_precomputed_weak_fingerprint(async_session, monkeypatch):
    import src.services.pipeline as pipeline_module

    repo = ListingRepository(async_session)
    repo.find_relist_by_physical_fingerprint = AsyncMock()
    listing = make_listing().model_copy(
        update={"street": None, "city": "Rzeszów", "physical_fingerprint": "phys_v2_coarse"}
    )
    monkeypatch.setattr(pipeline_module, "audit_and_apply_spatial_data", AsyncMock(return_value={}))
    pipeline = ScraperPipeline(scrapers=[MagicMock()])
    pipeline.llm_analysis_enabled = False
    result = await pipeline.process_listing(listing, repo, defer_save=True)
    assert listing.physical_fingerprint is None
    assert not result.get("relisted")
    repo.find_relist_by_physical_fingerprint.assert_not_awaited()


@pytest.mark.asyncio
async def test_repository_preserves_coordinate_uncertainty(async_session):
    repo = ListingRepository(async_session)
    approximate = make_listing().model_copy(update={"is_exact_coords": False})
    model, _, _ = await repo.save_or_update(approximate, make_qualified_result())
    assert model.is_exact_coords is False
    await repo.save_or_update(approximate.model_copy(update={"is_exact_coords": True}), make_qualified_result())
    assert model.is_exact_coords is True
    await repo.save_or_update(approximate, make_qualified_result())
    assert model.is_exact_coords is False
