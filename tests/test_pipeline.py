from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.models.enums import BuildingType, QualificationStatus, SegmentSubtype
from src.models.listing import FilterResult, ListingSchema
from src.services.pipeline import ScraperPipeline
from src.storage.models import Base
from src.storage.repository import ListingRepository


@pytest_asyncio.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


def make_listing() -> ListingSchema:
    return ListingSchema(
        id="llm-1",
        portal="Otodom",
        title="Dom testowy",
        url="https://otodom.pl/oferta/llm-1",
        price=1_000_000,
        price_per_m2=8_000,
        area_home=125.0,
        area_plot=350.0,
        building_type=BuildingType.WOLNOSTOJACY,
        segment_subtype=SegmentSubtype.NIEOKRESLONY,
        location_raw="Rzeszów, Słocina",
        coordinates=(50.04, 22.0),
        raw_description="Dom z garażem, dojazd asfaltowy, kanalizacja miejska.",
    )


def make_qualified_result(**ai_fields) -> FilterResult:
    score = ai_fields.pop("score", 60.0)
    return FilterResult(
        is_qualified=True,
        status=QualificationStatus.QUALIFIED,
        score=score,
        passed_stage1=True,
        passed_stage2=True,
        **ai_fields,
    )


def make_unqualified_result(**ai_fields) -> FilterResult:
    score = ai_fields.pop("score", 10.0)
    return FilterResult(
        is_qualified=False,
        status=QualificationStatus.REJECTED_STAGE2,
        score=score,
        passed_stage1=True,
        passed_stage2=False,
        **ai_fields,
    )


def make_pipeline(llm_enabled: bool, engine_mock) -> ScraperPipeline:
    pipeline = ScraperPipeline(
        scrapers=[MagicMock()],
        discord_notifier=AsyncMock(),
        telegram_notifier=AsyncMock(),
    )
    pipeline.llm_analysis_enabled = llm_enabled
    pipeline.engine = engine_mock
    return pipeline


@pytest.mark.asyncio
async def test_pipeline_backfills_ai_analysis_for_existing_listing(async_session):
    """Existing listing without AI analysis must be sent to the LLM once (backfill)."""
    repo = ListingRepository(async_session)
    listing = make_listing()

    model, is_new, _ = await repo.save_or_update(listing, make_qualified_result())
    assert is_new is True
    assert model.ai_summary is None

    engine_mock = AsyncMock()
    engine_mock.evaluate_listing.return_value = FilterResult(
        is_qualified=False,
        status=QualificationStatus.REJECTED_STAGE2,
        score=10.0,
        passed_stage1=True,
        passed_stage2=False,
        ai_summary="TL;DR oferty.",
        ai_questions=["Pytanie do agenta?"],
        contact_phone="+48600123456",
        contact_person="Jan Kowalski",
    )
    pipeline = make_pipeline(llm_enabled=True, engine_mock=engine_mock)

    result = await pipeline.process_listing(listing, repo)

    engine_mock.evaluate_listing.assert_awaited_once()
    assert engine_mock.evaluate_listing.call_args.kwargs["skip_llm"] is False
    assert result["is_new"] is False
    assert model.ai_summary == "TL;DR oferty."
    assert model.ai_questions == ["Pytanie do agenta?"]
    assert model.contact_phone == "+48600123456"
    assert model.contact_person == "Jan Kowalski"


@pytest.mark.asyncio
async def test_pipeline_skips_llm_when_analysis_already_present(async_session):
    """Existing listing with AI analysis and unchanged description must skip the LLM."""
    repo = ListingRepository(async_session)
    listing = make_listing()

    model, is_new, _ = await repo.save_or_update(
        listing,
        make_qualified_result(
            ai_summary="Istniejące TL;DR.",
            ai_questions=["Stare pytanie?"],
        ),
    )
    assert is_new is True
    assert model.ai_summary == "Istniejące TL;DR."

    engine_mock = AsyncMock()
    engine_mock.evaluate_listing.return_value = make_unqualified_result(ai_summary="", ai_questions=[])
    pipeline = make_pipeline(llm_enabled=True, engine_mock=engine_mock)

    await pipeline.process_listing(listing, repo)

    engine_mock.evaluate_listing.assert_awaited_once()
    assert engine_mock.evaluate_listing.call_args.kwargs["skip_llm"] is True
    # Preserved from DB (skip path keeps existing AI fields)
    assert model.ai_summary == "Istniejące TL;DR."
    assert model.ai_questions == ["Stare pytanie?"]


@pytest.mark.asyncio
async def test_pipeline_skips_llm_when_analysis_disabled(async_session):
    """LLM must never run when llm_analysis_enabled is False."""
    repo = ListingRepository(async_session)
    listing = make_listing()

    engine_mock = AsyncMock()
    engine_mock.evaluate_listing.return_value = make_unqualified_result()
    pipeline = make_pipeline(llm_enabled=False, engine_mock=engine_mock)

    await pipeline.process_listing(listing, repo)

    engine_mock.evaluate_listing.assert_awaited_once()
    assert engine_mock.evaluate_listing.call_args.kwargs["skip_llm"] is True


@pytest.mark.asyncio
async def test_pipeline_integrates_geoportal_spatial_findings(async_session, monkeypatch):
    """Pipeline audits Geoportal for exact coords and applies MPZP and flood risk."""
    from src.services.geoportal import geoportal_service

    mock_audit = AsyncMock(
        return_value={
            "main_parcel_id": "186301_1.0221.2296/2",
            "main_parcel_number": "2296/2",
            "cadastral_area": 500.0,
            "geoportal_url": "https://mapy.geoportal.gov.pl/?identifyParcel=186301_1.0221.2296/2",
            "mpzp_zone": "MN: tereny mieszkaniowe",
            "mpzp_status": "OBOWIĄZUJĄCY",
            "flood_risk_zone": "ZAGROŻENIE_POWODZIOWE",
            "surrounding_risks": ["Działka w strefie zagrożenia powodziowego"],
            "surrounding_parcels_count": 4,
        }
    )
    monkeypatch.setattr(geoportal_service, "audit_location", mock_audit)

    repo = ListingRepository(async_session)
    listing = make_listing()
    listing.coordinates = (50.04, 22.0)

    engine_mock = AsyncMock()
    engine_mock.evaluate_listing.return_value = make_qualified_result(score=60.0)
    pipeline = make_pipeline(llm_enabled=False, engine_mock=engine_mock)

    await pipeline.process_listing(listing, repo)

    model = await repo.get_by_url(listing.url)
    assert model is not None
    assert model.parcel_id == "186301_1.0221.2296/2"
    assert model.mpzp_zone == "MN: tereny mieszkaniowe"
    assert model.flood_risk_zone == "ZAGROŻENIE_POWODZIOWE"
    assert any("Zagrożenie powodziowe" in c for c in model.cons)
    assert any("Miejscowy Plan" in p for p in model.pros)
    # Score penalty -20 applied for flood risk
    assert model.qualification_score == 40.0
