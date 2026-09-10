import asyncio
import time
from typing import Any

from loguru import logger

from config import settings
from src.filters import QualificationEngine
from src.models.enums import BuildingType, FinishCondition, HeatingType, SewerageType
from src.models.listing import ListingSchema
from src.scrapers import BaseScraper, MorizonScraper, NieruchomosciOnlineScraper, OLXScraper, OtodomScraper
from src.services.config_manager import SearchProfile
from src.services.discord_notifier import DiscordNotifier
from src.services.market_analyzer import analyze_negotiation, resolve_local_median
from src.services.progress import global_tracker
from src.services.telegram_notifier import TelegramNotifier
from src.storage import ListingRepository, get_session, init_db


class ScraperPipeline:
    """
    End-to-end analytical pipeline:
    1. Scrapes targets (Otodom, OLX, Nieruchomosci-online).
    2. Broadcasts live progress to terminal and web dashboard.
    3. Performs cross-portal / multi-agency deduplication via property_fingerprint.
    4. Executes Two-Stage filtration and semantic qualification.
    5. Persists data, price history, and qualification status via SQLAlchemy 2.0.
    6. Dispatches notifications for new matching offers and price drops.
    """

    def __init__(
        self,
        scrapers: list[BaseScraper] | None = None,
        discord_notifier: DiscordNotifier | None = None,
        telegram_notifier: TelegramNotifier | None = None,
    ):
        self._custom_scrapers = scrapers is not None
        self.scrapers = scrapers or [
            OtodomScraper(max_pages=2),
            OLXScraper(max_pages=1),
            NieruchomosciOnlineScraper(max_pages=1),
            MorizonScraper(max_pages=1),
        ]
        self.discord = discord_notifier or DiscordNotifier()
        self.telegram = telegram_notifier or TelegramNotifier()
        self.llm_analysis_enabled = settings.USE_LLM_ANALYSIS
        self.engine = QualificationEngine(llm_enabled=self.llm_analysis_enabled)

    async def process_listing(
        self,
        listing: ListingSchema,
        repo: ListingRepository,
        profile: Any | None = None,
        market_medians: dict[str, float] | None = None,
    ) -> dict:
        result = {
            "is_new": False,
            "is_duplicate_fingerprint": False,
            "price_changed": False,
            "qualified": False,
            "notified": False,
        }

        if profile:
            if not listing.profile_id:
                listing.profile_id = profile.id
            if not listing.profile_name:
                listing.profile_name = profile.name

        # 1. Look up existing record in database
        existing_model = await repo.get_by_url(listing.url) or await repo.get_by_portal_id(listing.portal, listing.id)

        # 1.1 Check duplicate by fingerprint
        if listing.property_fingerprint:
            duplicate_model = await repo.find_duplicate_by_fingerprint(listing.property_fingerprint)
            if duplicate_model and duplicate_model.url != listing.url:
                logger.info(
                    f"[Pipeline] Found multi-agency/cross-portal duplicate for '{listing.title[:40]}' "
                    f"(matches existing ID {duplicate_model.id} from {duplicate_model.portal})."
                )
                result["is_duplicate_fingerprint"] = True

        # 1.2 Restore stored detail data when detail was skipped or already cached in DB
        if existing_model:
            if not listing.raw_description and existing_model.raw_description:
                listing.raw_description = existing_model.raw_description
            if listing.finish_condition == FinishCondition.NIEOKRESLONY and existing_model.finish_condition:
                try:
                    listing.finish_condition = FinishCondition(existing_model.finish_condition)
                except ValueError:
                    pass
            if listing.sewerage == SewerageType.NIEZNANA and existing_model.sewerage:
                try:
                    listing.sewerage = SewerageType(existing_model.sewerage)
                except ValueError:
                    pass
            if listing.heating == HeatingType.NIEZNANE and existing_model.heating:
                try:
                    listing.heating = HeatingType(existing_model.heating)
                except ValueError:
                    pass
            if not listing.has_fiber:
                listing.has_fiber = bool(existing_model.has_fiber)
            if not listing.has_visualisations:
                listing.has_visualisations = bool(existing_model.has_visualisations)
            if not listing.year_built:
                listing.year_built = existing_model.year_built
            if not listing.coordinates and existing_model.latitude and existing_model.longitude:
                listing.coordinates = (existing_model.latitude, existing_model.longitude)
            if listing.building_type.value == "inny" and existing_model.building_type != "inny":
                try:
                    listing.building_type = type(listing.building_type)(existing_model.building_type)
                except ValueError:
                    pass
            if listing.access_road_type.value == "nieznana" and existing_model.access_road_type != "nieznana":
                try:
                    listing.access_road_type = type(listing.access_road_type)(existing_model.access_road_type)
                except ValueError:
                    pass
            if listing.market.value == "nieokreślony" and existing_model.market != "nieokreślony":
                try:
                    listing.market = type(listing.market)(existing_model.market)
                except ValueError:
                    pass
            if not listing.parcel_id and existing_model.parcel_id:
                listing.parcel_id = existing_model.parcel_id
                listing.cadastral_area = existing_model.cadastral_area
                listing.geoportal_url = existing_model.geoportal_url
                listing.mpzp_zone = getattr(existing_model, "mpzp_zone", None)
                listing.mpzp_status = getattr(existing_model, "mpzp_status", None)
                listing.flood_risk_zone = getattr(existing_model, "flood_risk_zone", None)
                listing.gesut_networks = getattr(existing_model, "gesut_networks_data", None)

        # 1.5. Stage 1 pre-check & Geoportal spatial audit before LLM
        is_exact_coords = True
        stage1_passed = True
        if hasattr(self.engine, "stage1"):
            stage1_attr = getattr(self.engine, "stage1", None)
            from unittest.mock import AsyncMock, MagicMock

            if stage1_attr is not None and not isinstance(stage1_attr, (AsyncMock, MagicMock)):
                try:
                    s1_res = stage1_attr.evaluate(listing, profile=profile)
                    if isinstance(s1_res, tuple) and len(s1_res) >= 1:
                        stage1_passed = bool(s1_res[0])
                except Exception as e:
                    logger.debug(f"[Pipeline] Stage 1 pre-check error: {e}")

        geo_audit = None
        if stage1_passed:
            # Resolve coordinates if missing (skip if already resolved in existing_model)
            if not listing.coordinates:
                from src.services.geocoder import geocoder

                lat, lon, is_exact = await geocoder.geocode(
                    session=repo.session,
                    street=listing.street,
                    district=listing.district,
                    city=listing.city,
                    location_raw=listing.location_raw,
                )
                if lat and lon:
                    listing.coordinates = (lat, lon)
                    is_exact_coords = is_exact
            elif existing_model and existing_model.is_exact_coords is not None:
                is_exact_coords = bool(existing_model.is_exact_coords)

            # Audit location in Geoportal if coords are exact, and not already audited
            if listing.coordinates and is_exact_coords and not listing.parcel_id:
                try:
                    from src.services.geoportal import geoportal_service

                    geo_audit = await geoportal_service.audit_location(
                        listing.coordinates[0], listing.coordinates[1], radius_meters=120
                    )
                    if geo_audit.get("main_parcel_id"):
                        listing.parcel_id = geo_audit["main_parcel_id"]
                        listing.cadastral_area = geo_audit.get("cadastral_area")
                        listing.geoportal_url = geo_audit.get("geoportal_url")
                        listing.mpzp_zone = geo_audit.get("mpzp_zone")
                        listing.mpzp_status = geo_audit.get("mpzp_status")
                        listing.flood_risk_zone = geo_audit.get("flood_risk_zone")
                    for k in (
                        "landslide_risk",
                        "egib_building_status",
                        "egib_soil_class",
                        "noise_level_db",
                        "noise_zone",
                        "nature_protected_zone",
                        "monument_zone",
                        "cemetery_buffer_zone",
                    ):
                        if (v := geo_audit.get(k)) is not None:
                            setattr(listing, k, v)
                except Exception as e:
                    logger.debug(f"[Pipeline] Geoportal audit skipped: {e}")

        # Check if LLM can be skipped because this listing was already analyzed.
        # If LLM analysis is enabled and the listing has no AI summary yet (e.g. rows
        # scraped before the AI Due Diligence feature), run the LLM once to backfill.
        skip_llm = not self.llm_analysis_enabled
        if self.llm_analysis_enabled and existing_model and existing_model.qualification_status:
            desc_unchanged = not listing.raw_description or (
                existing_model.raw_description
                and listing.raw_description.strip() == existing_model.raw_description.strip()
            )
            if desc_unchanged and (existing_model.ai_summary or existing_model.ai_questions):
                skip_llm = True

        # 2. Run two-stage qualification engine (LLM now receives spatial context in listing!)
        filter_result = await self.engine.evaluate_listing(listing, profile=profile, skip_llm=skip_llm)

        # If LLM was skipped, preserve previously saved LLM pros/cons and AI fields
        if skip_llm and existing_model:
            if existing_model.pros:
                for p in existing_model.pros:
                    if p.startswith("[LLM]") and p not in filter_result.pros:
                        filter_result.pros.append(p)
            if existing_model.cons:
                for c in existing_model.cons:
                    if (
                        c.startswith("[LLM]")
                        or c.startswith("🔧 [LLM]")
                        or c.startswith("🖼️ [LLM]")
                        or c.startswith("🔍 [LLM]")
                        or c.startswith("⚠️ [Ukryty koszt]")
                        or c.startswith("⚖️ [Ryzyko prawne]")
                    ) and c not in filter_result.cons:
                        filter_result.cons.append(c)
            # Preserve AI Due Diligence fields for the in-memory result used by notifiers
            for field in ("ai_summary", "ai_verdict", "ai_questions", "contact_phone", "contact_person"):
                if not getattr(filter_result, field) and getattr(existing_model, field, None):
                    setattr(filter_result, field, getattr(existing_model, field))
            if filter_result.worth_interest is None and getattr(existing_model, "worth_interest", None) is not None:
                filter_result.worth_interest = existing_model.worth_interest

        # Propagate spatial fields to filter_result
        for f in (
            "landslide_risk",
            "egib_building_status",
            "egib_soil_class",
            "noise_level_db",
            "noise_zone",
            "nature_protected_zone",
            "monument_zone",
            "cemetery_buffer_zone",
        ):
            if (val := getattr(listing, f, None)) is not None:
                setattr(filter_result, f, val)

        # 3. Enrich filter_result with spatial audit findings (MPZP, flood risk, cadastral parcel, Tier 1 checks)
        if filter_result.is_qualified:
            if listing.mpzp_zone:
                filter_result.mpzp_zone = listing.mpzp_zone
                if listing.mpzp_status == "OBOWIĄZUJĄCY":
                    filter_result.pros.append(f"Miejscowy Plan (MPZP): {listing.mpzp_zone}")
                elif listing.mpzp_status == "BRAK_PLANU_LUB_CYFRYZACJI":
                    filter_result.cons.append("⚠️ Brak cyfrowego MPZP w Geoportalu (wymaga weryfikacji WZ)")

            if listing.flood_risk_zone:
                filter_result.flood_risk_zone = listing.flood_risk_zone
                if listing.flood_risk_zone == "ZAGROŻENIE_POWODZIOWE":
                    filter_result.cons.append("⚠️ Zagrożenie powodziowe (ISOK): Działka w strefie ryzyka powodziowego")
                    filter_result.score = max(0.0, filter_result.score - 20.0)

            # SOPO Landslide
            if listing.landslide_risk in ("OSUWISKO", "ZAGROŻENIE_OSUWISKIEM"):
                filter_result.cons.append(
                    "🚨 Aktywne osuwisko / Zagrożenie ruchami masowymi (PIG-PIB SOPO): "
                    "Ryzyko naruszenia konstrukcji, odmowy ubezpieczenia lub kredytu"
                )
                filter_result.score = max(0.0, filter_result.score - 50.0)

            # EGiB Building disclosure & Soil class
            if listing.egib_building_status:
                cat = (
                    listing.category.value
                    if hasattr(listing.category, "value")
                    else str(getattr(listing, "category", "dom"))
                ).lower()
                is_house = cat in ("dom", "segment", "blizniak", "szeregowiec") or listing.building_type in (
                    BuildingType.WOLNOSTOJACY,
                    BuildingType.BLIZNIAK,
                    BuildingType.SZEREGOWIEC,
                )
                finish = (
                    listing.finish_condition.value
                    if hasattr(listing.finish_condition, "value")
                    else str(listing.finish_condition or "")
                ).lower()
                is_developer = "deweloperski" in finish or (
                    hasattr(listing, "market") and str(listing.market).lower() == "pierwotny"
                )

                if is_house and not is_developer:
                    if listing.egib_building_status == "BRAK_W_EWIDENCJI":
                        filter_result.cons.append(
                            "⚠️ Dom nieujawniony w ewidencji budynków EGiB: Ryzyko samowoli budowlanej, "
                            "braku odbioru końcowego lub problemu z kredytem hipotecznym"
                        )
                        filter_result.score = max(0.0, filter_result.score - 15.0)
                    elif listing.egib_building_status == "UJAWNIONY":
                        filter_result.pros.append(
                            "Budynek formalnie ujawniony w państwowej ewidencji budynków (EGiB użytek B/Br)"
                        )

            if listing.egib_soil_class:
                soil_upper = listing.egib_soil_class.upper()
                if any(pc in soil_upper for pc in ("RIIIA", "RIIIB", "ŁIII", "PSIII", "RI", "RII")):
                    filter_result.cons.append(
                        f"⚠️ Grunt chroniony w EGiB ({listing.egib_soil_class}): Klasa bonitacyjna podlega "
                        "ustawowej ochronie rolnej (trudności z odrolnieniem i rozbudową)"
                    )
                    filter_result.score = max(0.0, filter_result.score - 10.0)

            # Acoustic Noise (>65 dB)
            if (listing.noise_level_db is not None and listing.noise_level_db > 65.0) or (
                listing.noise_zone and "WYSOKI" in listing.noise_zone
            ):
                db_str = f"{listing.noise_level_db:.0f}" if listing.noise_level_db is not None else ">65"
                filter_result.cons.append(
                    f"⚠️ Podwyższony poziom hałasu ({db_str} dB Lden): "
                    "Przekroczenie progu uciążliwości akustycznej w sąsiedztwie korytarza tranzytowego"
                )
                filter_result.score = max(0.0, filter_result.score - 15.0)

            # GDOŚ Nature protection
            if listing.nature_protected_zone:
                filter_result.cons.append(
                    f"⚠️ Obszar chroniony przyrodniczo (GDOŚ: {listing.nature_protected_zone}): "
                    "Rygory środowiskowe i ograniczenia inwestycyjne"
                )
                filter_result.score = max(0.0, filter_result.score - 10.0)

            # NID Monuments
            if listing.monument_zone:
                filter_result.cons.append(
                    f"🏛️ Obiekt w rejestrze zabytków / strefa konserwatorska (NID: {listing.monument_zone}): "
                    "Wszelkie prace budowlane wymagają uzgodnień z Wojewódzkim Konserwatorem Zabytków (WKZ)"
                )
                filter_result.score = max(0.0, filter_result.score - 15.0)

            # Cemetery Buffer
            if listing.cemetery_buffer_zone:
                if listing.cemetery_buffer_zone == "<50m":
                    filter_result.cons.append(
                        "🚨 Bezpośrednia strefa sanitarna cmentarza (<50m): Ustawowy zakaz rozbudowy "
                        "i lokalizacji okien mieszkalnych (Rozporządzenie MZ)"
                    )
                    filter_result.score = max(0.0, filter_result.score - 25.0)
                elif listing.cemetery_buffer_zone == "50-150m":
                    filter_result.cons.append(
                        "⚠️ Strefa ochronna cmentarza (50–150m): Ograniczenia sanitarne i warunki ujęć wody"
                    )
                    filter_result.score = max(0.0, filter_result.score - 10.0)

            if geo_audit:
                risks = geo_audit.get("surrounding_risks", [])
                if risks:
                    for r in risks:
                        if not any(
                            m in r
                            for m in (
                                "zagrożenia powodziowego",
                                "SOPO",
                                "osuwisk",
                                "hałas",
                                "GDOŚ",
                                "NID",
                                "cmentar",
                                "Gleba",
                                "EGiB",
                            )
                        ):
                            filter_result.cons.append(f"⚠️ Geoportal: {r}")
                    if any("Ba" in r or "Bi" in r or "Tk" in r for r in risks):
                        filter_result.score = max(0.0, filter_result.score - 25.0)

                p_num = geo_audit.get("main_parcel_number")
                p_area = geo_audit.get("cadastral_area")
                if p_num and p_area:
                    filter_result.pros.append(f"Zidentyfikowano działkę w Geoportalu: nr {p_num} ({p_area} m²)")

        result["qualified"] = filter_result.is_qualified

        # 4. Save or update in database
        db_model, is_new, price_changed = await repo.save_or_update(
            listing, filter_result, is_exact_coords=is_exact_coords
        )
        result["is_new"] = is_new
        result["price_changed"] = price_changed

        # 5. Dispatch notification if qualified and unnotified
        should_notify = filter_result.is_qualified and (
            (is_new and not result["is_duplicate_fingerprint"]) or price_changed
        )

        if should_notify and db_model.notified_at is None:
            logger.info(
                f"[Pipeline] Alerting on qualified offer: {listing.title} "
                f"[{filter_result.status.value}] (Score: {filter_result.score:.1f})"
            )
            # Calculate market negotiation advice
            if market_medians is None:
                market_medians = await repo.get_market_medians()
            local_median = resolve_local_median(
                market_medians,
                listing.city,
                listing.district,
                getattr(listing, "category", "dom"),
            )
            advice = analyze_negotiation(
                listing=listing,
                filter_result=filter_result,
                market_median_m2=local_median,
            )

            webhook_url = getattr(profile, "discord_webhook_url", None)
            discord_ok = await self.discord.send_notification(
                listing, filter_result, webhook_url=webhook_url, negotiation_advice=advice
            )
            telegram_ok = await self.telegram.send_notification(listing, filter_result, negotiation_advice=advice)

            if discord_ok or telegram_ok:
                await repo.mark_as_notified(db_model.id)
                result["notified"] = True

        return result

    async def run_cycle(self, target_profile: str | None = None) -> dict:
        """Run a complete scraping and processing cycle across active profiles."""
        cycle_started = time.perf_counter()
        logger.info("=== Starting Scraper Pipeline Cycle ===")
        from src.services.config_manager import config_manager

        cfg = config_manager.get_config()
        self.llm_analysis_enabled = bool(getattr(cfg, "llm_analysis_enabled", settings.USE_LLM_ANALYSIS))
        self.engine = QualificationEngine(llm_enabled=self.llm_analysis_enabled)
        if self.llm_analysis_enabled:
            logger.info("[Pipeline] AI LLM analysis enabled.")
        await init_db()

        total_scraped = 0
        total_new = 0
        total_duplicates = 0
        total_price_changes = 0
        total_qualified = 0
        total_notified = 0

        if self._custom_scrapers:
            execution_plan: list[tuple[SearchProfile | None, list[BaseScraper]]] = [(None, self.scrapers)]
            fresh_urls: set = set()
        else:
            profiles = cfg.get_active_profiles(target_profile)
            if not profiles:
                logger.warning("[Pipeline] No active search profiles found to scrape.")
                return {
                    "total_scraped": 0,
                    "new_listings": 0,
                    "duplicate_fingerprints": 0,
                    "price_changes": 0,
                    "qualified": 0,
                    "notified": 0,
                }
            async with get_session() as session:
                repo = ListingRepository(session)
                fresh_urls = set(
                    await repo.get_fresh_urls(
                        ["Otodom", "NieruchomosciOnline"],
                        within_hours=settings.DETAIL_REFRESH_HOURS,
                    )
                )
            logger.info(f"[Pipeline] {len(fresh_urls)} ogłoszeń ma świeże dane - szczegóły zostaną pominięte.")

            execution_plan = []
            for prof in profiles:
                scs: list[BaseScraper] = []
                p_portals = prof.enabled_portals
                if cfg.scrapers.otodom.enabled and (not p_portals or "otodom" in p_portals):
                    scs.append(
                        OtodomScraper(
                            max_pages=cfg.scrapers.otodom.max_pages, profile=prof, skip_detail_urls=fresh_urls
                        )
                    )
                if cfg.scrapers.olx.enabled and (not p_portals or "olx" in p_portals):
                    scs.append(OLXScraper(max_pages=cfg.scrapers.olx.max_pages, profile=prof))
                if cfg.scrapers.nieruchomosci_online.enabled and (not p_portals or "nieruchomosci_online" in p_portals):
                    scs.append(
                        NieruchomosciOnlineScraper(
                            max_pages=cfg.scrapers.nieruchomosci_online.max_pages,
                            profile=prof,
                            skip_detail_urls=fresh_urls,
                        )
                    )
                if cfg.scrapers.morizon.enabled and (not p_portals or "morizon" in p_portals):
                    scs.append(MorizonScraper(max_pages=cfg.scrapers.morizon.max_pages, profile=prof))
                execution_plan.append((prof, scs))

        flat_scrapers = []
        for profile, scrapers in execution_plan:
            prof_name = profile.name if profile else "Default"
            for scraper in scrapers:
                flat_scrapers.append((profile, prof_name, scraper))

        total_steps = len(flat_scrapers) or 1
        global_tracker.start_session(total_portals=total_steps)

        # Market medians are computed once per cycle (single full-table pass) and
        # shared across all portal batches.
        async with get_session() as session:
            medians_repo = ListingRepository(session)
            cycle_medians = await medians_repo.get_market_medians()
        t_medians = time.perf_counter() - cycle_started
        logger.debug(f"[Pipeline] Market medians computed in {t_medians:.2f}s.")

        # 1. Scrape all portals in parallel
        scrape_portal_times: list[tuple[str, float]] = []

        async def scrape_portal(prof, prof_name, scraper):
            t_start = time.perf_counter()
            if global_tracker.is_cancelled():
                return prof, prof_name, scraper.name, [], None
            global_tracker.update_portal(f"{scraper.name} ({prof_name})", 1, getattr(scraper, "max_pages", 1), 10)
            scraper.progress_cb = global_tracker.update_portal_page
            try:
                listings = await scraper.scrape()
                if global_tracker.is_cancelled():
                    return prof, prof_name, scraper.name, [], None
                global_tracker.record_items(count=len(listings))
                global_tracker.add_log(f"[{scraper.name} - {prof_name}] Pobrano {len(listings)} ogłoszeń.")
                logger.info(f"[{scraper.name} - {prof_name}] Scraped {len(listings)} listings.")
                return prof, prof_name, scraper.name, listings, None
            except Exception as e:
                logger.error(f"[Pipeline] Error running {scraper.name} for {prof_name}: {e}", exc_info=True)
                global_tracker.add_log(f"[{scraper.name} - {prof_name}] Błąd: {e}", level="error")
                return prof, prof_name, scraper.name, [], e
            finally:
                elapsed = time.perf_counter() - t_start
                scrape_portal_times.append((scraper.name, elapsed))
                logger.info(f"[Pipeline] [{scraper.name} - {prof_name}] scrape took {elapsed:.1f}s.")
                try:
                    await scraper.close()
                except Exception:
                    pass

        scrape_results = await asyncio.gather(*[scrape_portal(p, pn, sc) for p, pn, sc in flat_scrapers])
        t_scrape = time.perf_counter() - cycle_started - t_medians
        logger.info(f"[Pipeline] Scraping stage took {t_scrape:.1f}s total.")

        # 2. Concurrently process listings with Semaphore
        concurrency = getattr(settings, "CONCURRENT_REQUESTS", 3) or 3
        sem = asyncio.Semaphore(concurrency)

        t_process_start = time.perf_counter()
        step_idx = 0
        for prof, prof_name, _sc_name, listings, _err in scrape_results:
            if global_tracker.is_cancelled():
                logger.info("[Pipeline] Cancellation detected before processing batch, breaking loop.")
                break

            step_idx += 1
            total_scraped += len(listings)
            base_pct = int(((step_idx - 1) / total_steps) * 85)

            if not listings:
                continue

            processed = 0

            empty_cancel_res = {
                "is_new": False,
                "is_duplicate_fingerprint": False,
                "price_changed": False,
                "qualified": False,
                "notified": False,
            }

            async def safe_process(
                item,
                prof=prof,
                total_listings=len(listings),
                medians=cycle_medians,
                cancel_res=empty_cancel_res,
            ):
                nonlocal processed
                if global_tracker.is_cancelled():
                    return item, cancel_res
                async with sem:
                    if global_tracker.is_cancelled():
                        return item, cancel_res
                    async with get_session() as session:
                        repo = ListingRepository(session)
                        res = await self.process_listing(item, repo, profile=prof, market_medians=medians)
                    processed += 1
                    if processed % 5 == 0 or processed == total_listings:
                        global_tracker.update_processing(processed, total_listings)
                    return item, res

            results = await asyncio.gather(*[safe_process(item) for item in listings])

            for item, res in results:
                if res["is_new"]:
                    total_new += 1
                if res["is_duplicate_fingerprint"]:
                    total_duplicates += 1
                if res["price_changed"]:
                    total_price_changes += 1
                if res["qualified"]:
                    total_qualified += 1
                    if res["is_new"]:
                        global_tracker.add_log(
                            f"⭐ Nowa oferta [{prof_name}]: {item.title[:45]} ({item.price:,.0f} zł)",
                            level="success",
                        )
                if res["notified"]:
                    total_notified += 1

                global_tracker.record_items(
                    count=1,
                    qualified=1 if res["qualified"] and res["is_new"] else 0,
                    duplicates=1 if res["is_duplicate_fingerprint"] else 0,
                )

            step_pct = base_pct + int((step_idx / total_steps) * 85)
            global_tracker.percentage = step_pct

        t_process = time.perf_counter() - t_process_start
        portal_timings = ", ".join(f"{name}={elapsed:.1f}s" for name, elapsed in scrape_portal_times)
        logger.info(
            f"[Pipeline] Cycle timing: medians={t_medians:.1f}s, scrape={t_scrape:.1f}s "
            f"({portal_timings}), processing={t_process:.1f}s, "
            f"total={time.perf_counter() - cycle_started:.1f}s"
        )

        summary = {
            "total_scraped": total_scraped,
            "new_listings": total_new,
            "duplicate_fingerprints": total_duplicates,
            "price_changes": total_price_changes,
            "qualified": total_qualified,
            "notified": total_notified,
            "cancelled": global_tracker.is_cancelled(),
        }

        if global_tracker.is_cancelled():
            global_tracker.cancel_session()
            logger.info("=== Cycle Cancelled by User ===")
            return summary

        global_tracker.complete_session(summary)

        logger.info(
            f"=== Cycle Finished ===\n"
            f"Scraped: {total_scraped} | New: {total_new} | Duplicates: {total_duplicates} | "
            f"Price changes: {total_price_changes} | Qualified: {total_qualified} | Notified: {total_notified}"
        )
        return summary
