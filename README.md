# 🏡 Universal Real Estate Hunter & Intelligence Platform

[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue.svg)](https://www.python.org/)
[![Docker Ready](https://img.shields.io/badge/docker-ready-2496ED.svg?logo=docker&logoColor=white)](https://www.docker.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Clean](https://img.shields.io/badge/code%20style-pydantic%20%7C%20sqlalchemy%202.0-emerald.svg)](https://docs.pydantic.dev/)

An advanced, asynchronous real estate monitoring, analytical pipeline, and market intelligence platform. Designed to continuously track, qualify, deduplicate, and analyze property listings across major portals (**Otodom**, **OLX**, **Nieruchomości-online**, **Morizon**) with official cadastral data integration (**Polish National Geoportal / GUGiK**), interactive map CRM, and real-time Discord/Telegram notifications.

> 🇵🇱 *Polska wersja dokumentacji jest dostępna w pliku [README.pl.md](README.pl.md).*

---

## ✨ Key Features

### 🌐 1. High-Performance Multi-Portal Scraping
- **Anti-Bot Bypass:** Uses `curl_cffi` with Chrome TLS fingerprint impersonation (`impersonate="chrome120"`) to seamlessly pass Cloudflare and DataDome protections without paid proxies.
- **Direct Next.js Hydration Extraction:** Extracts pristine structured JSON from `__NEXT_DATA__` and `__PRERENDERED_STATE__` script tags, minimizing brittle HTML DOM parsing.
- **Detail Page Refresh Control:** Intelligent cache layer skipping recently scraped listings while tracking price drops and listing updates.

### 🗺️ 2. Official Cadastral & Geospatial Intelligence (GUGiK Geoportal)
- **Automatic Parcel Identification:** Queries the Polish National ULDK API (`GetParcelByXY`) to resolve cadastral parcel ID (`TERYT`), commune, precinct, and parcel number from GPS coordinates.
- **Accurate Surface Area Calculation:** Downloads exact boundary polygons in `EPSG:2180` and computes true legal land area in m² (handling enclaves and multi-polygons).
- **Industrial & Commercial Risk Audit:** Scans surrounding parcels within 120 meters in 8 cardinal directions via KIEG WMS (`GetFeatureInfo`) for zoning risks:
  - `Ba` – Industrial / production facilities
  - `Bi` – Commercial / warehousing complexes
  - `Tk` – Railway grounds
- **Automated Score Penalty & Alerts:** Automatically subtracts 25 points from listings near industrial risks, alerts in cons, and provides direct 1-click deep links to the National Geoportal.

### 🧠 3. Two-Stage Qualification & Semantic Engine
- **Stage 1 (Hard Rules):** Enforces strict numerical thresholds (maximum price, price/m², living area, plot area, construction year, and whitelist/blacklist locations).
- **Stage 2 (Semantic NLP & Heuristics):** Analyzes listing titles and full descriptions:
  - Detects **Finish Condition**: *Turnkey / Ready to Move In*, *Developer State*, *Raw Closed*, *Needs Renovation*.
  - Flags **3D Visualizations & Renderings** (alerting on listings lacking real photos).
  - Detects **Utilities**: Municipal sewerage vs. Septic tank (`szambo`), gas heating, heat pumps, solid fuel, and high-speed fiber optic internet.
- **Cross-Agency Deduplication (`property_fingerprint`):** Matches properties listed simultaneously by multiple real estate agencies using fuzzy spatial, pricing, and dimensional signatures.
- **Price History Tracking:** Tracks historical price drops with percentage changes and timestamps.

### 📊 4. Interactive Live Web Dashboard & CRM
- **Modern Dark UI:** High-density, professional design built on strict neutral palette and tabular figures.
- **Interactive Leaflet Map:** Custom color-coded pins, clustering, and viewport synchronization.
- **Personal CRM:** Mark listings as ★ Favorites, 📅 Scheduled Visits, or ✕ Rejected. Add private notes from property tours.
- **Multi-Profile Search Manager:** Switch between multiple profiles (e.g. *Houses in Rzeszów*, *Flats in Kraków*, *Plots in Warsaw*) directly from the browser.
- **Photo Galleries & Lightbox:** Inline thumbnail carousels and full-screen image viewer.

### ⏱️ 5. Smart Scheduler & Quiet Hours
- Configurable continuous background monitoring (e.g. every 15–20 minutes during daytime).
- Automatic **Night Mode / Quiet Hours** (e.g. reducing checks to every 60 minutes between 22:00 and 07:00).
- Dynamic interval adjustments from web UI without restarting the container.

---

## 🏗️ Architecture

```text
Universal-Real-Estate-Hunter/
├── config/                  # Pydantic BaseSettings & environment loader
│   └── settings.py          # Thresholds, default whitelist/blacklist, database URLs
├── src/
│   ├── models/              # Pydantic v2 schemas and enums
│   ├── scrapers/            # Multi-portal scrapers (Otodom, OLX, Nieruchomości-online, Morizon)
│   ├── filters/             # Qualification engine (Stage 1 numerical + Stage 2 NLP + fingerprint)
│   ├── storage/             # Async SQLAlchemy 2.0 models, repository & automatic SQLite migrations
│   ├── services/
│   │   ├── geoportal.py     # GUGiK ULDK & KIEG WMS spatial audit service
│   │   ├── geocoder.py      # Nominatim caching geocoder
│   │   ├── pipeline.py      # Orchestrator running scraping, audit, storage, and alerts
│   │   ├── config_manager.py# Multi-profile & scheduler JSON configuration manager
│   │   ├── live_dashboard.py# aiohttp async web server & REST API
│   │   ├── discord_notifier.py # Rich Discord embed notifier
│   │   ├── telegram_notifier.py# HTML Telegram bot notifier
│   │   └── report_generator.py # Static standalone HTML dashboard generator
│   └── scheduler/           # Periodic runner with day/night adaptive loop
├── tests/                   # Automated pytest suite
├── Dockerfile               # Production container image (Python 3.12-slim)
├── docker-compose.yml       # Multi-service setup (Dashboard + Scraper Daemon)
├── search_config.json       # Live profiles and scheduler configuration
├── main.py                  # Unified CLI entrypoint
└── listings.db              # SQLite database (persisted locally or in Docker volume)
```

---

## 🚀 Quickstart with Docker (Recommended)

### 1. Clone the repository
```bash
git clone https://github.com/p-sternik/Universal-Real-Estate-Hunter.git
cd Universal-Real-Estate-Hunter
```

### 2. Configure environment variables
Copy the example environment file and add your Discord or Telegram credentials (optional):
```bash
cp .env.example .env
```

### 3. Launch with Docker Compose
```bash
docker compose up -d
```

The system will start two containers:
1. **`estate_hunter_dashboard`**: Live Web Dashboard accessible at **`http://localhost:8080`**.
2. **`estate_hunter_scraper`**: Continuous background scraper monitoring active search profiles.

### 4. Check logs
```bash
docker compose logs -f scraper
```

---

## 💻 Local Installation (Without Docker)

### Prerequisites
- Python 3.11, 3.12, or 3.13
- pip & virtualenv

### 1. Setup Virtual Environment
```bash
# Clone repository
git clone https://github.com/p-sternik/Universal-Real-Estate-Hunter.git
cd Universal-Real-Estate-Hunter

# Create and activate virtual environment
python -m venv venv
# Linux / macOS:
source venv/bin/activate
# Windows PowerShell:
.\venv\Scripts\Activate.ps1
```

### 2. Install Dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. Initialize Database
```bash
python main.py init-db
```

---

## 🛠️ CLI Usage & Commands

The application provides a unified CLI via [`main.py`](main.py):

| Command | Description | Example |
| :--- | :--- | :--- |
| `run` | Start continuous monitoring daemon | `python main.py run` or `python main.py run --interval 15` |
| `once` | Run a single scraping and qualification pass | `python main.py once` or `python main.py once --profile "Domy Rzeszów"` |
| `dashboard` | Launch real-time web UI CRM & Leaflet map | `python main.py dashboard --port 8080` |
| `geoportal` | Audit saved listings with GUGiK Geoportal | `python main.py geoportal --limit 50` |
| `report` | Generate standalone HTML analytical report | `python main.py report` (opens in browser) |
| `view` | View qualified listings in formatted terminal table | `python main.py view --status QUALIFIED` |
| `reindex` | Re-evaluate all database listings with latest filters | `python main.py reindex` |
| `geocode` | Backfill missing GPS coordinates via Nominatim | `python main.py geocode` |
| `test-webhook` | Send a test notification to Discord / Telegram | `python main.py test-webhook` |

---

## ⚙️ Configuration & Customization

### 1. Environment Variables (`.env`)
```ini
# Database (SQLite by default, PostgreSQL supported)
DATABASE_URL=sqlite+aiosqlite:///listings.db

# Notifications
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=-100123456789

# Scheduler fallback (if not set in search_config.json)
CHECK_INTERVAL_MINUTES=20
```

### 2. Search Profiles (`search_config.json`)
You can configure multiple independent search profiles (Houses, Apartments, Plots) across any Polish city via the Web Dashboard or by editing `search_config.json`:

```json
{
  "profiles": [
    {
      "id": "rzeszow_domy",
      "name": "Domy Rzeszów",
      "enabled": true,
      "category": "dom",
      "city": "Rzeszów",
      "distance_radius": 15,
      "min_price": 400000,
      "max_price": 1300000,
      "min_area_home": 100,
      "max_area_home": 160,
      "min_area_plot": 300,
      "allowed_finish_conditions": ["do zamieszkania", "deweloperski"],
      "allow_visualisations": false
    }
  ],
  "scheduler": {
    "interval_minutes": 20,
    "night_mode": true,
    "night_interval_minutes": 60,
    "quiet_hours_start": "22:00",
    "quiet_hours_end": "07:00"
  }
}
```

---

## 🗺️ How Geoportal Spatial Audit Works

When an offer qualifies, the system performs a zero-cost spatial audit against the official Polish National Spatial Infrastructure (GUGiK):

1. **Parcel Resolution:** ULDK API identifies the cadastral plot ID (e.g. `181609_2.0001.2643/7`).
2. **True Legal Area:** Geometrical calculation computes the polygon surface in square meters directly from official land borders.
3. **Zoning Hazard Scan:** KIEG WMS evaluates land-use contours in a 120m radius. If an industrial (`Ba`), commercial warehouse (`Bi`), or railway (`Tk`) contour is detected, the listing is flagged with a warning and penalized by 25 points in the qualification score.

---

## 🧪 Running Automated Tests

Run the test suite with `pytest`:
```bash
pytest
```

---

## 🔒 Security & Open Source Practices

- **Never commit `.env` or `listings.db`**: Both are explicitly excluded in `.gitignore` and `.dockerignore`.
- **Stateless Containers**: In Docker, data is mounted to `/app/data/listings.db` to ensure persistent storage across restarts and upgrades.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE) — free for personal and commercial use.
