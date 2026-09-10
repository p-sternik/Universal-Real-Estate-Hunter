import argparse
import asyncio
import sys

from loguru import logger

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

from src.scheduler.runner import SchedulerRunner
from src.services.discord_notifier import DiscordNotifier
from src.services.pipeline import ScraperPipeline
from src.storage.database import init_db


async def run_once(profile: str | None = None):
    """Execute a single scraping and qualification pass."""
    logger.info(f"Executing single pipeline pass{f' for profile: {profile}' if profile else ''}...")
    pipeline = ScraperPipeline()
    summary = await pipeline.run_cycle(target_profile=profile)
    logger.info("--- Cycle summary ---")
    for k, v in summary.items():
        logger.info(f"  {k}: {v}")


async def test_webhook():
    """Send test notification to Discord Webhook."""
    logger.info("Testing Discord Webhook...")
    notifier = DiscordNotifier()
    if not notifier.webhook_url:
        logger.error("DISCORD_WEBHOOK_URL is not configured in .env!")
        return

    ok = await notifier.send_test_message()
    if ok:
        logger.success("Test webhook sent successfully! Check your Discord channel.")
    else:
        logger.error("Failed to send Discord webhook message.")


async def test_filter_demo():
    """Run an interactive demonstration of Stage I & Stage II filters on sample listings."""
    from src.filters import QualificationEngine
    from src.models.enums import BuildingType, RoadType, SegmentSubtype
    from src.models.listing import ListingSchema

    logger.info("Testing QualificationEngine on synthetic test scenarios...")
    engine = QualificationEngine()

    test_cases = [
        ListingSchema(
            id="test_1",
            portal="Otodom",
            title="Nowoczesny dom szeregowy skrajny na Słocinie",
            url="https://otodom.pl/oferta/test-slocina-skrajny",
            price=1_150_000,
            price_per_m2=8_846,
            area_home=130.0,
            area_plot=380.0,
            building_type=BuildingType.SZEREGOWIEC,
            segment_subtype=SegmentSubtype.SKRAJNY,
            location_raw="Rzeszów, Słocina, ul. Witolda",
            street="Witolda",
            district="Słocina",
            city="Rzeszów",
            access_road_type=RoadType.ASFALT,
            raw_description=(
                "Do sprzedania wyjątkowy dom w zabudowie szeregowej - segment skrajny z dużą działką 3.8 ara! "
                "Garaż w bryle budynku oraz 2 miejsca postojowe na wybrukowanym podjeździe. "
                "Dojazd bezpośrednio z drogi asfaltowej. Ogrzewanie podłogowe, pompa ciepła, światłowód. "
                "Teren płaski, zagospodarowany."
            ),
        ),
        ListingSchema(
            id="test_2",
            portal="Otodom",
            title="Dom wolnostojący na Tyczynie z widokiem",
            url="https://otodom.pl/oferta/test-tyczyn",
            price=990_000,
            price_per_m2=7_615,
            area_home=130.0,
            area_plot=800.0,
            building_type=BuildingType.WOLNOSTOJACY,
            location_raw="Tyczyn, okolice Rzeszowa",
            access_road_type=RoadType.ASFALT,
            raw_description="Piękny dom w cichej okolicy Tyczyna, szybki dojazd do Rzeszowa.",
        ),
        ListingSchema(
            id="test_3",
            portal="Otodom",
            title="Segment środkowy na Zalesiu",
            url="https://otodom.pl/oferta/test-zalesie-srodkowy",
            price=890_000,
            price_per_m2=8_090,
            area_home=110.0,
            area_plot=140.0,
            building_type=BuildingType.SZEREGOWIEC,
            location_raw="Rzeszów, Zalesie, ul. Dunikowskiego",
            street="Dunikowskiego",
            district="Zalesie",
            city="Rzeszów",
            access_road_type=RoadType.KOSTKA,
            raw_description=(
                "Segment środkowy, działka 140 m2. Miejsce postojowe przed budynkiem. Dojazd drogą z kostki brukowej."
            ),
        ),
        ListingSchema(
            id="test_4",
            portal="Otodom",
            title="Dom w Krasnem przy DK94 z drogą polną",
            url="https://otodom.pl/oferta/test-krasne-bad-road",
            price=1_100_000,
            price_per_m2=8_800,
            area_home=125.0,
            area_plot=500.0,
            building_type=BuildingType.BLIZNIAK,
            location_raw="Krasne, w pobliżu DK94",
            access_road_type=RoadType.POLNA,
            raw_description="Dom w stanie deweloperskim. Dojazd drogą polną, ostatnie 200m droga nieutwardzona.",
        ),
    ]

    for i, item in enumerate(test_cases, 1):
        res = await engine.evaluate_listing(item)
        print(f"\n--- Przypadek {i}: {item.title} ---")
        print(f"  Status: {res.status.value}")
        print(f"  Zakwalifikowany: {'TAK' if res.is_qualified else 'NIE'}")
        print(f"  Score: {res.score:.1f}")
        if res.stage1_reasons:
            print(f"  Powody odrzucenia (Etap I): {res.stage1_reasons}")
        if res.stage2_reasons:
            print(f"  Powody odrzucenia (Etap II): {res.stage2_reasons}")
        if res.pros:
            print(f"  Zalety: {res.pros}")
        if res.cons:
            print(f"  Wady/Uwagi: {res.cons}")


async def reindex_all_listings():
    """Re-evaluate all existing listings in DB with the latest Stage 2 filters, finish conditions, visualisations, and utilities."""
    from collections import Counter

    from sqlalchemy import select

    from src.filters.stage2_semantic import Stage2SemanticFilter
    from src.models.enums import FinishCondition, HeatingType, SewerageType
    from src.storage.database import get_session
    from src.storage.models import ListingModel

    logger.info("Starting database re-indexing and backfill of finish, visualisations, sewerage, heating, and fiber...")
    s2 = Stage2SemanticFilter()
    finish_counter = Counter()
    sewerage_counter = Counter()
    heating_counter = Counter()
    fiber_count = 0
    vis_count = 0
    total = 0

    async with get_session() as session:
        result = await session.execute(select(ListingModel))
        listings = result.scalars().all()
        total = len(listings)
        logger.info(f"Loaded {total} listings from database.")

        for item in listings:
            desc = f"{item.title or ''}\n{item.raw_description or ''}"

            # 1. Detect finish condition
            existing_fc = (
                FinishCondition(item.finish_condition)
                if item.finish_condition in FinishCondition._value2member_map_
                else FinishCondition.NIEOKRESLONY
            )
            detected_fc = s2.detect_finish_condition(desc, existing_fc)
            item.finish_condition = detected_fc.value
            finish_counter[detected_fc.value] += 1

            # 2. Detect visualisations
            has_vis = s2.detect_visualisations(desc) or bool(item.has_visualisations)
            item.has_visualisations = has_vis
            if has_vis:
                vis_count += 1

            # 3. Detect sewerage
            existing_sew = (
                SewerageType(item.sewerage)
                if item.sewerage in SewerageType._value2member_map_
                else SewerageType.NIEZNANA
            )
            detected_sew = s2.detect_sewerage(desc, existing_sew)
            item.sewerage = detected_sew.value
            sewerage_counter[detected_sew.value] += 1

            # 4. Detect heating
            existing_heat = (
                HeatingType(item.heating) if item.heating in HeatingType._value2member_map_ else HeatingType.NIEZNANE
            )
            detected_heat = s2.detect_heating(desc, existing_heat)
            item.heating = detected_heat.value
            heating_counter[detected_heat.value] += 1

            # 5. Detect fiber
            has_fiber = s2.detect_fiber(desc, bool(item.has_fiber))
            item.has_fiber = has_fiber
            if has_fiber:
                fiber_count += 1

            # Refresh pros/cons
            pros = list(item.pros or [])
            cons = list(item.cons or [])

            # Clean previous dynamic tags
            pros = [
                p
                for p in pros
                if not any(
                    k in p.lower()
                    for k in [
                        "pod klucz",
                        "stan deweloperski",
                        "kanalizacja",
                        "oczyszczalnia",
                        "pompa ciepła",
                        "gazowe",
                        "miejskie",
                        "światłowód",
                    ]
                )
            ]
            cons = [
                c
                for c in cons
                if not any(
                    k in c.lower() for k in ["surowy", "remont", "wizualizacj", "szambo", "paliwo stałe", "elektryczne"]
                )
            ]

            if detected_fc == FinishCondition.DO_ZAMIESZKANIA:
                pros.append("Standard wykończenia: do zamieszkania / pod klucz")
            elif detected_fc == FinishCondition.DEWELOPERSKI:
                pros.append("Stan deweloperski")
            elif detected_fc == FinishCondition.SUROWY_ZAMKNIETY:
                cons.append("Stan surowy zamknięty (wymaga wykończenia)")
            elif detected_fc == FinishCondition.SUROWY_OTWARTY:
                cons.append("Stan surowy otwarty (brak stolarki i wykończenia)")
            elif detected_fc == FinishCondition.DO_REMONTU:
                cons.append("Wymaga remontu / odświeżenia")

            if has_vis:
                cons.append("⚠️ Oferta zawiera wizualizacje / zdjęcia poglądowe")

            if detected_sew == SewerageType.MIEJSKA:
                pros.append("Kanalizacja miejska/gminna")
            elif detected_sew == SewerageType.OCZYSZCZALNIA:
                pros.append("Przydomowa oczyszczalnia ścieków")
            elif detected_sew == SewerageType.SZAMBO:
                cons.append("⚠️ Szambo (brak kanalizacji miejskiej)")

            if detected_heat == HeatingType.POMPA_CIEPLA:
                pros.append("Pompa ciepła")
            elif detected_heat == HeatingType.GAZOWE:
                pros.append("Ogrzewanie gazowe")
            elif detected_heat == HeatingType.MIEJSKIE:
                pros.append("Ogrzewanie miejskie")
            elif detected_heat == HeatingType.PELLET_WEGIEL:
                cons.append("⚠️ Ogrzewanie na paliwo stałe (pellet/węgiel/drewno)")
            elif detected_heat == HeatingType.ELEKTRYCZNE:
                cons.append("Ogrzewanie elektryczne")

            if has_fiber:
                pros.append("Dostępny światłowód")

            item.pros = pros
            item.cons = cons

        await session.commit()

    print("\n" + "=" * 55)
    print("🎯 PODSUMOWANIE REINDEKSACJI BAZY DANYCH (MEDIA & STAN)")
    print("=" * 55)
    print(f"Liczba przetworzonych ofert: {total}")
    print(f"Wykryte wizualizacje 3D: {vis_count}")
    print(f"Dostępny światłowód: {fiber_count}")
    print("\nRozkład stanów wykończenia:")
    for status, count in finish_counter.most_common():
        pct = (count / total * 100) if total > 0 else 0
        print(f"  • {status.capitalize():<24}: {count:>3} ({pct:>5.1f}%)")
    print("\nRozkład instalacji kanalizacji/ścieków:")
    for status, count in sewerage_counter.most_common():
        pct = (count / total * 100) if total > 0 else 0
        print(f"  • {status.capitalize():<24}: {count:>3} ({pct:>5.1f}%)")
    print("\nRozkład systemów ogrzewania:")
    for status, count in heating_counter.most_common():
        pct = (count / total * 100) if total > 0 else 0
        print(f"  • {status.capitalize():<24}: {count:>3} ({pct:>5.1f}%)")
    print("=" * 55)


async def audit_geoportal_all(limit: int = 50, only_qualified: bool = True):
    """
    Audits listings in database using Geoportal ULDK & KIEG.
    Resolves cadastral parcel ID, exact area, and checks for surrounding industrial risks (Ba).
    """
    from sqlalchemy import select

    from src.services.geoportal import geoportal_service
    from src.storage.database import get_session, init_db
    from src.storage.models import ListingModel

    await init_db()
    logger.info(f"Rozpoczynanie audytu Geoportalu dla ofert w bazie (limit={limit})...")
    async with get_session() as session:
        stmt = select(ListingModel).where(
            ListingModel.latitude.isnot(None),
            ListingModel.longitude.isnot(None),
        )
        if only_qualified:
            stmt = stmt.where(ListingModel.is_qualified.is_(True))
        stmt = stmt.order_by(ListingModel.is_qualified.desc(), ListingModel.id.desc()).limit(limit)

        res = await session.execute(stmt)
        listings = res.scalars().all()
        logger.info(f"Znaleziono {len(listings)} ofert do audytu w Geoportalu.")

        audited = 0
        risks_count = 0
        for item in listings:
            if item.latitude is None or item.longitude is None:
                continue
            geo_res = await geoportal_service.audit_location(item.latitude, item.longitude, radius_meters=120)
            if geo_res.get("gesut_networks"):
                item.gesut_networks_data = geo_res["gesut_networks"]
            if geo_res.get("main_parcel_id"):
                item.parcel_id = geo_res["main_parcel_id"]
                item.geoportal_url = geo_res["geoportal_url"]
                if geo_res.get("cadastral_area"):
                    item.cadastral_area = geo_res["cadastral_area"]

                risks = geo_res.get("surrounding_risks", [])
                cons = list(item.cons or [])
                pros = list(item.pros or [])

                # Clean previous geoportal tags
                cons = [c for c in cons if not c.startswith("⚠️ Geoportal:")]
                pros = [p for p in pros if not p.startswith("Zidentyfikowano działkę w Geoportalu:")]

                if risks:
                    risks_count += 1
                    for r in risks:
                        cons.append(f"⚠️ Geoportal: {r}")
                    item.qualification_score = max(0.0, item.qualification_score - 25.0)

                p_num = geo_res.get("main_parcel_number")
                p_area = geo_res.get("cadastral_area")
                if p_num and p_area:
                    pros.append(f"Zidentyfikowano działkę w Geoportalu: nr {p_num} ({p_area:.0f} m²)")

                item.cons = cons
                item.pros = pros
                audited += 1
                logger.info(
                    f"[{item.id}] {item.title[:35]} -> Dz. {item.parcel_id} ({item.cadastral_area} m²) | Ryzyka: {len(risks)}"
                )

        await session.commit()
        logger.success(
            f"Zakończono audyt Geoportalu. Przeanalizowano {audited} ofert, wykryto ryzyka sąsiedztwa w {risks_count} ofertach."
        )


def main():
    parser = argparse.ArgumentParser(description="Rzeszów Real Estate Hunter & Scraper Pipeline")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    run_parser = subparsers.add_parser("run", help="Start continuous scheduler daemon (default: every 20 mins)")
    run_parser.add_argument("--city", default=None, help="Target city (e.g. Kraków, Warszawa, Rzeszów)")
    run_parser.add_argument("--radius", type=int, default=None, help="Search distance radius (+km)")
    run_parser.add_argument("--profile", default=None, help="Specific search profile to run (name or ID)")
    run_parser.add_argument(
        "--interval", type=int, default=None, help="Scraping interval in minutes (overrides config)"
    )

    once_parser = subparsers.add_parser("once", help="Run a single scraping and qualification pass")
    once_parser.add_argument("--city", default=None, help="Target city (e.g. Kraków, Warszawa, Rzeszów)")
    once_parser.add_argument("--radius", type=int, default=None, help="Search distance radius (+km)")
    once_parser.add_argument("--profile", default=None, help="Specific search profile to run (name or ID)")

    subparsers.add_parser("init-db", help="Initialize database tables")
    subparsers.add_parser("test-webhook", help="Send a test message to Discord Webhook")
    subparsers.add_parser("test-filter", help="Run demonstration test of filtering rules")

    # View in terminal
    view_parser = subparsers.add_parser("view", help="View saved listings in terminal table")
    view_parser.add_argument("--status", default="QUALIFIED", help="Filter: QUALIFIED, QUALIFIED_WHITELIST, ALL")
    view_parser.add_argument("--limit", type=int, default=15, help="Number of records to show")

    # Live Preview Web Server (dynamic, direct DB connection)
    dash_parser = subparsers.add_parser("dashboard", help="Start real-time Live Preview Web Server")
    dash_parser.add_argument("--host", default="0.0.0.0", help="Host to listen on (default: 0.0.0.0)")
    dash_parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    dash_parser.add_argument("--no-open", action="store_true", help="Do not automatically open browser")

    server_parser = subparsers.add_parser("server", help="Alias for dashboard")
    server_parser.add_argument("--host", default="0.0.0.0", help="Host to listen on (default: 0.0.0.0)")
    server_parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    server_parser.add_argument("--no-open", action="store_true", help="Do not automatically open browser")

    # Geocode missing coordinates
    subparsers.add_parser("geocode", help="Geocode listings missing GPS coordinates using Nominatim cache")

    # Reindex database
    subparsers.add_parser("reindex", help="Re-evaluate all existing listings in database with latest filters")

    # Geoportal audit
    geo_parser = subparsers.add_parser(
        "geoportal", help="Audit listings using Geoportal ULDK & KIEG for cadastral parcel and industrial risks"
    )
    geo_parser.add_argument("--limit", type=int, default=50, help="Number of listings to audit (default: 50)")
    geo_parser.add_argument("--all", action="store_true", help="Audit all listings including non-qualified")

    args = parser.parse_args()
    cmd = args.command or "run"

    # Apply CLI city and radius overrides if specified
    if hasattr(args, "city") and args.city:
        from src.services.config_manager import config_manager

        upd = {"city": args.city}
        if hasattr(args, "radius") and args.radius is not None:
            upd["distance_radius"] = args.radius
        config_manager.update_config(upd)

    if cmd == "init-db":
        asyncio.run(init_db())
    elif cmd == "geoportal":
        asyncio.run(audit_geoportal_all(limit=args.limit, only_qualified=not getattr(args, "all", False)))
    elif cmd == "reindex":
        asyncio.run(reindex_all_listings())
    elif cmd == "geocode":
        from src.services.geocoder import backfill_missing_coordinates

        asyncio.run(backfill_missing_coordinates())
    elif cmd == "once":
        asyncio.run(run_once(profile=getattr(args, "profile", None)))
    elif cmd in ("dashboard", "server"):
        from src.services.live_dashboard import LiveDashboardServer

        host = getattr(args, "host", "0.0.0.0")
        srv = LiveDashboardServer(host=host, port=args.port)
        try:
            asyncio.run(srv.run(auto_open=not args.no_open))
        except (KeyboardInterrupt, SystemExit):
            pass
    elif cmd == "view":
        from src.services.terminal_view import print_terminal_view

        asyncio.run(print_terminal_view(status_filter=args.status, limit=args.limit))
    elif cmd == "test-webhook":
        asyncio.run(test_webhook())
    elif cmd == "test-filter":
        asyncio.run(test_filter_demo())
    elif cmd == "run":
        runner = SchedulerRunner(
            interval_minutes=getattr(args, "interval", None),
            profile=getattr(args, "profile", None),
        )
        try:
            asyncio.run(runner.start())
        except (KeyboardInterrupt, SystemExit):
            runner.stop()


if __name__ == "__main__":
    main()
