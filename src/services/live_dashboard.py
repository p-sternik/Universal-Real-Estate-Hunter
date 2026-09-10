import asyncio
import gzip
import hashlib
import json
import webbrowser
from pathlib import Path
from typing import Any

from aiohttp import web
from loguru import logger
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import selectinload

from src.services.config_manager import config_manager
from src.services.pipeline import ScraperPipeline
from src.storage import ListingModel, ListingRepository, PriceHistoryModel, get_session

MIN_COMPRESS_SIZE = 1024
COMPRESSIBLE_CT = ("application/json", "text/html", "text/plain")


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

if TEMPLATE_PATH.exists():
    INDEX_HTML = TEMPLATE_PATH.read_text(encoding="utf-8")
else:
    INDEX_HTML = "<!DOCTYPE html><html><body><h1>Dashboard template not found</h1></body></html>"


class LiveDashboardServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8080):
        self.host = host
        self.port = port
        self.app = web.Application(middlewares=[gzip_middleware])
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/api/listings", self.handle_get_listings)
        self.app.router.add_get("/api/listings/{id}/price-history", self.handle_get_price_history)
        self.app.router.add_patch("/api/listings/{id}/status", self.handle_update_status)
        self.app.router.add_patch("/api/listings/{id}/notes", self.handle_update_notes)
        self.app.router.add_post("/api/geocode/backfill", self.handle_backfill_coords)
        self.app.router.add_get("/api/scrape/status", self.handle_scrape_status)
        self.app.router.add_post("/api/scrape", self.handle_trigger_scrape)
        self.app.router.add_get("/api/config", self.handle_get_config)
        self.app.router.add_post("/api/config", self.handle_update_config)
        self.app.router.add_get("/api/profiles", self.handle_get_profiles)
        self.app.router.add_post("/api/profiles", self.handle_add_or_update_profile)
        self.app.router.add_delete("/api/profiles/{id}", self.handle_delete_profile)
        self.app.router.add_post("/api/scrapers", self.handle_update_scrapers)
        self.app.router.add_get("/api/scheduler", self.handle_get_scheduler)
        self.app.router.add_post("/api/scheduler", self.handle_update_scheduler)

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
                        "is_exact_coords": getattr(item, "is_exact_coords", True),
                        "parcel_id": getattr(item, "parcel_id", None),
                        "cadastral_area": getattr(item, "cadastral_area", None),
                        "geoportal_url": getattr(item, "geoportal_url", None),
                        "user_status": getattr(item, "user_status", "NEW") or "NEW",
                        "user_notes": getattr(item, "user_notes", "") or "",
                        "access_road_type": item.access_road_type,
                        "market": getattr(item, "market", "nieokreślony"),
                        "finish_condition": getattr(item, "finish_condition", "nieokreślony") or "nieokreślony",
                        "has_visualisations": bool(getattr(item, "has_visualisations", False)),
                        "sewerage": getattr(item, "sewerage", "nieznana") or "nieznana",
                        "heating": getattr(item, "heating", "nieznane") or "nieznane",
                        "has_fiber": bool(getattr(item, "has_fiber", False)),
                        "year_built": getattr(item, "year_built", None),
                        "category": getattr(item, "category", "dom") or "dom",
                        "rooms": getattr(item, "rooms", None),
                        "floor": getattr(item, "floor", None),
                        "floors_in_building": getattr(item, "floors_in_building", None),
                        "is_private_owner": getattr(item, "is_private_owner", None),
                        "profile_id": getattr(item, "profile_id", None) or "default",
                        "profile_name": getattr(item, "profile_name", None),
                        "main_image_url": item.main_image_url,
                        "gallery_images": getattr(item, "gallery_images", []) or [],
                        "is_qualified": item.is_qualified,
                        "qualification_status": item.qualification_status,
                        "qualification_score": item.qualification_score,
                        "filter_reasons": item.filter_reasons,
                        "pros": item.pros,
                        "cons": item.cons,
                        "created_at": item.created_at.isoformat() if item.created_at else None,
                        # AI Due Diligence
                        "ai_summary": getattr(item, "ai_summary", None),
                        "ai_questions": getattr(item, "ai_questions", []) or [],
                        "contact_phone": getattr(item, "contact_phone", None),
                        "contact_person": getattr(item, "contact_person", None),
                        # Price Drop History
                        "price_drop_amount": price_drop_amount,
                        "price_drop_pct": price_drop_pct,
                        "initial_price": initial_price,
                        "price_history_count": len(ph),
                    }
                )

            body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            etag = f'"{hashlib.md5(body).hexdigest()}"'
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

    async def handle_trigger_scrape(self, request: web.Request) -> web.Response:
        target_profile = request.query.get("profile")
        if not target_profile and request.can_read_body:
            try:
                body = await request.json()
                target_profile = body.get("profile")
            except Exception:
                pass
        if target_profile and target_profile.upper() == "ALL":
            target_profile = None

        logger.info(f"[LiveDashboard] Manual scrape triggered via Web UI (target_profile: {target_profile}).")
        pipeline = ScraperPipeline()
        summary = await pipeline.run_cycle(target_profile=target_profile)
        return web.json_response(summary)

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
