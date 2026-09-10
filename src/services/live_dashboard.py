import asyncio
import gzip
import hashlib
import json
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import selectinload

from src.services.config_manager import config_manager
from src.services.market_analyzer import analyze_land_and_utilities, analyze_negotiation, resolve_local_median
from src.services.pipeline import ScraperPipeline
from src.storage import ListingModel, ListingRepository, PriceHistoryModel, get_session

MIN_COMPRESS_SIZE = 1024
COMPRESSIBLE_CT = ("application/javascript", "application/json", "text/css", "text/html", "text/plain")


def _as_utc(dt: "datetime | None") -> "datetime | None":
    """Return dt with UTC tzinfo, normalising naive datetimes stored by SQLite."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt


@web.middleware
async def gzip_middleware(request: web.Request, handler):
    response = await handler(request)
    if response.status == 304 or response.body is None:
        return response
    if "Content-Encoding" in response.headers or "gzip" not in request.headers.get("Accept-Encoding", ""):
        return response
    if len(response.body) < MIN_COMPRESS_SIZE:
        return response
    if not (response.content_type or "").startswith(COMPRESSIBLE_CT):
        return response
    response.body = gzip.compress(response.body, compresslevel=6)
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Vary"] = "Accept-Encoding"
    response.headers["Content-Length"] = str(len(response.body))
    return response


TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html"
ASSET_DIR = Path(__file__).parent / "templates" / "assets"

ASSET_CONTENT_TYPES = {
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".map": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}

if TEMPLATE_PATH.exists():
    INDEX_HTML = TEMPLATE_PATH.read_text(encoding="utf-8")
else:
    INDEX_HTML = "<!DOCTYPE html><html><body><h1>Dashboard template not found</h1></body></html>"


class LiveDashboardServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = web.Application(middlewares=[gzip_middleware])
        self._active_scrape_task: asyncio.Task[Any] | None = None
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/assets/{path:.*}", self.handle_assets)
        self.app.router.add_get("/api/listings", self.handle_get_listings)
        self.app.router.add_get("/api/listings/{id}/price-history", self.handle_get_price_history)
        self.app.router.add_patch("/api/listings/{id}/status", self.handle_update_status)
        self.app.router.add_patch("/api/listings/{id}/notes", self.handle_update_notes)
        self.app.router.add_post("/api/geocode/backfill", self.handle_backfill_coords)
        self.app.router.add_get("/api/scrape/status", self.handle_scrape_status)
        self.app.router.add_post("/api/scrape", self.handle_trigger_scrape)
        self.app.router.add_post("/api/scrape/cancel", self.handle_cancel_scrape)
        self.app.router.add_get("/api/config", self.handle_get_config)
        self.app.router.add_post("/api/config", self.handle_update_config)
        self.app.router.add_get("/api/profiles", self.handle_get_profiles)
        self.app.router.add_post("/api/profiles", self.handle_add_or_update_profile)
        self.app.router.add_delete("/api/profiles/{id}", self.handle_delete_profile)
        self.app.router.add_post("/api/scrapers", self.handle_update_scrapers)
        self.app.router.add_get("/api/scheduler", self.handle_get_scheduler)
        self.app.router.add_post("/api/scheduler", self.handle_update_scheduler)
        self.app.router.add_post("/api/data/reset", self.handle_reset_data)

    async def handle_get_config(self, request: web.Request) -> web.Response:
        cfg = config_manager.get_config()
        data = cfg.model_dump()
        active = cfg.get_active_profile()
        for k, v in active.model_dump().items():
            if k not in data:
                data[k] = v
        return web.json_response(data)

    async def handle_update_config(self, request: web.Request) -> web.Response:
        data = await request.json()
        old_cfg = config_manager.get_config()
        old_profiles = {p.id: p for p in old_cfg.profiles}

        updated = config_manager.update_config(data)

        # If profiles array was provided, clean up listings for any deleted profiles
        if "profiles" in data and isinstance(data["profiles"], list):
            new_ids = {p.get("id") for p in data["profiles"] if p.get("id")}
            removed_ids = set(old_profiles.keys()) - new_ids
            if removed_ids:
                async with get_session() as session:
                    repo = ListingRepository(session)
                    for rid in removed_ids:
                        r_name = old_profiles[rid].name if rid in old_profiles else None
                        del_cnt = await repo.delete_by_profile(profile_id=rid, profile_name=r_name)
                        logger.info(f"[LiveDashboard] Usunięto profil '{rid}' oraz {del_cnt} powiązanych ofert.")

        price_display = f"{updated.max_price:,.0f} PLN" if updated.max_price is not None else "brak limitu"
        logger.info(
            f"[LiveDashboard] Updated search config: city={updated.city}, "
            f"radius={updated.distance_radius}km, max_price={price_display}"
        )
        resp_data = updated.model_dump()
        active = updated.get_active_profile()
        for k, v in active.model_dump().items():
            if k not in resp_data:
                resp_data[k] = v
        return web.json_response(resp_data)

    async def handle_get_profiles(self, request: web.Request) -> web.Response:
        profiles = [p.model_dump() for p in config_manager.get_config().profiles]
        return web.json_response(profiles)

    async def handle_add_or_update_profile(self, request: web.Request) -> web.Response:
        data = await request.json()
        saved = config_manager.add_or_update_profile(data)
        return web.json_response(saved.model_dump())

    async def handle_delete_profile(self, request: web.Request) -> web.Response:
        profile_id = request.match_info.get("id", "")
        cfg = config_manager.get_config()
        target_name = None
        for p in cfg.profiles:
            if p.id == profile_id:
                target_name = p.name
                break

        ok = config_manager.delete_profile(profile_id)
        deleted_count = 0
        if ok:
            async with get_session() as session:
                repo = ListingRepository(session)
                deleted_count = await repo.delete_by_profile(profile_id=profile_id, profile_name=target_name)
                logger.info(
                    f"[LiveDashboard] Usunięto profil '{profile_id}' oraz {deleted_count} powiązanych ofert z bazy."
                )

        return web.json_response({"success": ok, "deleted_listings": deleted_count})

    async def handle_update_scrapers(self, request: web.Request) -> web.Response:
        data = await request.json()
        cfg = config_manager.update_config({"scrapers": data})
        return web.json_response(cfg.scrapers.model_dump())

    async def handle_get_scheduler(self, request: web.Request) -> web.Response:
        cfg = config_manager.get_config()
        return web.json_response(cfg.scheduler.model_dump())

    async def handle_update_scheduler(self, request: web.Request) -> web.Response:
        data = await request.json()
        saved = config_manager.update_scheduler(data)
        logger.info(f"[LiveDashboard] Zaktualizowano konfigurację harmonogramu: {saved.model_dump()}")
        return web.json_response(saved.model_dump())

    async def handle_reset_data(self, request: web.Request) -> web.Response:
        data: dict[str, Any] = {}
        if request.can_read_body:
            try:
                data = await request.json()
            except Exception:
                data = {}
        if data.get("confirm") is not True:
            return web.json_response(
                {"error": 'Wymagane potwierdzenie: {"confirm": true}'},
                status=400,
            )

        profile_scope = str(data.get("profile") or "").strip()
        async with get_session() as session:
            repo = ListingRepository(session)
            if profile_scope and profile_scope.upper() != "ALL":
                target_name = None
                for p in config_manager.get_config().profiles:
                    if p.id == profile_scope or p.name.lower() == profile_scope.lower():
                        target_name = p.name
                        break
                deleted = await repo.delete_by_profile(profile_id=profile_scope, profile_name=target_name)
            else:
                deleted = await repo.delete_all_listings()

        scope_label = profile_scope or "ALL"
        logger.warning(f"[LiveDashboard] Reset danych: usunięto {deleted} ofert (zakres: {scope_label}).")
        return web.json_response({"success": True, "deleted_listings": deleted, "scope": scope_label})

    async def handle_scrape_status(self, request: web.Request) -> web.Response:
        from src.services.progress import global_tracker

        return web.json_response(global_tracker.get_status_payload())

    async def handle_index(self, request: web.Request) -> web.Response:
        content = INDEX_HTML
        if TEMPLATE_PATH.exists():
            try:
                content = TEMPLATE_PATH.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read template dynamically: {e}")
        return web.Response(text=content, content_type="text/html", charset="utf-8")

    async def handle_assets(self, request: web.Request) -> web.Response:
        rel = str(request.match_info.get("path", ""))
        asset_path = (ASSET_DIR / rel).resolve()
        assets_root = ASSET_DIR.resolve()
        if not asset_path.is_relative_to(assets_root) or not asset_path.is_file():
            return web.Response(status=404, text="Not found")
        content = asset_path.read_bytes()
        etag = f'"{hashlib.md5(content, usedforsecurity=False).hexdigest()}"'
        if request.headers.get("If-None-Match") == etag:
            return web.Response(status=304)
        ctype = ASSET_CONTENT_TYPES.get(asset_path.suffix.lower(), "application/octet-stream")
        return web.Response(
            body=content,
            content_type=ctype,
            charset=None,
            headers={"ETag": etag, "Cache-Control": "no-cache"},
        )

    async def handle_get_price_history(self, request: web.Request) -> web.Response:
        listing_id = int(request.match_info["id"])
        async with get_session() as session:
            stmt = (
                select(PriceHistoryModel)
                .where(PriceHistoryModel.listing_id == listing_id)
                .order_by(PriceHistoryModel.recorded_at.desc())
            )
            res = await session.execute(stmt)
            items = res.scalars().all()
            data = [
                {
                    "price": h.price,
                    "price_per_m2": h.price_per_m2,
                    "date": h.recorded_at.isoformat() if h.recorded_at else None,
                }
                for h in items
            ]
            return web.json_response(data)

    async def handle_get_listings(self, request: web.Request) -> web.Response:
        prof_filter = request.query.get("profile")
        async with get_session() as session:
            stmt = select(ListingModel).options(selectinload(ListingModel.price_history))
            if prof_filter and prof_filter.upper() != "ALL":
                cfg = config_manager.get_config()
                matched_prof = None
                for p in cfg.profiles:
                    if p.id == prof_filter or p.name.lower() == prof_filter.lower():
                        matched_prof = p
                        break
                conds = [ListingModel.profile_id == prof_filter, ListingModel.profile_name == prof_filter]
                if matched_prof:
                    conds.append(ListingModel.profile_id == matched_prof.id)
                    conds.append(ListingModel.profile_name == matched_prof.name)
                # If checking default profile, also match records where profile_id is None
                if prof_filter == "default" or (matched_prof and matched_prof.id == "default"):
                    conds.append(ListingModel.profile_id.is_(None))
                stmt = stmt.where(or_(*conds))

            stmt = stmt.order_by(
                desc(ListingModel.is_qualified),
                desc(ListingModel.qualification_score),
                desc(ListingModel.created_at),
            )
            res = await session.execute(stmt)
            items = res.scalars().all()

            repo = ListingRepository(session)
            market_medians = await repo.get_market_medians()

            now_utc = datetime.now(UTC)
            max_scraped_at = None
            for it in items:
                if (sa := _as_utc(it.last_scraped_at)) and (max_scraped_at is None or sa > max_scraped_at):
                    max_scraped_at = sa

            data: list[dict[str, Any]] = []
            for item in items:
                # Compute price drop from price_history
                price_drop_amount = None
                price_drop_pct = None
                initial_price = None
                ph = item.price_history or []
                if len(ph) >= 2:
                    # price_history ordered desc by recorded_at, so last entry = oldest
                    oldest = ph[-1]
                    initial_price = oldest.price
                    if initial_price and initial_price > item.price:
                        price_drop_amount = round(initial_price - item.price)
                        price_drop_pct = round((price_drop_amount / initial_price) * 100, 1)

                # Delta analysis (cycle additions & updates)
                created_utc = _as_utc(item.created_at)
                updated_utc = _as_utc(item.updated_at)

                is_new_cycle = bool(
                    created_utc
                    and (
                        (max_scraped_at is not None and (max_scraped_at - created_utc).total_seconds() <= 10800)
                        or (now_utc - created_utc).total_seconds() <= 86400
                    )
                )

                is_updated_cycle = bool(
                    len(ph) >= 2
                    or (
                        updated_utc
                        and created_utc
                        and (updated_utc - created_utc).total_seconds() > 300
                        and (
                            (max_scraped_at is not None and (max_scraped_at - updated_utc).total_seconds() <= 10800)
                            or (now_utc - updated_utc).total_seconds() <= 86400
                        )
                    )
                )

                local_median = resolve_local_median(
                    market_medians,
                    item.city,
                    item.district,
                    item.category,
                )
                neg_advice = analyze_negotiation(
                    listing=item,
                    market_median_m2=local_median,
                    price_drop_amount=float(price_drop_amount or 0.0),
                    price_drop_pct=float(price_drop_pct or 0.0),
                    price_history_count=len(ph),
                )
                land_audit = analyze_land_and_utilities(item, market_median_m2=local_median)

                data.append(
                    {
                        "id": item.id,
                        "portal": item.portal,
                        "portal_id": item.portal_id,
                        "url": item.url,
                        "title": item.title,
                        "price": item.price,
                        "price_per_m2": item.price_per_m2,
                        "area_home": item.area_home,
                        "area_plot": item.area_plot,
                        "building_type": item.building_type,
                        "segment_subtype": item.segment_subtype,
                        "location_raw": item.location_raw,
                        "street": item.street,
                        "district": item.district,
                        "city": item.city,
                        "latitude": item.latitude,
                        "longitude": item.longitude,
                        "is_exact_coords": item.is_exact_coords,
                        "parcel_id": item.parcel_id,
                        "cadastral_area": item.cadastral_area,
                        "geoportal_url": item.geoportal_url,
                        "mpzp_zone": item.mpzp_zone,
                        "mpzp_status": item.mpzp_status,
                        "flood_risk_zone": item.flood_risk_zone,
                        "user_status": item.user_status or "NEW",
                        "user_notes": item.user_notes or "",
                        "access_road_type": item.access_road_type,
                        "market": item.market,
                        "finish_condition": item.finish_condition or "nieokreślony",
                        "has_visualisations": item.has_visualisations,
                        "sewerage": item.sewerage,
                        "heating": item.heating,
                        "has_fiber": item.has_fiber,
                        "year_built": item.year_built,
                        "category": item.category or "dom",
                        "rooms": item.rooms,
                        "floor": item.floor,
                        "floors_in_building": item.floors_in_building,
                        "is_private_owner": item.is_private_owner,
                        "profile_id": item.profile_id or "default",
                        "profile_name": item.profile_name,
                        "main_image_url": item.main_image_url,
                        "gallery_images": item.gallery_images,
                        "is_qualified": item.is_qualified,
                        "qualification_status": item.qualification_status,
                        "qualification_score": item.qualification_score,
                        "filter_reasons": item.filter_reasons,
                        "pros": item.pros,
                        "cons": item.cons,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                        "last_scraped_at": item.last_scraped_at.isoformat() if item.last_scraped_at else None,
                        "is_new_cycle": is_new_cycle,
                        "is_updated_cycle": is_updated_cycle,
                        # AI Due Diligence
                        "ai_summary": item.ai_summary,
                        "ai_verdict": item.ai_verdict,
                        "worth_interest": item.worth_interest,
                        "ai_questions": item.ai_questions,
                        "contact_phone": item.contact_phone,
                        "contact_person": item.contact_person,
                        # Price Drop History
                        "price_drop_amount": price_drop_amount,
                        "price_drop_pct": price_drop_pct,
                        "initial_price": initial_price,
                        "price_history_count": len(ph),
                        # Negotiation & Market Intelligence
                        "market_median_m2": neg_advice.market_median_m2,
                        "price_deviation_pct": neg_advice.price_deviation_pct,
                        "days_on_market": neg_advice.days_on_market,
                        "negotiation_leverage": neg_advice.negotiation_leverage,
                        "fair_market_value": neg_advice.fair_market_value,
                        "suggested_opening_offer": neg_advice.suggested_opening_offer,
                        "negotiation_arguments": neg_advice.arguments,
                        # Automated Intelligence: TCO, Commute, Risk
                        "land_audit": land_audit,
                    }
                )

            body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            etag = f'"{hashlib.md5(body, usedforsecurity=False).hexdigest()}"'
            if request.headers.get("If-None-Match") == etag:
                return web.Response(status=304)
            return web.json_response(body=body, headers={"ETag": etag})

    async def handle_update_status(self, request: web.Request) -> web.Response:
        listing_id = int(request.match_info["id"])
        data = await request.json()
        new_status = data.get("status", "NEW")

        async with get_session() as session:
            repo = ListingRepository(session)
            item = await repo.update_user_status(listing_id, new_status)
            if not item:
                return web.json_response({"error": "Listing not found"}, status=404)
            await session.commit()
            logger.info(f"[LiveDashboard] Listing #{listing_id} status updated to: {new_status}")
            return web.json_response({"success": True, "id": listing_id, "user_status": new_status})

    async def handle_update_notes(self, request: web.Request) -> web.Response:
        listing_id = int(request.match_info["id"])
        data = await request.json()
        notes = data.get("notes", "")

        async with get_session() as session:
            repo = ListingRepository(session)
            item = await repo.update_user_notes(listing_id, notes)
            if not item:
                return web.json_response({"error": "Listing not found"}, status=404)
            await session.commit()
            logger.info(f"[LiveDashboard] Listing #{listing_id} notes updated.")
            return web.json_response({"success": True, "id": listing_id, "user_notes": notes})

    async def handle_backfill_coords(self, request: web.Request) -> web.Response:
        from src.services.geocoder import backfill_missing_coordinates

        count = await backfill_missing_coordinates()
        return web.json_response({"success": True, "updated": count})

    async def _run_scrape_background(self, target_profile: str | None = None) -> None:
        from src.services.progress import global_tracker

        try:
            pipeline = ScraperPipeline()
            await pipeline.run_cycle(target_profile=target_profile)
        except asyncio.CancelledError:
            logger.info("[LiveDashboard] Background scrape task cancelled.")
            global_tracker.cancel_session()
        except Exception as e:
            logger.error(f"[LiveDashboard] Background scrape error: {e}", exc_info=True)
            global_tracker.add_log(f"Błąd krytyczny scrapingu: {e}", level="error")
            global_tracker.complete_session({"error": str(e)})
        finally:
            self._active_scrape_task = None

    async def handle_trigger_scrape(self, request: web.Request) -> web.Response:
        from src.services.progress import global_tracker

        if global_tracker.is_running:
            return web.json_response(
                {"status": "already_running", "message": "Scraping jest już w toku."},
                status=409,
            )

        target_profile = request.query.get("profile")
        if not target_profile and request.can_read_body and (request.content_length or 0) > 0:
            try:
                body = await request.json()
                if isinstance(body, dict):
                    target_profile = body.get("profile")
            except Exception:
                pass

        if target_profile and isinstance(target_profile, str):
            target_profile = target_profile.strip()
            if target_profile.upper() in ("ALL", "NULL", "NONE", ""):
                target_profile = None

        logger.info(f"[LiveDashboard] Manual scrape triggered via Web UI (target_profile: {target_profile}).")
        self._active_scrape_task = asyncio.create_task(self._run_scrape_background(target_profile=target_profile))
        return web.json_response({"status": "started", "message": "Scraping uruchomiony w tle."})

    async def handle_cancel_scrape(self, request: web.Request) -> web.Response:
        from src.services.progress import global_tracker

        logger.info("[LiveDashboard] Stop scrape requested via Web UI.")
        if not global_tracker.is_running:
            return web.json_response(
                {"status": "not_running", "message": "Scraping nie jest obecnie uruchomiony."},
                status=200,
            )

        global_tracker.request_cancel()
        return web.json_response({"status": "cancelling", "message": "Zażądano zatrzymania scrapingu."})

    async def run(self, auto_open: bool = True):
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        try:
            await site.start()
        except OSError as e:
            if getattr(e, "errno", None) in (10048, 48, 98):  # WinError 10048 / EADDRINUSE
                logger.error(
                    f"Port {self.port} jest już zajęty przez inny proces (np. działający w tle serwer dashboardu). "
                    f"Zatrzymaj poprzedni proces lub wybierz inny port, np.: python main.py dashboard --port {self.port + 1}"
                )
                await runner.cleanup()
                return
            raise

        display_host = "127.0.0.1" if self.host in ("0.0.0.0", "") else self.host
        display_url = f"http://{display_host}:{self.port}"
        logger.success(
            f"🚀 Live Preview Dashboard aktywny pod adresem: {display_url} (nasłuch na {self.host}:{self.port})"
        )
        print("\n========================================================")
        print("  🏡 LIVE UNIVERSAL DASHBOARD & CRM DZIAŁA:")
        print(f"     {display_url}")
        print("  (Naciśnij Ctrl+C aby zatrzymać serwer)")
        print("========================================================\n")

        if auto_open:
            try:
                webbrowser.open(display_url)
            except Exception as e:
                logger.debug(f"Could not open browser automatically: {e}")

        try:
            while True:
                await asyncio.sleep(3600)
        except (asyncio.CancelledError, KeyboardInterrupt):
            pass
        finally:
            await runner.cleanup()
            logger.info("[LiveDashboard] Serwer zatrzymany.")
