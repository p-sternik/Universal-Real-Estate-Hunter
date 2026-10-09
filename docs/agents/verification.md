# Verification & Quality Gates Guide — Universal Real Estate Hunter

Verification workflows, quality gates, and command recipes for Universal Real Estate Hunter.

---

## 1. Quality Gates (MANDATORY FOR ALL CODE CHANGES)

Every code change touching scrapers, models, filters, storage, or the web interface must satisfy all three gates before merging or committing:

```powershell
# 1. Linter & Import Sorter (zero warnings / errors)
uv run ruff check src/ tests/

# 2. Static Type Checker (strict types on filters and pipeline)
uv run mypy src/ tests/

# 3. Test Suite (all 346+ tests must pass)
uv run pytest
```

---

## 2. Change Category-to-Check Matrix

| Area Touched | Recommended Verification Commands | Key Test Targets | Expected Side Effects / Notes |
| :--- | :--- | :--- | :--- |
| **Scraper Parsers** (`src/scrapers/`) | `uv run pytest tests/test_otodom_parser.py tests/test_morizon.py tests/test_olx.py tests/test_nieruchomosci_online.py` | HTML parsing, pagination, JSON extraction | Scrapers use mock HTML/JSON fixtures in tests. No real network calls are made. |
| **Filters & LLM Rules** (`src/filters/`) | `uv run pytest tests/test_filters.py tests/test_fingerprint.py tests/test_llm_config.py tests/test_vision_analyzer.py` | Living Quarters Principle, regex accuracy, borderline margins | Ensure test cases cover false-friend traps and ancillary works rules. |
| **Spatial / Geoportal Services** (`src/services/geoportal.py`, `air_quality.py`, etc.) | `uv run pytest tests/test_geoportal.py tests/test_air_quality.py tests/test_commute.py tests/test_gunb.py` | Cadastral parcel parsing, flood zones, air quality caching | Network requests are mocked via `pytest-asyncio` / `unittest.mock`. |
| **Storage & Migrations** (`src/storage/`) | `uv run pytest tests/test_storage.py` | Schema column additions, SQLite lock retry, Postgres auto-migration | Creates isolated temporary SQLite databases in `.pytest_tmp/`. |
| **Pipeline & Orchestration** (`src/services/pipeline.py`) | `uv run pytest tests/test_pipeline.py tests/test_notifications.py` | Deduplication, relisting, notification quiet hours | Checks pipeline cycle end-to-end with mocked scrapers. |
| **Web Dashboard & REST APIs** (`src/services/live_dashboard.py`) | `uv run pytest tests/test_dashboard_images_valuation.py tests/test_crm.py` | API response schemas, omitted fields in `/api/listings` | Tests use `aiohttp.test_utils.AioHTTPTestCase`. |
| **Scheduler & Lifecycle** (`src/scheduler/runner.py`) | `uv run pytest tests/test_scheduler.py` | Interval cron timing, graceful shutdown | Tests verify thread lock release on shutdown. |

---

## 3. Tooling & Environment Prerequisites

- **Package Manager**: `uv` (version >= 0.12.13).
  - Run all commands prefixed with `uv run` to ensure execution in the isolated `.venv`.
- **Python Version**: `>=3.11` (currently running on Python 3.13 / 3.11 virtualenv).
- **Format Code**:
  ```powershell
  uv run ruff format src/ tests/
  ```
- **Security Audit**:
  ```powershell
  uv run bandit -c pyproject.toml -r src/
  ```
- **Container Testing (Docker Compose)**:
  When modifying Dockerfile or dependencies:
  ```powershell
  docker compose build
  docker compose up -d
  ```

---

## 4. Known Environment Nuances & Gotchas

1. **Windows Console Encoding**:
   `main.py` explicitly forces UTF-8 on Windows stdout/stderr (`sys.stdout.reconfigure(encoding="utf-8")`) to prevent `UnicodeEncodeError` with Polish characters (*ą, ę, ś, ć, ż, ź*).
2. **Mypy Strictness Boundaries**:
   Per [`pyproject.toml`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/pyproject.toml#L133-L142), strict typed defs (`disallow_untyped_defs = true`) are enforced on:
   - `src.filters.llm_analyzer`
   - `src.filters.*`
   - `src.services.pipeline`
   - `src.services.geocoder`
   Legacy modules are checked without `--check-untyped-defs` to avoid blocking quality gates on legacy functions.
3. **Pytest Temp Directories**:
   Pytest is configured with `--basetemp=.pytest_tmp` in `pyproject.toml` to prevent filesystem lock conflicts on Windows.
