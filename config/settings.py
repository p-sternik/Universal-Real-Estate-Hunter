from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///listings.db"

    # Notifiers
    DISCORD_WEBHOOK_URL: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None

    # Scheduler
    CHECK_INTERVAL_MINUTES: int = 20

    # Stage I: Numerical thresholds
    MAX_PRICE: float = 1_300_000.0
    MIN_AREA_HOME: float = 90.0
    MAX_AREA_HOME: float = 145.0
    MIN_AREA_PLOT: float = 250.0  # If < 250 and middle segment -> reject; if None -> analyze desc

    # Stage I: Blacklist keywords (case-insensitive substring check)
    BLACKLIST_KEYWORDS: List[str] = Field(
        default_factory=lambda: [
            "matysówka",
            "matysowka",
            "matysowska",
            "tyczyn",
            "chmielnik",
            "biała",
            "biala",
            "zwięczyca",
            "zwieczyca",
            "kielanówka",
            "kielanowka",
            "górna słocina",
            "gorna slocina",
            "św. rocha",
            "sw. rocha",
            "sw rocha",
            "św rocha",
            "skarpie",
            "na skarpie",
            "teren osuwiskowy",
            "osuwisko",
        ]
    )

    # Stage I: Whitelist configurations
    # Whitelist is prioritized. Offers matching whitelist receive high priority / bonus tag.
    WHITELIST_AREAS: List[dict] = Field(
        default_factory=lambda: [
            {
                "name": "Słocina Dolna",
                "keywords": ["paderewskiego", "witolda", "powstańców wielkopolskich", "powstancow wielkopolskich"],
                "required_parent": "słocina",
            },
            {
                "name": "Zalesie Dolne/Centralne",
                "keywords": ["łukasiewicza", "lukasiewicza", "dunikowskiego", "spacerowa"],
                "required_parent": "zalesie",
            },
            {
                "name": "Staromieście",
                "keywords": ["staromieście ogrody", "staromiescie ogrody", "borowa", "lubelska", "lubelskiej"],
                "required_parent": "staromieście",
            },
            {
                "name": "Północ/Wschód (Trzebownisko)",
                "keywords": ["trzebownisko"],
                "required_parent": None,
            },
            {
                "name": "Północ/Wschód (Nowa Wieś)",
                "keywords": ["nowa wieś", "nowa wies"],
                "required_parent": None,
            },
            {
                "name": "Północ/Wschód (Terliczka)",
                "keywords": ["terliczka"],
                "required_parent": None,
            },
            {
                "name": "Północ/Wschód (Krasne wzdłuż DK94)",
                "keywords": ["krasne", "dk94", "krasnego"],
                "required_parent": None,
            },
            {
                "name": "Północ/Wschód (Głogów Młp. Niwa / Rogoźnica / PKA)",
                "keywords": ["niwa", "rogoźnica", "rogoznica", "stacji pka", "pka", "głogów", "glogow"],
                "required_parent": None,
            },
        ]
    )

    # Scraping Configuration
    REQUEST_TIMEOUT_SECONDS: int = 25
    MAX_RETRIES: int = 3
    FETCH_DETAILS: bool = True
    CONCURRENT_REQUESTS: int = 3
    DETAIL_REFRESH_HOURS: int = 24
    PROXY_URL: Optional[str] = None
    USER_AGENT: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    )

    # LLM Settings (Optional)
    USE_LLM_ANALYSIS: bool = False
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_MODEL: str = "gpt-4o-mini"
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "llama3.1:8b"


settings = Settings()
