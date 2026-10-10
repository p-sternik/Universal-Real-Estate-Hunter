# Repository Map — Universal Real Estate Hunter

Combined workspace and component navigation map for Universal Real Estate Hunter.

---

## 1. Investigation Scope & Boundaries

- **Project Root**: `C:\Users\User\WebstormProjects\apartments-scrapper`
- **Application Identity**: `rzeszow-houses-scrapper` (Python 3.11+, uv package manager, FastAPI / aiohttp web service, SQLite/PostgreSQL storage, curl_cffi / Playwright scrapers).
- **Scope**: Single-project workspace combining scraping, qualification, spatial intelligence, web dashboard, and persistence.
- **Coverage Status**:
  - `investigated`: `main.py`, `src/scrapers/`, `src/filters/`, `src/services/`, `src/storage/`, `src/models/`, `src/scheduler/`, `tests/`, `config/`.
  - `excluded`: Local databases (`listings.db`, `data/listings.db`), local secrets (`.env`), temporary caches (`.pytest_tmp/`, `.mypy_cache/`, `.ruff_cache/`).

---

## 2. Directory Structure & Component Roles

```
apartments-scrapper/
├── main.py                     # CLI dispatcher and runtime entrypoint
├── pyproject.toml              # Build manifest, dependency groups, tool configs (ruff, mypy, pytest)
├── search_config.json          # Search profiles, budget limits, city/distance filters, blacklist/whitelist
├── docker-compose.yml          # Container configuration (app + optional PostgreSQL)
├── config/                     # Application settings (pydantic-settings)
│   └── settings.py             # Settings singleton, environment bindings, default whitelists
├── src/
│   ├── models/                 # Domain Pydantic schemas and StrEnums
│   │   ├── enums.py            # Taxonomies: PropertyCategory, FinishCondition, BuildingType, RoadType, etc.
│   │   └── listing.py          # ListingSchema, FilterResult, spatial attribute mappings
│   ├── scrapers/               # Real estate portal scrapers
│   │   ├── base.py             # BaseScraper: curl_cffi TLS impersonation, backoff, User-Agent rotation
│   │   ├── otodom.py           # Otodom parser (JSON embedded state & HTML)
│   │   ├── morizon.py          # Morizon parser
│   │   ├── olx.py              # OLX API / HTML scraper
│   │   └── nieruchomosci_online.py # Nieruchomości-online parser
│   ├── filters/                # 3-Stage filtering and forensic qualification engine
│   │   ├── __init__.py         # QualificationEngine: combines S1, S2, S3, spatial scoring
│   │   ├── stage1_hard_rules.py# Stage 1: Zero-cost fast reject (budget, home/plot area, whitelist/blacklist)
│   │   ├── stage2_semantic.py  # Stage 2: Fast regex parser (road surface, segment subtype, finish, utilities)
│   │   ├── fingerprint.py      # Deduplication: physical fingerprint generator & desc hash
│   │   ├── llm_analyzer.py     # Stage 3: LLM forensic audit via Ollama / OpenAI API
│   │   ├── vision_analyzer.py  # Stage 3: Multimodal Vision AI for photo inspection (renders vs real, finish, defects)
│   │   └── prompts/            # Prompt templates for forensic LLM audit
│   ├── services/               # Background orchestration, spatial services, notifiers, web dashboard
│   │   ├── pipeline.py         # ScraperPipeline: master orchestrator of cycles, enrichment, DB, notifiers
│   │   ├── live_dashboard.py   # aiohttp.web server: REST endpoints & static assets
│   │   ├── config_manager.py   # Multi-profile search configuration manager
│   │   ├── geoportal.py        # GUGiK ULDK, KIEG, MPZP, ISOK flood, SOPO landslides, GESUT integration
│   │   ├── geocoder.py         # Nominatim geocoding with SQLite/Postgres cache
│   │   ├── gunb.py             # GUNB / RWDZ architectural registry client
│   │   ├── air_quality.py      # CAMS & GIOŚ air pollution and winter PM2.5 monitor
│   │   ├── commute.py          # OSRM drive and walking route calculator
│   │   ├── developer_verifier.py # KRS / REGON legal & capital solvency verifier
│   │   ├── market_analyzer.py  # ValuationEngine: market median m2, negotiation leverage, opening offer
│   │   ├── discord_notifier.py # Discord webhook alerts
│   │   ├── telegram_notifier.py# Telegram bot notifications
│   │   ├── progress.py         # Global scraper progress & event broadcast tracker
│   │   ├── scrape_lock.py      # Process concurrency lock to prevent overlapping scrape runs
│   │   └── terminal_view.py    # Rich terminal tables for CLI listing inspections
│   ├── storage/                # Database models and data access layer
│   │   ├── database.py         # Engine factory, safe_commit retry lock, auto-migration to PostgreSQL
│   │   ├── models.py           # SQLAlchemy declarative ORM models: ListingModel, PriceHistoryModel, etc.
│   │   └── repository.py       # ListingRepository CRUD, profile filtering, CRM statuses
│   └── scheduler/              # Scheduled daemon runner
│       └── runner.py           # APScheduler background runner with graceful shutdown
└── tests/                      # Pytest test suite (unit, integration, mock fixtures)
```

---

## 3. Task-Conditioned Routing

| If your task is... | Start at... | Key contracts to preserve | Verify with... |
| :--- | :--- | :--- | :--- |
| **Adding or modifying a portal scraper** | [`src/scrapers/base.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/scrapers/base.py) & target scraper | Yield [`ListingSchema`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/models/listing.py); respect rate-limiting, error handling, and session closing | `uv run pytest tests/test_<portal>.py` |
| **Altering Stage 1 hard filter rules** | [`src/filters/stage1_hard_rules.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/filters/stage1_hard_rules.py) | Whitelist vs Blacklist precedence; budget and area ranges | `uv run pytest tests/test_filters.py` |
| **Adjusting Stage 2 regex or finish detection** | [`src/filters/stage2_semantic.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/filters/stage2_semantic.py) | Living Quarters Principle (`CONTEXT.md` §3); false-friend traps | `uv run pytest tests/test_filters.py` |
| **Refining Stage 3 LLM or Vision AI** | [`src/filters/llm_analyzer.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/filters/llm_analyzer.py) or [`vision_analyzer.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/filters/vision_analyzer.py) | Prompt contract in `src/filters/prompts/`; JSON schema output | `uv run pytest tests/test_llm_config.py tests/test_vision_analyzer.py` |
| **Changing spatial intelligence or Geoportal** | [`src/services/geoportal.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/services/geoportal.py) | Coordinate transforms (EPSG:2180 vs EPSG:4326); caching in `spatial_cache` | `uv run pytest tests/test_geoportal.py` |
| **Updating Database schemas or migrations** | [`src/storage/database.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/storage/database.py) & [`models.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/storage/models.py) | Add entry to `LISTINGS_SCHEMA_MIGRATIONS`; support both SQLite & Postgres | `uv run pytest tests/test_storage.py` |
| **Modifying Web Dashboard or REST APIs** | [`src/services/live_dashboard.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/services/live_dashboard.py) | Keep `/api/listings` lightweight (`_LIST_OMIT_FIELDS`); full detail in `/api/listings/{id}` | `uv run pytest tests/test_dashboard_images_valuation.py tests/test_crm.py` |
| **Modifying Scraper Pipeline orchestration** | [`src/services/pipeline.py`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/services/pipeline.py) | Atomic progress updates; deduplication via physical fingerprint | `uv run pytest tests/test_pipeline.py` |

---

## 4. Key Cross-Cutting Invariants

1. **Ground Truth Hierarchy**: Portal metadata tags are untrusted claims. Listing text and official spatial data override portal tags. All contradictions must be recorded in `discrepancies`.
2. **Living Quarters Principle**: Properties with turnkey living quarters remain `pod_klucz` / `DO_ZAMIESZKANIA` even if external works (terrace, garden, paving) remain unfinished.
3. **Database Concurrency**: In SQLite mode, all write commits must pass through `safe_commit(session)` with lock retry protection to prevent `database is locked` / `busy` errors during concurrent scrapes and dashboard interactions.
4. **Zero-Config PostgreSQL Auto-Migration**: If a local PostgreSQL instance is running on port 5432, `database.py` automatically detects it and migrates data from SQLite to PostgreSQL.
5. **Quality Gates**: All code changes must pass `ruff check src/ tests/`, `mypy src/ tests/`, and `pytest`.

---

## 5. Refresh Triggers

Update this repository map whenever:
- A new portal scraper or spatial service is integrated.
- Pipeline stages or filtering rules are restructured.
- Database tables or schema migration lists are modified.
- CLI commands in `main.py` are added or changed.
