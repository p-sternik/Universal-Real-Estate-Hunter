import asyncio
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.database import get_session, safe_commit
from src.storage.models import GeocacheModel, ListingModel

# Well-known centroids for Rzeszów districts and surrounding towns
RZESZOW_DISTRICT_CENTROIDS = {
    "słocina": (50.0242, 22.0520),
    "slocina": (50.0242, 22.0520),
    "zalesie": (50.0150, 22.0250),
    "staromieście": (50.0610, 22.0120),
    "staromiescie": (50.0610, 22.0120),
    "drabinianka": (50.0130, 22.0010),
    "budziwój": (49.9720, 21.9890),
    "budziwoj": (49.9720, 21.9890),
    "biała": (49.9880, 22.0180),
    "biala": (49.9880, 22.0180),
    "przybyszówka": (50.0350, 21.9450),
    "przybyszowka": (50.0350, 21.9450),
    "baranówka": (50.0520, 21.9780),
    "baranowka": (50.0520, 21.9780),
    "wilkowyja": (50.0380, 22.0400),
    "załęże": (50.0560, 22.0390),
    "zaleze": (50.0560, 22.0390),
    "pobitno": (50.0410, 22.0290),
    "nowe miasto": (50.0280, 22.0080),
    "krasne": (50.0430, 22.0830),
    "trzebownisko": (50.0780, 22.0520),
    "nowa wieś": (50.0980, 22.0550),
    "nowa wies": (50.0980, 22.0550),
    "jasionka": (50.1110, 22.0620),
    "tajęcina": (50.1250, 22.0350),
    "tajecina": (50.1250, 22.0350),
    "zaczernie": (50.0920, 22.0150),
    "głogów małopolski": (50.1510, 21.9610),
    "glogow malopolski": (50.1510, 21.9610),
    "głogów młp": (50.1510, 21.9610),
    "glogow mlp": (50.1510, 21.9610),
    "boguchwała": (49.9840, 21.9390),
    "boguchwala": (49.9840, 21.9390),
    "tyczyn": (49.9650, 22.0350),
    "świlcza": (50.0680, 21.8980),
    "swilcza": (50.0680, 21.8980),
    "bratkowice": (50.0950, 21.8100),
    "rudna mała": (50.0950, 21.9750),
    "rudna mala": (50.0950, 21.9750),
    "rudna wielka": (50.0820, 21.9350),
    "malawa": (50.0210, 22.0910),
    "chmielnik": (49.9780, 22.1400),
    "łańcut": (50.0690, 22.2310),
    "lancut": (50.0690, 22.2310),
    "rzeszów": (50.0375, 22.0047),
    "rzeszow": (50.0375, 22.0047),
}


class NominatimGeocoder:
    def __init__(self) -> None:
        self.base_url = "https://nominatim.openstreetmap.org/search"
        self.headers = {"User-Agent": "RzeszowPropertyHunter/1.0 (automated house monitor; rzeszow-hunter@local)"}
        self._lock = asyncio.Lock()
        self._last_request_time = 0.0
        # In-memory cache for the current process/cycle (avoids repeat DB + HTTP hits).
        self._mem_cache: dict[str, tuple[float, float, str]] = {}

    async def _rate_limited_query(self, query: str) -> dict | None:
        """Query OSM Nominatim respecting 1 req/sec rate limit."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_request_time
            if elapsed < 1.1:
                await asyncio.sleep(1.1 - elapsed)

            params: dict[str, Any] = {
                "q": query,
                "format": "json",
                "limit": 1,
                "countrycodes": "pl",
                "addressdetails": 1,
            }

            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await client.get(self.base_url, params=params, headers=self.headers)
                    self._last_request_time = time.time()
                    if resp.status_code == 200:
                        data = resp.json()
                        if data and isinstance(data, list) and len(data) > 0:
                            return data[0]
                    else:
                        logger.warning(f"Nominatim returned status {resp.status_code} for query: {query}")
            except Exception as e:
                logger.warning(f"Nominatim query failed for '{query}': {e}")
                self._last_request_time = time.time()

        return None

    async def get_cached(self, session: AsyncSession | None, query_key: str) -> tuple[float, float, str] | None:
        if query_key in self._mem_cache:
            return self._mem_cache[query_key]
        try:
            if session is not None:
                cached = await session.get(GeocacheModel, query_key)
                if cached:
                    val = (cached.latitude, cached.longitude, cached.display_name or "")
                    self._mem_cache[query_key] = val
                    return val
            else:
                async with get_session() as s:
                    cached = await s.get(GeocacheModel, query_key)
                    if cached:
                        val = (cached.latitude, cached.longitude, cached.display_name or "")
                        self._mem_cache[query_key] = val
                        return val
        except Exception as e:
            logger.debug(f"[Geocoder] Failed to read cache for '{query_key}': {e}")
        return None

    async def set_cache(
        self,
        session: AsyncSession | None,
        query_key: str,
        lat: float,
        lon: float,
        display_name: str,
    ) -> None:
        self._mem_cache[query_key] = (lat, lon, display_name)
        try:
            async with get_session() as write_session:
                existing = await write_session.get(GeocacheModel, query_key)
                if existing:
                    existing.latitude = lat
                    existing.longitude = lon
                    existing.display_name = display_name
                    existing.cached_at = datetime.now(UTC)
                else:
                    cache_entry = GeocacheModel(
                        query=query_key,
                        latitude=lat,
                        longitude=lon,
                        display_name=display_name,
                        cached_at=datetime.now(UTC),
                    )
                    write_session.add(cache_entry)
                await safe_commit(write_session)
        except Exception as e:
            logger.debug(f"[Geocoder] Failed to persist cache for '{query_key}': {e}")

    def _find_district_fallback(
        self,
        street: str | None,
        district: str | None,
        city: str | None,
        location_raw: str | None,
    ) -> tuple[float, float] | None:
        haystack = f"{street or ''} {district or ''} {city or ''} {location_raw or ''}".lower()
        from src.services.config_manager import CITY_CENTROIDS

        for c_name, coords in CITY_CENTROIDS.items():
            if re.search(rf"\b{re.escape(c_name)}\b", haystack):
                return coords
        for key, coords in RZESZOW_DISTRICT_CENTROIDS.items():
            if re.search(rf"\b{re.escape(key)}\b", haystack):
                return coords
        return None

    async def geocode(
        self,
        session: AsyncSession | None = None,
        street: str | None = None,
        district: str | None = None,
        city: str | None = None,
        location_raw: str | None = None,
    ) -> tuple[float | None, float | None, bool]:
        """
        Resolves (latitude, longitude, is_exact).
        Returns is_exact=True if resolved via street-level Nominatim,
        or is_exact=False if resolved via district/city fallback.
        """
        city_name = (city or "").strip()
        if not city_name and location_raw:
            tokens = [t.strip() for t in location_raw.split(",") if t.strip()]
            if tokens:
                city_name = tokens[0]

        # 1. Try Street + City on Nominatim
        if street:
            clean_street = street.replace("ul.", "").replace("ulica", "").strip()
            query = f"{clean_street}, {city_name}, Polska" if city_name else f"{clean_street}, Polska"
            query_key = f"street:{query}".lower()

            cached = await self.get_cached(session, query_key)
            if cached:
                return (cached[0], cached[1], True)

            data = await self._rate_limited_query(query)
            if data:
                lat = float(data["lat"])
                lon = float(data["lon"])
                display = data.get("display_name", "")
                await self.set_cache(session, query_key, lat, lon, display)
                return (lat, lon, True)

        # 2. Try District + City on Nominatim
        if district or city_name:
            target_area = district or city_name
            query = (
                f"{target_area}, {city_name}, Polska"
                if district and city_name and district != city_name
                else f"{target_area}, Polska"
            )
            query_key = f"district:{query}".lower()

            cached = await self.get_cached(session, query_key)
            if cached:
                return (cached[0], cached[1], False)

            data = await self._rate_limited_query(query)
            if data:
                lat = float(data["lat"])
                lon = float(data["lon"])
                display = data.get("display_name", "")
                await self.set_cache(session, query_key, lat, lon, display)
                return (lat, lon, False)

        # 3. Try Instant Offline Centroid Fallback
        fallback = self._find_district_fallback(street, district, city_name, location_raw)
        if fallback:
            return (fallback[0], fallback[1], False)

        # 4. No location resolved - leave coordinates empty (no misleading pin)
        return (None, None, False)


async def geocode_many(
    session: AsyncSession | None = None,
    items: list[dict[str, str | None]] | None = None,
    batch_size: int = 8,
) -> list[tuple[float | None, float | None, bool]]:
    if items is None:
        items = []
    """Resolve multiple addresses with bounded concurrency.

    DB/memory cache hits never touch the network; the 1 req/s Nominatim lock
    still serializes real HTTP calls, but cache lookups and fallbacks run
    concurrently in batches.
    """
    sem = asyncio.Semaphore(max(1, batch_size))
    results: list[tuple[float | None, float | None, bool] | None] = [None] * len(items)

    async def _one(idx: int, item: dict[str, str | None]) -> None:
        async with sem:
            results[idx] = await geocoder.geocode(
                session=session,
                street=item.get("street"),
                district=item.get("district"),
                city=item.get("city"),
                location_raw=item.get("location_raw"),
            )

    await asyncio.gather(*[_one(i, it) for i, it in enumerate(items)])
    return [r or (None, None, False) for r in results]


# Singleton instance
geocoder = NominatimGeocoder()


async def backfill_missing_coordinates(limit: int = 200) -> int:
    """Finds listings with NULL coordinates and fills them in."""
    updated_count = 0
    async with get_session() as session:
        stmt = (
            select(ListingModel)
            .where((ListingModel.latitude.is_(None)) | (ListingModel.longitude.is_(None)))
            .limit(limit)
        )
        res = await session.execute(stmt)
        missing_items = list(res.scalars().all())

        if not missing_items:
            logger.info("No listings need coordinate backfill.")
            return 0

        logger.info(f"Backfilling coordinates for {len(missing_items)} listings...")
        for item in missing_items:
            lat, lon, is_exact = await geocoder.geocode(
                session=session,
                street=item.street,
                district=item.district,
                city=item.city,
                location_raw=item.location_raw,
            )
            if lat and lon:
                item.latitude = lat
                item.longitude = lon
                item.is_exact_coords = is_exact
                updated_count += 1
                logger.debug(f"Geocoded '{item.title[:30]}': ({lat:.4f}, {lon:.4f}) [exact={is_exact}]")

        await safe_commit(session)
        logger.success(f"Successfully backfilled {updated_count} listing coordinates.")

    return updated_count
