import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from loguru import logger
from pydantic import BaseModel, Field

from config import settings

CONFIG_FILE_PATH = Path(os.getenv("SEARCH_CONFIG_PATH", "search_config.json"))

POLISH_CHAR_MAP = {
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
    "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "a", "Ć": "c", "Ę": "e", "Ł": "l", "Ń": "n",
    "Ó": "o", "Ś": "s", "Ź": "z", "Ż": "z",
}

# Major Polish cities mapping for Otodom canonical paths
OTODOM_CITY_PATHS = {
    "rzeszow": "podkarpackie/rzeszow/rzeszow/rzeszow",
    "krakow": "malopolskie/krakow/krakow/krakow",
    "warszawa": "mazowieckie/warszawa/warszawa/warszawa",
    "wroclaw": "dolnoslaskie/wroclaw/wroclaw/wroclaw",
    "lublin": "lubelskie/lublin/lublin/lublin",
    "poznan": "wielkopolskie/poznan/poznan/poznan",
    "gdansk": "pomorskie/gdansk/gdansk/gdansk",
    "katowice": "slaskie/katowice/katowice/katowice",
    "lodz": "lodzkie/lodz/lodz/lodz",
    "szczecin": "zachodniopomorskie/szczecin/szczecin/szczecin",
    "bialystok": "podlaskie/bialystok/bialystok/bialystok",
    "bydgoszcz": "kujawsko-pomorskie/bydgoszcz/bydgoszcz/bydgoszcz",
    "torun": "kujawsko-pomorskie/torun/torun/torun",
    "kielce": "swietokrzyskie/kielce/kielce/kielce",
    "lancut": "podkarpackie/lancucki/lancut",
    "krosno": "podkarpackie/krosno/krosno/krosno",
    "przemysl": "podkarpackie/przemysl/przemysl/przemysl",
    "tarnow": "malopolskie/tarnow/tarnow/tarnow",
    "mielec": "podkarpackie/mielecki/mielec",
}

# Centroids for major Polish cities to position Leaflet map
CITY_CENTROIDS = {
    "rzeszow": (50.0375, 22.0047),
    "krakow": (50.0647, 19.9450),
    "warszawa": (52.2297, 21.0122),
    "wroclaw": (51.1079, 17.0385),
    "lublin": (51.2465, 22.5684),
    "poznan": (52.4064, 16.9252),
    "gdansk": (54.3520, 18.6466),
    "katowice": (50.2649, 19.0238),
    "lodz": (51.7592, 19.4560),
    "szczecin": (53.4285, 14.5528),
    "bialystok": (53.1325, 23.1688),
    "kielce": (50.8661, 20.6286),
    "bydgoszcz": (53.1235, 18.0084),
    "torun": (53.0138, 18.5984),
    "lancut": (50.0690, 22.2310),
    "krosno": (49.6887, 21.7706),
    "przemysl": (49.7839, 22.7678),
    "tarnow": (50.0121, 20.9858),
    "mielec": (50.2872, 21.4239),
}


def slugify_city(text: str) -> str:
    """Converts a Polish city name into a clean URL slug (e.g. 'Głogów Małopolski' -> 'glogow-malopolski')."""
    if not text:
        return "rzeszow"
    result = []
    for ch in text.strip():
        result.append(POLISH_CHAR_MAP.get(ch, ch))
    slug = "".join(result).lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    return slug or "rzeszow"


class ScraperConfig(BaseModel):
    enabled: bool = True
    max_pages: int = 2
    delay_seconds: float = 1.0


class ScrapersSettings(BaseModel):
    otodom: ScraperConfig = Field(default_factory=lambda: ScraperConfig(enabled=True, max_pages=3, delay_seconds=1.0))
    olx: ScraperConfig = Field(default_factory=lambda: ScraperConfig(enabled=True, max_pages=2, delay_seconds=1.0))
    nieruchomosci_online: ScraperConfig = Field(default_factory=lambda: ScraperConfig(enabled=True, max_pages=2, delay_seconds=1.5))
    morizon: ScraperConfig = Field(default_factory=lambda: ScraperConfig(enabled=True, max_pages=2, delay_seconds=1.0))


class SchedulerSettings(BaseModel):
    interval_minutes: int = 20
    night_mode: bool = True
    night_interval_minutes: int = 60
    quiet_hours_start: str = "22:00"
    quiet_hours_end: str = "07:00"

    def get_current_interval_minutes(self) -> int:
        """Returns effective interval considering current time and quiet hours."""
        if not self.night_mode:
            return max(1, self.interval_minutes)
        try:
            now = datetime.now().time()
            start = datetime.strptime(self.quiet_hours_start, "%H:%M").time()
            end = datetime.strptime(self.quiet_hours_end, "%H:%M").time()
            if start <= end:
                is_night = start <= now <= end
            else:
                is_night = now >= start or now <= end
            return max(1, self.night_interval_minutes if is_night else self.interval_minutes)
        except Exception:
            return max(1, self.interval_minutes)


class SearchProfile(BaseModel):
    id: str = "default"
    name: str = "Domy Rzeszów"
    enabled: bool = True
    category: str = "dom"  # "dom", "mieszkanie", "dzialka"
    city: str = "Rzeszów"
    distance_radius: Optional[int] = 15
    min_price: Optional[float] = 0.0
    max_price: Optional[float] = 1_300_000.0
    min_price_per_m2: Optional[float] = None
    max_price_per_m2: Optional[float] = None
    min_area_home: Optional[float] = 90.0
    max_area_home: Optional[float] = 145.0
    min_area_plot: Optional[float] = 250.0
    max_area_plot: Optional[float] = None
    min_rooms: Optional[int] = None
    max_rooms: Optional[int] = None
    min_floor: Optional[int] = None
    max_floor: Optional[int] = None
    min_year_built: Optional[int] = None
    max_year_built: Optional[int] = None
    owner_type: str = "all"  # "all", "private", "agency", "developer"
    market_type: str = "all"  # "all", "pierwotny", "wtórny"
    allowed_finish_conditions: List[str] = Field(default_factory=lambda: ["all"])
    allow_visualisations: bool = True
    reject_septic_tank: bool = False
    allowed_heating_types: List[str] = Field(default_factory=lambda: ["all"])
    building_types: List[str] = Field(
        default_factory=lambda: ["szeregowiec", "bliźniak", "wolnostojący", "inny"]
    )
    whitelist_areas: List[dict] = Field(default_factory=list)
    blacklist_keywords: List[str] = Field(default_factory=list)
    enabled_portals: Optional[List[str]] = None
    discord_webhook_url: Optional[str] = None

    @property
    def city_slug(self) -> str:
        return slugify_city(self.city)

    def get_otodom_url(self) -> str:
        slug = self.city_slug
        path = OTODOM_CITY_PATHS.get(slug, slug)
        cat = {"dom": "dom", "mieszkanie": "mieszkanie", "dzialka": "dzialka"}.get(self.category, "dom")
        base = f"https://www.otodom.pl/pl/wyniki/sprzedaz/{cat}/{path}"

        radius = self.distance_radius if self.distance_radius is not None else 15
        params = [f"distanceRadius={radius}", "limit=36"]
        if self.min_price is not None and self.min_price > 0:
            params.append(f"priceMin={int(self.min_price)}")
        if self.max_price is not None and self.max_price > 0:
            params.append(f"priceMax={int(self.max_price)}")

        if self.category == "dzialka":
            if self.min_area_plot is not None and self.min_area_plot > 0:
                params.append(f"areaMin={int(self.min_area_plot)}")
            if self.max_area_plot is not None and self.max_area_plot > 0:
                params.append(f"areaMax={int(self.max_area_plot)}")
        else:
            if self.min_area_home is not None and self.min_area_home > 0:
                params.append(f"areaMin={int(self.min_area_home)}")
            if self.max_area_home is not None and self.max_area_home > 0:
                params.append(f"areaMax={int(self.max_area_home)}")
            if self.category == "dom":
                if self.min_area_plot is not None and self.min_area_plot > 0:
                    params.append(f"terrainAreaMin={int(self.min_area_plot)}")
                if self.max_area_plot is not None and self.max_area_plot > 0:
                    params.append(f"terrainAreaMax={int(self.max_area_plot)}")

        if self.market_type == "pierwotny":
            params.append("market=PRIMARY")
        elif self.market_type == "wtórny":
            params.append("market=SECONDARY")
        if self.owner_type == "private":
            params.append("ownerTypeSingleSelect=PRIVATE")
        elif self.owner_type in ("agency", "developer"):
            params.append(f"ownerTypeSingleSelect={self.owner_type.upper()}")

        if self.min_rooms or self.max_rooms:
            room_names = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX_OR_MORE"}
            min_r = self.min_rooms or 1
            max_r = self.max_rooms or 6
            selected = [room_names[r] for r in range(min_r, min(max_r, 6) + 1) if r in room_names]
            if selected:
                params.append(f"roomsNumber=%5B{','.join(selected)}%5D")

        return f"{base}?{'&'.join(params)}"

    def get_olx_url(self) -> str:
        slug = self.city_slug
        cat = {"dom": "domy", "mieszkanie": "mieszkania", "dzialka": "dzialki"}.get(self.category, "domy")
        base = f"https://www.olx.pl/nieruchomosci/{cat}/sprzedaz/{slug}/"

        radius = self.distance_radius if self.distance_radius is not None else 15
        params = [f"search%5Bdist%5D={radius}"]
        if self.min_price is not None and self.min_price > 0:
            params.append(f"search%5Bfilter_float_price%3Afrom%5D={int(self.min_price)}")
        if self.max_price is not None and self.max_price > 0:
            params.append(f"search%5Bfilter_float_price%3Ato%5D={int(self.max_price)}")

        if self.category == "dzialka":
            if self.min_area_plot is not None and self.min_area_plot > 0:
                params.append(f"search%5Bfilter_float_m%3Afrom%5D={int(self.min_area_plot)}")
            if self.max_area_plot is not None and self.max_area_plot > 0:
                params.append(f"search%5Bfilter_float_m%3Ato%5D={int(self.max_area_plot)}")
        else:
            if self.min_area_home is not None and self.min_area_home > 0:
                params.append(f"search%5Bfilter_float_m%3Afrom%5D={int(self.min_area_home)}")
            if self.max_area_home is not None and self.max_area_home > 0:
                params.append(f"search%5Bfilter_float_m%3Ato%5D={int(self.max_area_home)}")

        if self.market_type == "pierwotny":
            params.append("search%5Bfilter_enum_market%5D%5B0%5D=primary")
        elif self.market_type == "wtórny":
            params.append("search%5Bfilter_enum_market%5D%5B0%5D=secondary")
        if self.owner_type == "private":
            params.append("search%5Bprivate_business%5D=private")
        elif self.owner_type in ("agency", "developer"):
            params.append("search%5Bprivate_business%5D=business")

        if self.min_rooms or self.max_rooms:
            olx_rooms = {1: "one", 2: "two", 3: "three", 4: "four_more"}
            min_r = self.min_rooms or 1
            max_r = self.max_rooms or 4
            idx = 0
            for r in range(min_r, min(max_r, 4) + 1):
                if r in olx_rooms:
                    params.append(f"search%5Bfilter_enum_rooms%5D%5B{idx}%5D={olx_rooms[r]}")
                    idx += 1

        return f"{base}?{'&'.join(params)}"

    def get_nieruchomosci_online_url(self) -> str:
        slug = self.city_slug
        cat = {"dom": "domy", "mieszkanie": "mieszkania", "dzialka": "dzialki"}.get(self.category, "domy")
        base = f"https://{slug}.nieruchomosci-online.pl/{cat},sprzedaz/"

        params = []
        if self.min_price is not None and self.min_price > 0:
            params.append(f"cena_od={int(self.min_price)}")
        if self.max_price is not None and self.max_price > 0:
            params.append(f"cena_do={int(self.max_price)}")

        if self.category == "dzialka":
            if self.min_area_plot is not None and self.min_area_plot > 0:
                params.append(f"powierzchnia_od={int(self.min_area_plot)}")
            if self.max_area_plot is not None and self.max_area_plot > 0:
                params.append(f"powierzchnia_do={int(self.max_area_plot)}")
        else:
            if self.min_area_home is not None and self.min_area_home > 0:
                params.append(f"powierzchnia_od={int(self.min_area_home)}")
            if self.max_area_home is not None and self.max_area_home > 0:
                params.append(f"powierzchnia_do={int(self.max_area_home)}")

        if self.min_rooms and self.min_rooms > 0:
            params.append(f"liczba-pokoi_od={int(self.min_rooms)}")
        if self.max_rooms and self.max_rooms > 0:
            params.append(f"liczba-pokoi_do={int(self.max_rooms)}")

        if params:
            return f"{base}?{'&'.join(params)}"
        return base

    def get_morizon_url(self) -> str:
        slug = self.city_slug
        cat = {"dom": "domy", "mieszkanie": "mieszkania", "dzialka": "dzialki"}.get(self.category, "domy")
        base = f"https://www.morizon.pl/{cat}/{slug}/"

        params = []
        if self.min_price is not None and self.min_price > 0:
            params.append(f"ps%5Bprice_from%5D={int(self.min_price)}")
        if self.max_price is not None and self.max_price > 0:
            params.append(f"ps%5Bprice_to%5D={int(self.max_price)}")

        if self.category == "dzialka":
            if self.min_area_plot is not None and self.min_area_plot > 0:
                params.append(f"ps%5Bliving_area_from%5D={int(self.min_area_plot)}")
            if self.max_area_plot is not None and self.max_area_plot > 0:
                params.append(f"ps%5Bliving_area_to%5D={int(self.max_area_plot)}")
        else:
            if self.min_area_home is not None and self.min_area_home > 0:
                params.append(f"ps%5Bliving_area_from%5D={int(self.min_area_home)}")
            if self.max_area_home is not None and self.max_area_home > 0:
                params.append(f"ps%5Bliving_area_to%5D={int(self.max_area_home)}")

        if params:
            return f"{base}?{'&'.join(params)}"
        return base

    def get_city_center(self) -> tuple[float, float]:
        slug = self.city_slug
        return CITY_CENTROIDS.get(slug, (50.0375, 22.0047))


class SearchConfig(BaseModel):
    """
    Root configuration managing search profiles and scrapers settings.
    Maintains full backward compatibility with legacy single-profile callers.
    """
    profiles: List[SearchProfile] = Field(default_factory=list)
    scrapers: ScrapersSettings = Field(default_factory=ScrapersSettings)
    scheduler: SchedulerSettings = Field(default_factory=SchedulerSettings)

    def __getattr__(self, item: str) -> Any:
        # Transparent proxy to active/first profile for backward compatibility
        if item not in ("profiles", "scrapers", "scheduler") and hasattr(self, "profiles") and self.profiles:
            active = self.get_active_profile()
            if hasattr(active, item):
                return getattr(active, item)
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{item}'")

    def get_active_profile(self) -> SearchProfile:
        for p in self.profiles:
            if p.enabled:
                return p
        return self.profiles[0] if self.profiles else SearchProfile()

    def get_active_profiles(self, target_name: Optional[str] = None) -> List[SearchProfile]:
        if target_name:
            target_clean = target_name.strip().lower()
            matched = [p for p in self.profiles if p.id.lower() == target_clean or p.name.lower() == target_clean]
            if matched:
                return matched
        return [p for p in self.profiles if p.enabled]


class ConfigManager:
    """Manages active search criteria, location, and filtration rules."""

    def __init__(self, config_path: Union[Path, str] = CONFIG_FILE_PATH):
        self.config_path = Path(config_path) if isinstance(config_path, str) else config_path
        self._config: Optional[SearchConfig] = None
        self.load_config()

    def _get_default_profile(self) -> SearchProfile:
        return SearchProfile(
            id="rzeszow_domy",
            name="Domy Rzeszów",
            enabled=True,
            category="dom",
            city="Rzeszów",
            distance_radius=15,
            min_price=0.0,
            max_price=settings.MAX_PRICE,
            min_area_home=settings.MIN_AREA_HOME,
            max_area_home=settings.MAX_AREA_HOME,
            min_area_plot=settings.MIN_AREA_PLOT,
            market_type="all",
            allowed_finish_conditions=["all"],
            allow_visualisations=True,
            building_types=["szeregowiec", "bliźniak", "wolnostojący", "inny"],
            whitelist_areas=settings.WHITELIST_AREAS,
            blacklist_keywords=settings.BLACKLIST_KEYWORDS,
        )

    def _get_default_config(self) -> SearchConfig:
        return SearchConfig(
            profiles=[self._get_default_profile()],
            scrapers=ScrapersSettings(),
            scheduler=SchedulerSettings(),
        )

    @classmethod
    def _migrate_legacy_dict(cls, data: Dict[str, Any]) -> SearchConfig:
        """Migrate legacy flat dictionary into modern profiles structure."""
        if "profiles" in data and isinstance(data["profiles"], list) and len(data["profiles"]) > 0:
            return SearchConfig(**data)

        logger.info("[ConfigManager] Wykryto starszy format konfiguracji, migruję do formatu z profilami...")
        # Extract profile-specific fields from flat structure
        profile_fields = {k: v for k, v in data.items() if k in SearchProfile.model_fields}
        if "name" not in profile_fields:
            city_name = data.get("city", "Rzeszów")
            profile_fields["name"] = f"Domy {city_name}"
        if "id" not in profile_fields:
            profile_fields["id"] = "default"
        if "category" not in profile_fields:
            profile_fields["category"] = "dom"
        if "enabled" not in profile_fields:
            profile_fields["enabled"] = True

        profile = SearchProfile(**profile_fields)
        scrapers = ScrapersSettings()
        if "scrapers" in data and isinstance(data["scrapers"], dict):
            try:
                scrapers = ScrapersSettings(**data["scrapers"])
            except Exception:
                pass

        return SearchConfig(profiles=[profile], scrapers=scrapers)

    def load_config(self) -> SearchConfig:
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self._config = self._migrate_legacy_dict(data)
                    logger.info(f"[ConfigManager] Załadowano konfigurację ({len(self._config.profiles)} profili).")
                    # Save back migrated format
                    self.save_config()
                    return self._config
            except Exception as e:
                logger.warning(f"[ConfigManager] Błąd odczytu {self.config_path}, przywracam domyślne: {e}")

        # Check fallback root config (e.g. inside Docker image when volume config_path doesn't exist yet)
        fallback = Path("search_config.json")
        if fallback.exists() and fallback.resolve() != self.config_path.resolve():
            try:
                with open(fallback, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = self._migrate_legacy_dict(data)
                logger.info(f"[ConfigManager] Zainicjalizowano konfigurację z szablonu {fallback} do {self.config_path}")
                self.save_config()
                return self._config
            except Exception as e:
                logger.warning(f"[ConfigManager] Błąd odczytu fallback {fallback}: {e}")

        self._config = self._get_default_config()
        self.save_config()
        return self._config

    def save_config(self) -> None:
        if self._config is None:
            self._config = self._get_default_config()
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(self._config.model_dump(), f, ensure_ascii=False, indent=2)
            logger.info(f"[ConfigManager] Zapisano konfigurację do {self.config_path}")
        except Exception as e:
            logger.error(f"[ConfigManager] Nie udało się zapisać konfiguracji: {e}")

    def get_config(self) -> SearchConfig:
        if self._config is None:
            self.load_config()
        return self._config

    def update_config(self, updates: Dict[str, Any]) -> SearchConfig:
        """Update top-level configuration (e.g. scrapers, scheduler or full dictionary)."""
        current_dict = self.get_config().model_dump()
        if "profiles" in updates:
            current_dict["profiles"] = updates["profiles"]
        if "scrapers" in updates:
            current_dict["scrapers"] = updates["scrapers"]
        if "scheduler" in updates:
            current_dict["scheduler"] = updates["scheduler"]

        # Support updating first/active profile directly if flat keys were provided
        flat_keys = {k: v for k, v in updates.items() if k not in ("profiles", "scrapers", "scheduler")}
        if flat_keys and current_dict.get("profiles"):
            current_dict["profiles"][0].update(flat_keys)

        self._config = SearchConfig(**current_dict)
        self.save_config()
        return self._config

    def update_scheduler(self, scheduler_data: Dict[str, Any]) -> SchedulerSettings:
        cfg = self.get_config()
        current_dict = cfg.scheduler.model_dump()
        current_dict.update(scheduler_data)
        cfg.scheduler = SchedulerSettings(**current_dict)
        self.save_config()
        return cfg.scheduler

    def get_profile(self, profile_id_or_name: Optional[str] = None) -> SearchProfile:
        cfg = self.get_config()
        if profile_id_or_name:
            target = profile_id_or_name.strip().lower()
            for p in cfg.profiles:
                if p.id.lower() == target or p.name.lower() == target:
                    return p
        return cfg.get_active_profile()

    def add_or_update_profile(self, profile_data: Dict[str, Any]) -> SearchProfile:
        cfg = self.get_config()
        prof_id = profile_data.get("id") or profile_data.get("name", "profile").lower().replace(" ", "_")
        profile_data["id"] = prof_id

        existing_idx = None
        for i, p in enumerate(cfg.profiles):
            if p.id == prof_id:
                existing_idx = i
                break

        new_profile = SearchProfile(**profile_data)
        if existing_idx is not None:
            cfg.profiles[existing_idx] = new_profile
        else:
            cfg.profiles.append(new_profile)

        self.save_config()
        return new_profile

    def delete_profile(self, profile_id: str) -> bool:
        cfg = self.get_config()
        initial_len = len(cfg.profiles)
        cfg.profiles = [p for p in cfg.profiles if p.id != profile_id]
        if len(cfg.profiles) < initial_len:
            if not cfg.profiles:
                cfg.profiles.append(self._get_default_profile())
            self.save_config()
            return True
        return False


# Singleton config manager
config_manager = ConfigManager()
