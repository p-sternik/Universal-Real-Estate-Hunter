import os
import pytest
import pytest_asyncio
from aiohttp.test_utils import TestClient, TestServer
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.enums import BuildingType, QualificationStatus, SegmentSubtype, UserCRMStatus
from src.models.listing import FilterResult, ListingSchema
from src.services.geocoder import NominatimGeocoder
from src.services.live_dashboard import LiveDashboardServer
from src.storage.models import Base, ListingModel
from src.storage.repository import ListingRepository


@pytest_asyncio.fixture
async def test_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_crm_status_and_notes(test_session: AsyncSession):
    repo = ListingRepository(test_session)

    listing = ListingSchema(
        id="crm-test-1",
        portal="Otodom",
        title="Dom w Słocinie CRM Test",
        url="https://otodom.pl/oferta/crm-test-1",
        price=950_000,
        price_per_m2=8_500.0,
        area_home=112.0,
        area_plot=350.0,
        building_type=BuildingType.SZEREGOWIEC,
        segment_subtype=SegmentSubtype.SKRAJNY,
        location_raw="Rzeszów, Słocina",
        street="Słocińska",
    )
    filt_res = FilterResult(
        is_qualified=True,
        status=QualificationStatus.QUALIFIED_WHITELIST,
        score=110.0,
        passed_stage1=True,
        passed_stage2=True,
    )

    model, is_new, _ = await repo.save_or_update(listing, filt_res)
    assert model.user_status == "NEW"
    assert model.user_notes is None

    # Test update status to FAVORITE
    updated = await repo.update_user_status(model.id, UserCRMStatus.FAVORITE.value)
    assert updated is not None
    assert updated.user_status == "FAVORITE"

    # Test update notes
    updated = await repo.update_user_notes(model.id, "Zadzwoń do agenta w poniedziałek o 10:00")
    assert updated is not None
    assert updated.user_notes == "Zadzwoń do agenta w poniedziałek o 10:00"

    # Test update status to TO_VISIT
    updated = await repo.update_user_status(model.id, UserCRMStatus.TO_VISIT.value)
    assert updated.user_status == "TO_VISIT"


@pytest.mark.asyncio
async def test_geocoder_fallback(test_session: AsyncSession):
    geocoder = NominatimGeocoder()

    # Test centroid/geocoding matching for Słocina
    lat, lon, is_exact = await geocoder.geocode(
        session=test_session,
        district="Słocina",
        city="Rzeszów",
    )
    assert lat is not None and lon is not None
    assert abs(lat - 50.02) < 0.05
    assert abs(lon - 22.05) < 0.05

    # Test centroid/geocoding matching for Krasne
    lat, lon, is_exact = await geocoder.geocode(
        session=test_session,
        city="Krasne",
    )
    assert lat is not None and lon is not None
    assert abs(lat - 50.04) < 0.05
    assert abs(lon - 22.08) < 0.05


@pytest.mark.asyncio
async def test_live_dashboard_crm_endpoints():
    from src.storage.database import init_db
    await init_db()
    server = LiveDashboardServer(port=8089)
    async with TestClient(TestServer(server.app)) as client:
        # Test GET /api/listings
        resp = await client.get("/api/listings")
        assert resp.status == 200
        listings = await resp.json()
        assert isinstance(listings, list)

        if len(listings) > 0:
            target_id = listings[0]["id"]
            # Test PATCH /api/listings/{id}/status
            patch_resp = await client.patch(
                f"/api/listings/{target_id}/status",
                json={"status": "FAVORITE"}
            )
            assert patch_resp.status == 200
            patch_data = await patch_resp.json()
            assert patch_data["success"] is True
            assert patch_data["user_status"] == "FAVORITE"

            # Test PATCH /api/listings/{id}/notes
            notes_resp = await client.patch(
                f"/api/listings/{target_id}/notes",
                json={"notes": "Notatka testowa z poziomu API"}
            )
            assert notes_resp.status == 200
            notes_data = await notes_resp.json()
            assert notes_data["success"] is True
            assert notes_data["user_notes"] == "Notatka testowa z poziomu API"


@pytest.mark.asyncio
async def test_live_dashboard_config_endpoints():
    server = LiveDashboardServer(port=8088)
    async with TestClient(TestServer(server.app)) as client:
        # Test GET /api/config
        resp = await client.get("/api/config")
        assert resp.status == 200
        cfg = await resp.json()
        assert "city" in cfg
        assert "distance_radius" in cfg

        # Test POST /api/config
        update_resp = await client.post(
            "/api/config",
            json={
                "city": "Kraków",
                "distance_radius": 25,
                "max_price": 1_400_000.0,
            }
        )
        assert update_resp.status == 200
        new_cfg = await update_resp.json()
        assert new_cfg["city"] == "Kraków"
        assert new_cfg["distance_radius"] == 25
        assert new_cfg["max_price"] == 1_400_000.0

        # Restore to default Rzeszów
        await client.post(
            "/api/config",
            json={
                "city": "Rzeszów",
                "distance_radius": 15,
                "max_price": 1_300_000.0,
            }
        )


@pytest.mark.asyncio
async def test_live_dashboard_listings_includes_gallery():
    from src.storage.database import init_db
    await init_db()
    server = LiveDashboardServer(port=8087)
    async with TestClient(TestServer(server.app)) as client:
        resp = await client.get("/api/listings")
        assert resp.status == 200
        listings = await resp.json()
        assert isinstance(listings, list)
        if len(listings) > 0:
            assert "gallery_images" in listings[0]
            assert isinstance(listings[0]["gallery_images"], list)


@pytest.mark.asyncio
async def test_generate_html_dashboard_with_gallery(tmp_path):
    from src.services.report_generator import generate_html_dashboard
    from src.storage.database import get_session, init_db
    await init_db()

    async with get_session() as session:
        repo = ListingRepository(session)
        listing = ListingSchema(
            id="test-rpt-1",
            portal="Otodom",
            portal_id="test_rpt_1",
            url="https://otodom.pl/oferta/test-rpt-1",
            title="Dom do raportu HTML",
            price=920_000,
            price_per_m2=7_666,
            area_home=120.0,
            area_plot=300.0,
            location_raw="Rzeszów",
            gallery_images=["https://example.com/1.jpg", "https://example.com/2.jpg"],
        )
        filt_res = FilterResult(
            is_qualified=True,
            status=QualificationStatus.QUALIFIED,
            score=80.0,
            passed_stage1=True,
            passed_stage2=True,
        )
        await repo.save_or_update(listing, filt_res)
        await session.commit()

    out_file = str(tmp_path / "test_report.html")
    path = await generate_html_dashboard(output_path=out_file, auto_open=False)
    assert os.path.exists(path)
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "<!DOCTYPE html>" in content
    assert "Universal Real Estate Hunter" in content
    assert "gallery-strip" in content




