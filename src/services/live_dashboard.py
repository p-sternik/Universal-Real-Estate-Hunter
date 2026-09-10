import asyncio
import os
import webbrowser
from typing import Any, Dict, List
from aiohttp import web
from loguru import logger
from sqlalchemy import desc, select

from src.services.config_manager import config_manager
from src.services.pipeline import ScraperPipeline
from src.storage import ListingModel, ListingRepository, get_session

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "dashboard.html")

if os.path.exists(TEMPLATE_PATH):
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as _f:
        INDEX_HTML = _f.read()
else:
    INDEX_HTML = "<!DOCTYPE html><html><body><h1>Dashboard template not found</h1></body></html>"


class LiveDashboardServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.host = host
        self.port = port
        self.app = web.Application()
        self._setup_routes()

    def _setup_routes(self):
        self.app.router.add_get("/", self.handle_index)
        self.app.router.add_get("/api/listings", self.handle_get_listings)
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
        updated = config_manager.update_config(data)
        logger.info(
            f"[LiveDashboard] Updated search config: city={updated.city}, "
            f"radius={updated.distance_radius}km, max_price={updated.max_price:,.0f} PLN"
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
        ok = config_manager.delete_profile(profile_id)
        return web.json_response({"success": ok})

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
        if os.path.exists(TEMPLATE_PATH):
            try:
                with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                logger.warning(f"Could not read template dynamically: {e}")
        return web.Response(text=content, content_type="text/html", charset="utf-8")

    async def handle_get_listings(self, request: web.Request) -> web.Response:
        async with get_session() as session:
            stmt = select(ListingModel).order_by(
                desc(ListingModel.is_qualified),
                desc(ListingModel.qualification_score),
                desc(ListingModel.created_at),
            )
            res = await session.execute(stmt)
            items = res.scalars().all()

            data: List[Dict[str, Any]] = []
            for item in items:
                data.append({
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
                })

            return web.json_response(data)

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
        logger.info("[LiveDashboard] Manual scrape triggered via Web UI.")
        pipeline = ScraperPipeline()
        summary = await pipeline.run_cycle()
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

        local_url = f"http://{self.host}:{self.port}"
        logger.success(f"🚀 Live Preview Dashboard aktywny pod adresem: {local_url}")
        print(f"\n========================================================")
        print(f"  🏡 LIVE UNIVERSAL DASHBOARD & CRM DZIAŁA:")
        print(f"     {local_url}")
        print(f"  (Naciśnij Ctrl+C aby zatrzymać serwer)")
        print(f"========================================================\n")

        if auto_open:
            try:
                webbrowser.open(local_url)
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
