import pytest
import pytest_asyncio
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.filters.fingerprint import generate_property_fingerprint
from src.models.enums import BuildingType, QualificationStatus, RoadType, SegmentSubtype
from src.models.listing import FilterResult, ListingSchema
from src.storage.models import Base, ListingModel
from src.storage.repository import ListingRepository


@pytest_asyncio.fixture
async def async_session():
    # In-memory SQLite for testing
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_save_and_price_history(async_session: AsyncSession):
    repo = ListingRepository(async_session)

    fp = generate_property_fingerprint(
        price=1_100_000,
        area_home=120.0,
        area_plot=300.0,
        street="Witolda",
    )

    listing = ListingSchema(
        id="otodom-100",
        portal="Otodom",
        title="Dom na Witolda",
        url="https://otodom.pl/oferta/otodom-100",
        price=1_100_000,
        price_per_m2=9_166.67,
        area_home=120.0,
        area_plot=300.0,
        building_type=BuildingType.SZEREGOWIEC,
        segment_subtype=SegmentSubtype.SKRAJNY,
        location_raw="Rzeszów, Słocina",
        street="Witolda",
        property_fingerprint=fp,
    )

    filt_res = FilterResult(
        is_qualified=True,
        status=QualificationStatus.QUALIFIED_WHITELIST,
        score=120.0,
        passed_stage1=True,
        passed_stage2=True,
        pros=["Skrajny", "Garaż"],
        cons=[],
    )

    # 1. Insert new listing
    model, is_new, price_changed = await repo.save_or_update(listing, filt_res)
    assert is_new is True
    assert price_changed is False
    assert model.id is not None
    assert model.title == "Dom na Witolda"
    assert model.is_qualified is True

    # Check deduplication by fingerprint
    duplicate = await repo.find_duplicate_by_fingerprint(fp)
    assert duplicate is not None
    assert duplicate.id == model.id

    # 2. Update with price drop
    listing.price = 1_050_000
    listing.price_per_m2 = 8_750.0
    updated_model, is_new2, price_changed2 = await repo.save_or_update(listing, filt_res)

    assert is_new2 is False
    assert price_changed2 is True
    assert updated_model.price == 1_050_000

    # 3. Verify notification mark
    assert updated_model.notified_at is None
    await repo.mark_as_notified(updated_model.id)
    assert updated_model.notified_at is not None


@pytest.mark.asyncio
async def test_get_fresh_urls(async_session: AsyncSession):
    repo = ListingRepository(async_session)

    now = datetime.now(timezone.utc)
    async_session.add_all([
        ListingModel(
            portal="Otodom", portal_id="a", url="https://otodom.pl/x/fresh",
            property_fingerprint="f1", title="t", price=1, price_per_m2=1, area_home=100,
            raw_description="pełny opis", last_scraped_at=now,
        ),
        ListingModel(
            portal="Otodom", portal_id="b", url="https://otodom.pl/x/stale",
            property_fingerprint="f2", title="t", price=1, price_per_m2=1, area_home=100,
            raw_description="pełny opis", last_scraped_at=now - timedelta(hours=48),
        ),
        ListingModel(
            portal="OLX", portal_id="c", url="https://olx.pl/x/other-portal",
            property_fingerprint="f3", title="t", price=1, price_per_m2=1, area_home=100,
            raw_description="pełny opis", last_scraped_at=now,
        ),
        ListingModel(
            portal="Otodom", portal_id="d", url="https://otodom.pl/x/empty-desc",
            property_fingerprint="f4", title="t", price=1, price_per_m2=1, area_home=100,
            raw_description="", last_scraped_at=now,
        ),
    ])
    await async_session.flush()

    urls = await repo.get_fresh_urls(["Otodom", "NieruchomosciOnline"], within_hours=24)

    assert "https://otodom.pl/x/fresh" in urls
    assert "https://otodom.pl/x/stale" not in urls
    assert "https://olx.pl/x/other-portal" not in urls
    assert "https://otodom.pl/x/empty-desc" not in urls


@pytest.mark.asyncio
async def test_update_does_not_wipe_detected_flags(async_session: AsyncSession):
    repo = ListingRepository(async_session)

    fp = generate_property_fingerprint(price=900_000, area_home=110.0, area_plot=300.0)
    listing = ListingSchema(
        id="otodom-200",
        portal="Otodom",
        title="Dom z włóknem",
        url="https://otodom.pl/oferta/otodom-200",
        price=900_000,
        price_per_m2=8_000,
        area_home=110.0,
        area_plot=300.0,
        location_raw="Rzeszów",
        property_fingerprint=fp,
        has_fiber=True,
        has_visualisations=True,
    )
    filt_res = FilterResult(
        is_qualified=True,
        status=QualificationStatus.QUALIFIED,
        score=60.0,
        passed_stage1=True,
        passed_stage2=True,
    )
    model, is_new, _ = await repo.save_or_update(listing, filt_res)
    assert is_new is True
    assert model.has_fiber is True
    assert model.has_visualisations is True

    # Re-scrape with fields not detected this time (e.g. Otodom never detects fiber)
    listing2 = listing.model_copy(update={"has_fiber": False, "has_visualisations": False})
    model2, is_new2, _ = await repo.save_or_update(listing2, filt_res)
    assert is_new2 is False
    assert model2.has_fiber is True
    assert model2.has_visualisations is True


@pytest.mark.asyncio
async def test_repository_gallery_images(async_session: AsyncSession):
    repo = ListingRepository(async_session)
    fp = generate_property_fingerprint(
        price=850_000,
        area_home=120.0,
        area_plot=250.0,
        street="Krakowska",
    )
    test_gallery = [
        "https://example.com/photo1.jpg",
        "https://example.com/photo2.jpg",
        "https://example.com/photo3.jpg",
    ]
    listing = ListingSchema(
        id="otodom-gal-123",
        portal="Otodom",
        portal_id="gal_123",
        url="https://otodom.pl/oferta/gal-123",
        title="Dom z galerią zdjęć",
        price=850_000,
        price_per_m2=7_083,
        area_home=120.0,
        area_plot=250.0,
        location_raw="Rzeszów",
        property_fingerprint=fp,
        gallery_images=test_gallery,
    )
    filt_res = FilterResult(
        is_qualified=True,
        status=QualificationStatus.QUALIFIED,
        score=75.0,
        passed_stage1=True,
        passed_stage2=True,
    )

    model, is_new, _ = await repo.save_or_update(listing, filt_res)
    assert is_new is True
    assert model.gallery_images == test_gallery

    # Verify reload from DB
    loaded = await repo.get_by_url(listing.url)
    assert loaded is not None
    assert loaded.gallery_images == test_gallery

    # Update with new gallery
    new_gallery = test_gallery + ["https://example.com/photo4.jpg"]
    listing_updated = listing.model_copy(update={"gallery_images": new_gallery})
    model_up, is_new_up, _ = await repo.save_or_update(listing_updated, filt_res)
    assert is_new_up is False
    assert len(model_up.gallery_images) == 4

