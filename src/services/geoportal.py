import asyncio
import math
import re
from typing import Any

import httpx
from loguru import logger


class GeoportalService:
    """
    Integration with Polish National Geoportal (GUGiK) APIs:
    1. ULDK API (Usługa Lokalizacji Działek Katastralnych - uldk.gugik.gov.pl):
       - Resolves exact cadastral parcel (TERYT, nr działki, obręb, gmina).
       - Fetches parcel boundary geometry in EPSG:2180 and calculates exact area in m².
    2. KIEG WMS (Krajowa Integracja Ewidencji Gruntów):
       - Resolves official land use contour (klasoużytki) of the parcel.
       - Audits surrounding parcels within a given radius (e.g. 120m) for industrial ('Ba'),
         commercial ('Bi'), railway ('Tk'), or other high-impact activities.
    3. Direct deep-linking:
       - Generates direct map URLs to Geoportal Krajowy for any parcel or coordinates.
    """

    ULDK_BASE = "https://uldk.gugik.gov.pl/"
    KIEG_WMS = "https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow"
    KIMPZP_WMS = (
        "https://mapy.geoportal.gov.pl/wss/ext/KrajowaIntegracjaMiejscowychPlanowZagospodarowaniaPrzestrzennego"
    )
    ISOK_FLOOD_WMS = "https://wody.isok.gov.pl/wss/INSPIRE/INSPIRE_NZ_HY_MZPMRP_WMS"

    def __init__(self, request_timeout: float = 6.0):
        self.timeout = request_timeout
        self.headers = {"User-Agent": "ApartmentHunter-Geoportal/1.0 (property-research-suite; contact@local)"}
        self._cache: dict[str, Any] = {}

    @staticmethod
    def generate_gunb_url(parcel_id: str | None = None) -> str:
        """Generates direct URL to GUNB building permit (RWDZ) search portal."""
        _ = parcel_id
        return "https://wyszukiwarka.gunb.gov.pl/"

    def generate_geoportal_url(
        self,
        parcel_id: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
    ) -> str:
        """Generates a direct clickable link to the National Geoportal map."""
        if parcel_id:
            return f"https://mapy.geoportal.gov.pl/imap/Imgp_2.html?identifyParcel={parcel_id}"
        if lat is not None and lon is not None:
            return (
                f"https://mapy.geoportal.gov.pl/imap/Imgp_2.html?locale=pl&gui=new&"
                f"session=%7B%22actions%22%3A%5B%7B%22name%22%3A%22locatePoint%22%2C"
                f"%22params%22%3A%7B%22x%22%3A{lon}%2C%22y%22%3A{lat}%2C%22srid%22%3A4326%7D%7D%5D%7D"
            )
        return "https://mapy.geoportal.gov.pl/"

    async def get_parcel_by_xy(
        self,
        client: httpx.AsyncClient,
        lat: float,
        lon: float,
    ) -> dict[str, str] | None:
        """Queries ULDK for a parcel containing given WGS84 coordinates."""
        cache_key = f"xy:{lat:.6f},{lon:.6f}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{self.ULDK_BASE}?request=GetParcelByXY&xy={lon:.6f},{lat:.6f},4326&result=id,teryt,commune,county,voivodship"
        try:
            resp = await client.get(url, headers=self.headers, timeout=self.timeout)
            if resp.status_code == 200:
                lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
                if len(lines) >= 2 and lines[0] == "0":
                    parts = lines[1].split("|")
                    parcel_id = parts[0].strip()
                    res = {
                        "parcel_id": parcel_id,
                        "commune": parts[2].strip() if len(parts) > 2 else "",
                        "county": parts[3].strip() if len(parts) > 3 else "",
                    }
                    self._cache[cache_key] = res
                    return res
        except Exception as e:
            logger.debug(f"[Geoportal] ULDK GetParcelByXY query failed for ({lat}, {lon}): {e}")

        return None

    async def get_parcel_geometry_and_area(
        self,
        client: httpx.AsyncClient,
        parcel_id: str,
    ) -> tuple[float | None, tuple[float, float] | None]:
        """
        Retrieves parcel geometry in EPSG:2180.
        Returns: (area_m2, (centroid_x, centroid_y)).
        """
        cache_key = f"geom:{parcel_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{self.ULDK_BASE}?request=GetParcelById&id={parcel_id}&result=geom_wkt&srid=2180"
        try:
            resp = await client.get(url, headers=self.headers, timeout=self.timeout)
            if resp.status_code == 200 and ("POLYGON" in resp.text):
                m = re.search(r"\(\s*\(+([0-9\.\s,-]+?)\)", resp.text)
                if m:
                    raw_coords = m.group(1).strip()
                    pts = []
                    for pair in raw_coords.split(","):
                        pair = pair.strip()
                        if pair:
                            parts = pair.split()
                            if len(parts) >= 2:
                                pts.append((float(parts[0]), float(parts[1])))
                    n = len(pts)
                    if n >= 3:
                        area = 0.5 * abs(
                            sum(pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1] for i in range(n - 1))
                        )
                        cx = sum(p[0] for p in pts) / n
                        cy = sum(p[1] for p in pts) / n
                        res = (round(area, 1), (cx, cy))
                        self._cache[cache_key] = res
                        return res
        except Exception as e:
            logger.debug(f"[Geoportal] ULDK GetParcelById failed for {parcel_id}: {e}")

        return (None, None)

    async def get_parcel_contours_kieg(
        self,
        client: httpx.AsyncClient,
        cx: float,
        cy: float,
    ) -> str:
        """Queries KIEG WMS GetFeatureInfo to extract soil/use contours (e.g. 'RIIIb,Ba')."""
        cache_key = f"kieg:{round(cx, 1)},{round(cy, 1)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        query_url = (
            f"{self.KIEG_WMS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo&"
            f"BBOX={cy - 5:.1f},{cx - 5:.1f},{cy + 5:.1f},{cx + 5:.1f}&CRS=EPSG:2180&"
            f"WIDTH=10&HEIGHT=10&LAYERS=dzialki&QUERY_LAYERS=dzialki&I=5&J=5&INFO_FORMAT=text/html"
        )
        try:
            resp = await client.get(query_url, headers=self.headers, timeout=self.timeout)
            if resp.status_code == 200:
                m = re.search(r"Oznaczenie konturu</td><td>(.*?)</td>", resp.text)
                if m:
                    contour = m.group(1).strip()
                    self._cache[cache_key] = contour
                    return contour
        except Exception as e:
            logger.debug(f"[Geoportal] KIEG GetFeatureInfo failed: {e}")

        return ""

    async def get_mpzp_info(
        self,
        client: httpx.AsyncClient,
        cx: float,
        cy: float,
    ) -> dict[str, str | None]:
        """Queries Krajowa Integracja MPZP WMS GetFeatureInfo (EPSG:2180)."""
        cache_key = f"mpzp:{round(cx, 1)},{round(cy, 1)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        query_url = (
            f"{self.KIMPZP_WMS}?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetFeatureInfo&"
            f"BBOX={cy - 5:.1f},{cx - 5:.1f},{cy + 5:.1f},{cx + 5:.1f}&CRS=EPSG:2180&"
            f"WIDTH=10&HEIGHT=10&LAYERS=plany_granice,wektor-str&QUERY_LAYERS=plany_granice,wektor-str&I=5&J=5&INFO_FORMAT=text/html"
        )
        try:
            resp = await client.get(query_url, headers=self.headers, timeout=self.timeout, follow_redirects=True)
            if resp.status_code == 200:
                text = resp.text
                symb_m = re.search(r"<FUN_SYMB>(.*?)</FUN_SYMB>", text, re.IGNORECASE)
                nazwa_m = re.search(r"<FUN_NAZWA>(.*?)</FUN_NAZWA>", text, re.IGNORECASE)
                plan_m = re.search(r"<NAZWA_PLAN>(.*?)</NAZWA_PLAN>", text, re.IGNORECASE)

                symbol = symb_m.group(1).strip() if symb_m else None
                fun_nazwa = nazwa_m.group(1).strip() if nazwa_m else None
                plan_name = plan_m.group(1).strip() if plan_m else None

                if symbol or fun_nazwa:
                    zone_desc = f"{symbol}: {fun_nazwa}" if (symbol and fun_nazwa) else (symbol or fun_nazwa)
                    mpzp_res: dict[str, str | None] = {
                        "status": "OBOWIĄZUJĄCY",
                        "zone": zone_desc,
                        "symbol": symbol,
                        "plan_name": plan_name,
                    }
                    self._cache[cache_key] = mpzp_res
                    return mpzp_res

                if "brak wyniku" in text.lower() or "<ROW" not in text:
                    mpzp_res = {
                        "status": "BRAK_PLANU_LUB_CYFRYZACJI",
                        "zone": "Brak MPZP w rejestrze cyfrowym (wymagane WZ)",
                        "symbol": None,
                        "plan_name": None,
                    }
                    self._cache[cache_key] = mpzp_res
                    return mpzp_res
        except Exception as e:
            logger.debug(f"[Geoportal] MPZP GetFeatureInfo failed: {e}")

        default_mpzp: dict[str, str | None] = {"status": "NIEZNANY", "zone": None, "symbol": None, "plan_name": None}
        self._cache[cache_key] = default_mpzp
        return default_mpzp

    async def get_flood_risk_isok(
        self,
        client: httpx.AsyncClient,
        cx: float,
        cy: float,
    ) -> dict[str, str | None]:
        """Queries Wody Polskie INSPIRE ISOK Flood WMS GetFeatureInfo (EPSG:2180)."""
        cache_key = f"flood:{round(cx, 1)},{round(cy, 1)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params = {
            "SERVICE": "WMS",
            "VERSION": "1.3.0",
            "REQUEST": "GetFeatureInfo",
            "BBOX": f"{cy - 10:.1f},{cx - 10:.1f},{cy + 10:.1f},{cx + 10:.1f}",
            "CRS": "EPSG:2180",
            "WIDTH": "10",
            "HEIGHT": "10",
            "LAYERS": "NZ.RiskZone,NZ.Fluvial",
            "QUERY_LAYERS": "NZ.RiskZone,NZ.Fluvial",
            "I": "5",
            "J": "5",
            "INFO_FORMAT": "application/json",
        }
        try:
            resp = await client.get(
                self.ISOK_FLOOD_WMS,
                params=params,
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
            if resp.status_code == 200:
                data = resp.json()
                features = data.get("features", [])
                if features:
                    risk_levels = []
                    for f in features:
                        props = f.get("properties") or {}
                        val = props.get("lor_qualitativevalue")
                        if val:
                            risk_levels.append(str(val))
                    level_str = ", ".join(sorted(set(risk_levels))) if risk_levels else "strefa zalewowa"
                    flood_res: dict[str, str | None] = {
                        "flood_zone": "ZAGROŻENIE_POWODZIOWE",
                        "risk_level": level_str,
                        "description": f"Działka w strefie zagrożenia powodziowego ({level_str})",
                    }
                    self._cache[cache_key] = flood_res
                    return flood_res

                flood_res = {
                    "flood_zone": "BRAK",
                    "risk_level": None,
                    "description": "Brak bezpośredniego zagrożenia powodziowego (poza strefą ISOK)",
                }
                self._cache[cache_key] = flood_res
                return flood_res
        except Exception as e:
            logger.debug(f"[Geoportal] ISOK Flood GetFeatureInfo failed: {e}")

        default_flood: dict[str, str | None] = {"flood_zone": "NIEZNANY", "risk_level": None, "description": None}
        self._cache[cache_key] = default_flood
        return default_flood

    async def audit_location(
        self,
        lat: float,
        lon: float,
        radius_meters: int = 120,
    ) -> dict[str, Any]:
        """
        Comprehensive spatial audit:
        1. Identifies the main parcel and computes exact cadastral area.
        2. Queries MPZP zoning and digital plan status (KI MPZP).
        3. Queries flood risk zones (ISOK Hydroportal).
        4. Scans surrounding parcels within radius_meters in 8 cardinal directions.
        5. Checks official EGiB contours for industrial (Ba), commercial (Bi), or railway (Tk) risks.
        6. Generates direct Geoportal link.
        """
        result: dict[str, Any] = {
            "main_parcel_id": None,
            "main_parcel_number": None,
            "cadastral_area": None,
            "geoportal_url": self.generate_geoportal_url(lat=lat, lon=lon),
            "gunb_url": self.generate_gunb_url(),
            "gesut_url": self.generate_geoportal_url(lat=lat, lon=lon),
            "surrounding_risks": [],
            "surrounding_parcels_count": 0,
            "mpzp_zone": None,
            "mpzp_status": None,
            "mpzp_plan_name": None,
            "flood_risk_zone": None,
            "flood_risk_level": None,
            "flood_risk_desc": None,
        }

        async with httpx.AsyncClient(timeout=self.timeout, headers=self.headers) as client:
            # Step 1: Main parcel
            main_info = await self.get_parcel_by_xy(client, lat, lon)
            if not main_info:
                return result

            main_pid = main_info["parcel_id"]
            result["main_parcel_id"] = main_pid
            result["main_parcel_number"] = main_pid.split(".")[-1]
            result["geoportal_url"] = self.generate_geoportal_url(parcel_id=main_pid)
            result["gunb_url"] = self.generate_gunb_url(parcel_id=main_pid)
            result["gesut_url"] = self.generate_geoportal_url(parcel_id=main_pid)

            main_area, main_centroid = await self.get_parcel_geometry_and_area(client, main_pid)
            result["cadastral_area"] = main_area

            # Step 2: MPZP & Flood risk queries (concurrent with surrounding search)
            mpzp_task = self.get_mpzp_info(client, main_centroid[0], main_centroid[1]) if main_centroid else None
            flood_task = self.get_flood_risk_isok(client, main_centroid[0], main_centroid[1]) if main_centroid else None

            # Step 3: Surrounding search points (8 directions)
            d_lat = radius_meters / 111139.0
            d_lon = radius_meters / (111139.0 * math.cos(math.radians(lat)))
            angles = [0, 45, 90, 135, 180, 225, 270, 315]
            surround_coords = [
                (lon + d_lon * math.cos(math.radians(a)), lat + d_lat * math.sin(math.radians(a))) for a in angles
            ]

            surround_tasks = [self.get_parcel_by_xy(client, pt_lat, pt_lon) for pt_lon, pt_lat in surround_coords]
            surround_infos = await asyncio.gather(*surround_tasks, return_exceptions=True)

            surround_pids: set[str] = set()
            for r in surround_infos:
                if isinstance(r, dict) and r.get("parcel_id"):
                    pid = r["parcel_id"]
                    if pid != main_pid:
                        surround_pids.add(pid)

            result["surrounding_parcels_count"] = len(surround_pids)

            # Await MPZP & Flood tasks
            if mpzp_task:
                mpzp_info = await mpzp_task
                result["mpzp_zone"] = mpzp_info.get("zone")
                result["mpzp_status"] = mpzp_info.get("status")
                result["mpzp_plan_name"] = mpzp_info.get("plan_name")
            if flood_task:
                flood_info = await flood_task
                result["flood_risk_zone"] = flood_info.get("flood_zone")
                result["flood_risk_level"] = flood_info.get("risk_level")
                result["flood_risk_desc"] = flood_info.get("description")
                if flood_info.get("flood_zone") == "ZAGROŻENIE_POWODZIOWE":
                    result["surrounding_risks"].append(
                        flood_info.get("description") or "Strefa zagrożenia powodziowego"
                    )

            if not surround_pids:
                return result

            # Step 4: Check geometry and contours for surrounding parcels concurrently
            geom_tasks = [self.get_parcel_geometry_and_area(client, pid) for pid in surround_pids]
            geom_results = await asyncio.gather(*geom_tasks, return_exceptions=True)

            kieg_tasks = []
            pid_list = list(surround_pids)
            for i, gr in enumerate(geom_results):
                if isinstance(gr, tuple) and gr[1] is not None:
                    cx, cy = gr[1]
                    kieg_tasks.append((pid_list[i], self.get_parcel_contours_kieg(client, cx, cy)))

            if kieg_tasks:
                kieg_results = await asyncio.gather(*[t[1] for t in kieg_tasks], return_exceptions=True)
                for j, contour in enumerate(kieg_results):
                    pid = kieg_tasks[j][0]
                    if isinstance(contour, str) and contour:
                        short_nr = pid.split(".")[-1]
                        contour_upper = contour.upper()
                        if "BA" in contour_upper:
                            result["surrounding_risks"].append(
                                f"Działka {short_nr} ma przeznaczenie przemysłowe (Ba): {contour}"
                            )
                        elif "BI" in contour_upper:
                            result["surrounding_risks"].append(
                                f"Działka {short_nr} ma użytek komercyjny/składowy (Bi): {contour}"
                            )
                        elif "TK" in contour_upper:
                            result["surrounding_risks"].append(f"Działka {short_nr} to tereny kolejowe (Tk): {contour}")

        return result


geoportal_service = GeoportalService()
