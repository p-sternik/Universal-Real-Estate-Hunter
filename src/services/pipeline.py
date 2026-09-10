import asyncio
from typing import Any, List, Optional
from loguru import logger

from config import settings
from src.filters import QualificationEngine
from src.models.enums import FinishCondition, HeatingType, QualificationStatus, SewerageType
from src.models.listing import ListingSchema
from src.scrapers import BaseScraper, MorizonScraper, NieruchomosciOnlineScraper, OLXScraper, OtodomScraper
from src.services.discord_notifier import DiscordNotifier
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
        scrapers: Optional[List[BaseScraper]] = None,
        discord_notifier: Optional[DiscordNotifier] = None,
        telegram_notifier: Optional[TelegramNotifier] = None,
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
        self.engine = QualificationEngine()

    async def process_listing(
        self,
        listing: ListingSchema,
        repo: ListingRepository,
        profile: Optional[Any] = None,
    ) -> dict:
        result = {
            "is_new": False,
            "is_duplicate_fingerprint": False,
            "price_changed": False,
            "qualified": False,
            "notified": False,
        }

        # 1. Check duplicate by fingerprint
        if listing.property_fingerprint:
            duplicate_model = await repo.find_duplicate_by_fingerprint(listing.property_fingerprint)
            if duplicate_model and duplicate_model.url != listing.url:
                logger.info(
                    f"[Pipeline] Found multi-agency/cross-portal duplicate for '{listing.title[:40]}' "
                    f"(matches existing ID {duplicate_model.id} from {duplicate_model.portal})."
                )
                result["is_duplicate_fingerprint"] = True

        # 1.5 Restore stored detail data when the detail fetch was skipped (fresh data)
        if listing.skip_detail:
            existing_model = await repo.get_by_url(listing.url) or await repo.get_by_portal_id(
                listing.portal, listing.id
            )
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

        # 2. Run two-stage qualification engine
        filter_result = await self.engine.evaluate_listing(listing, profile=profile)
        result["qualified"] = filter_result.is_qualified

        # 3. Resolve coordinates if missing
        is_exact_coords = True
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

        # 3.5. Audit location in Geoportal if qualified and coordinates are exact
        if listing.coordinates and is_exact_coords and filter_result.is_qualified:
            try:
                from src.services.geoportal import geoportal_service
                geo_audit = await geoportal_service.audit_location(
                    listing.coordinates[0], listing.coordinates[1], radius_meters=120
                )
                if geo_audit.get("main_parcel_id"):
                    listing.parcel_id = geo_audit["main_parcel_id"]
                    listing.cadastral_area = geo_audit.get("cadastral_area")
                    listing.geoportal_url = geo_audit["geoportal_url"]

                    risks = geo_audit.get("surrounding_risks", [])
                    if risks:
                        for r in risks:
                            filter_result.cons.append(f"⚠️ Geoportal: {r}")
                        filter_result.score = max(0.0, filter_result.score - 25.0)

                    p_num = geo_audit.get("main_parcel_number")
                    p_area = geo_audit.get("cadastral_area")
                    if p_num and p_area:
                        filter_result.pros.append(f"Zidentyfikowano działkę w Geoportalu: nr {p_num} ({p_area} m²)")
            except Exception as e:
                logger.debug(f"[Pipeline] Geoportal audit skipped: {e}")

        # 4. Save or update in database
        db_model, is_new, price_changed = await repo.save_or_update(
            listing, filter_result, is_exact_coords=is_exact_coords
        )
        result["is_new"] = is_new
        result["price_changed"] = price_changed

        # 5. Dispatch notification if qualified and unnotified
        should_notify = False
        if filter_result.is_qualified:
            if is_new and not result["is_duplicate_fingerprint"]:
                should_notify = True
            elif price_changed and filter_result.is_qualified:
                should_notify = True

        if should_notify and db_model.notified_at is None:
            logger.info(
                f"[Pipeline] Alerting on qualified offer: {listing.title} "
                f"[{filter_result.status.value}] (Score: {filter_result.score:.1f})"
            )
            webhook_url = getattr(profile, "discord_webhook_url", None)
            discord_ok = await self.discord.send_notification(listing, filter_result, webhook_url=webhook_url)
            telegram_ok = await self.telegram.send_notification(listing, filter_result)

            if discord_ok or telegram_ok:
                await repo.mark_as_notified(db_model.id)
                result["notified"] = True

        return result

    async def run_cycle(self, target_profile: Optional[str] = None) -> dict:
        """Run a complete scraping and processing cycle across active profiles."""
        logger.info("=== Starting Scraper Pipeline Cycle ===")
        from src.services.config_manager import config_manager
        cfg = config_manager.get_config()
        self.engine = QualificationEngine()
        await init_db()

        total_scraped = 0
        total_new = 0
        total_duplicates = 0
        total_price_changes = 0
        total_qualified = 0
        total_notified = 0

        if self._custom_scrapers:
            execution_plan = [(None, self.scrapers)]
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
                scs = []
                p_portals = prof.enabled_portals
                if cfg.scrapers.otodom.enabled and (not p_portals or "otodom" in p_portals):
                    scs.append(OtodomScraper(max_pages=cfg.scrapers.otodom.max_pages, profile=prof, skip_detail_urls=fresh_urls))
                if cfg.scrapers.olx.enabled and (not p_portals or "olx" in p_portals):
                    scs.append(OLXScraper(max_pages=cfg.scrapers.olx.max_pages, profile=prof))
                if cfg.scrapers.nieruchomosci_online.enabled and (not p_portals or "nieruchomosci_online" in p_portals):
                    scs.append(NieruchomosciOnlineScraper(max_pages=cfg.scrapers.nieruchomosci_online.max_pages, profile=prof, skip_detail_urls=fresh_urls))
                if cfg.scrapers.morizon.enabled and (not p_portals or "morizon" in p_portals):
                    scs.append(MorizonScraper(max_pages=cfg.scrapers.morizon.max_pages, profile=prof))
                execution_plan.append((prof, scs))

        total_steps = sum(len(scs) for _, scs in execution_plan) or 1
        global_tracker.start_session(total_portals=total_steps)

        step_idx = 0
        for profile, scrapers in execution_plan:
            prof_name = profile.name if profile else "Default"
            for scraper in scrapers:
                step_idx += 1
                base_pct = int(((step_idx - 1) / total_steps) * 85)
                global_tracker.update_portal(f"{scraper.name} ({prof_name})", 1, getattr(scraper, "max_pages", 1), base_pct + 5)
                scraper.progress_cb = global_tracker.update_portal_page
                try:
                    listings = await scraper.scrape()
                    total_scraped += len(listings)
                    global_tracker.record_items(count=len(listings))
                    global_tracker.add_log(f"[{scraper.name} - {prof_name}] Pobrano {len(listings)} ogłoszeń.")
                    logger.info(f"[{scraper.name} - {prof_name}] Scraped {len(listings)} listings. Processing...")

                    async with get_session() as session:
                        repo = ListingRepository(session)
                        processed = 0
                        for item in listings:
                            res = await self.process_listing(item, repo, profile=profile)
                            processed += 1
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
                            if processed % 5 == 0 or processed == len(listings):
                                global_tracker.update_processing(processed, len(listings))

                    step_pct = base_pct + int((step_idx / total_steps) * 85)
                    global_tracker.percentage = step_pct

                except Exception as e:
                    logger.error(f"[Pipeline] Error running {scraper.name} for {prof_name}: {e}", exc_info=True)
                    global_tracker.add_log(f"[{scraper.name} - {prof_name}] Błąd: {e}", level="error")
                finally:
                    try:
                        await scraper.close()
                    except Exception:
                        pass

        summary = {
            "total_scraped": total_scraped,
            "new_listings": total_new,
            "duplicate_fingerprints": total_duplicates,
            "price_changes": total_price_changes,
            "qualified": total_qualified,
            "notified": total_notified,
        }

        global_tracker.complete_session(summary)

        logger.info(
            f"=== Cycle Finished ===\n"
            f"Scraped: {total_scraped} | New: {total_new} | Duplicates: {total_duplicates} | "
            f"Price changes: {total_price_changes} | Qualified: {total_qualified} | Notified: {total_notified}"
        )
        return summary
