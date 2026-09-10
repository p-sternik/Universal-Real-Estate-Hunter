# 🏡 Rzeszów Real Estate Hunter & Scraper Pipeline

Zaawansowany, asynchroniczny system monitorowania, analityki oraz inteligentnego filtrowania ofert sprzedaży domów i szeregówek w Rzeszowie i okolicach (+15 km).

System wykorzystuje bezpośrednią ekstrakcję stanu hydracji JSON (`__NEXT_DATA__` w Next.js), wieloetapowy silnik kwalifikacji (twarde reguły + analiza semantyczna NLP/LLM), deduplikację ofert między agencjami (`property_fingerprint`), historię zmian cen w bazie danych oraz powiadomienia w formie bogatych Discord Embed / bota Telegram.

---

## 🏗️ Architektura Projektu

```text
Universal-Real-Estate-Hunter/
├── config/
│   ├── __init__.py
│   └── settings.py          # Konfiguracja Pydantic Settings (.env, progi, whitelist, blacklist)
├── src/
│   ├── __init__.py
│   ├── models/              # Schematy Pydantic v2 i typy wyliczeniowe (Enums)
│   │   ├── __init__.py
│   │   ├── enums.py         # BuildingType, SegmentSubtype, RoadType, MarketType, QualificationStatus
│   │   └── listing.py       # ListingSchema, FilterResult, RawListing, Coordinates
│   ├── scrapers/            # Asynchroniczne moduły ekstrakcji danych
│   │   ├── __init__.py
│   │   ├── base.py          # Klasa bazowa BaseScraper (curl_cffi, httpx, rotacja nagłówków, retry)
│   │   ├── otodom.py        # Scraper Otodom.pl (__NEXT_DATA__ JSON + detail page hydration)
│   │   └── olx.py           # Scraper OLX.pl (__PRERENDERED_STATE__ / selektory DOM)
│   ├── filters/             # Dwuetapowy silnik kwalifikacji i deduplikacji
│   │   ├── __init__.py      # QualificationEngine (koordynator etapów I i II + scoring)
│   │   ├── stage1_hard_rules.py  # Etap I: Budżet, metraż, działka, Whitelist / Blacklist
│   │   ├── stage2_semantic.py    # Etap II: Analiza opisu (segment skrajny, droga, garaż, skarpa)
│   │   ├── fingerprint.py        # Algorytm deduplikacji agencyjnej (property_fingerprint)
│   │   └── llm_analyzer.py       # Opcjonalny moduł LLM (OpenAI API / Ollama)
│   ├── storage/             # Warstwa bazy danych i ORM (SQLAlchemy 2.0 async)
│   │   ├── __init__.py
│   │   ├── database.py      # Silnik async (SQLite / PostgreSQL), sesje, init_db
│   │   ├── models.py        # Modele Declarative (ListingModel, PriceHistoryModel)
│   │   └── repository.py    # Wzorzec repozytorium (upsert, historia cen, deduplikacja)
│   ├── services/            # Serwisy aplikacyjne i powiadomienia
│   │   ├── __init__.py
│   │   ├── discord_notifier.py   # Formatowanie i wysyłka bogatych Embedów na Discord Webhook
│   │   ├── telegram_notifier.py  # Obsługa bota Telegram (wiadomości HTML)
│   │   └── pipeline.py           # Orkiestrator całego cyklu przetwarzania ofert
│   └── scheduler/           # Harmonogram zadań
│       ├── __init__.py
│       └── runner.py        # APScheduler (AsyncIOScheduler) / asyncio graceful runner
├── tests/                   # Kompletny zestaw testów automatycznych (pytest)
│   ├── test_filters.py      # Testy reguł Etapu I i Etapu II
│   ├── test_fingerprint.py  # Testy tolerancji deduplikacji (ceny, metraże, ulice)
│   ├── test_otodom_parser.py# Testy parsowania payloadów Otodom i czyszczenia tekstu
│   ├── test_storage.py      # Testy bazy danych, relacji i historii cen
│   └── test_discord.py      # Testy formatowania Discord Embed
├── .env.example             # Szablon zmiennych środowiskowych
├── pyproject.toml           # Metadane projektu i konfiguracja narzędzi
├── requirements.txt         # Zależności pip
├── main.py                  # Główny punkt wejściowy CLI
└── README.md                # Dokumentacja techniczna
```

---

## ⚡ Stack Technologiczny

* **Język:** Python 3.11+ / 3.12 / 3.13
* **Pobieranie danych:**
  * `curl_cffi` – automatyczne omijanie zabezpieczeń antybotowych Cloudflare / DataDome dzięki impersonacji stosu TLS i nagłówków przeglądarki Chrome (`impersonate="chrome120"`).
  * `httpx` – asynchroniczny klient HTTP z obsługą HTTP/2 jako fallback.
* **Parsowanie danych:**
  * `BeautifulSoup4` / `selectolax` – ekstrakcja skryptów JSON (`<script id="__NEXT_DATA__">`) i czyszczenie HTML.
  * `pydantic` v2 – ścisła walidacja i normalizacja typów danych wejściowych.
* **Baza Danych & ORM:**
  * `SQLAlchemy 2.0` (asynchroniczny) z pełnym wsparciem SQLite (`aiosqlite`) oraz PostgreSQL (`asyncpg`).
  * Automatyczna deduplikacja ofert, relacja jeden-do-wielu dla historii zmian cen (`PriceHistoryModel`).
* **Analiza NLP / LLM:**
  * Dedykowany silnik heurystyczno-wyrażeniowy (RegEx) zoptymalizowany pod specyfikę polskiego rynku nieruchomości.
  * Opcjonalna integracja z `OpenAI API` (`gpt-4o-mini`) lub lokalnym modelem `Ollama` (`llama3.1`).
* **Harmonogram:**
  * `APScheduler 3.x` (`AsyncIOScheduler`) z konfigurowalnym interwałem (domyślnie co 20 minut) i obsługą sygnałów wyłączenia (`SIGINT`, `SIGTERM`).
* **Powiadomienia:**
  * Discord Webhook z kolorami statusu (zielony, niebieski, pomarańczowy), podziałem na sekcje zalet i wad oraz zdjęciem nieruchomości.
  * Telegram Bot API z formatowaniem HTML.

---

## 🎯 Model Kwalifikacji i Filtrowania

### Etap I: Twarde reguły numeryczne i geograficzne
1. **Budżet:** `price <= 1 300 000 zł`
2. **Metraż domu:** `90 m² <= area_home <= 145 m²`
3. **Działka:**
   * `area_plot >= 250 m²`
   * Jeśli w ogłoszeniu brak metrażu działki w nagłówku, oferta **nie jest odrzucana**, lecz kierowana do analizy treści opisu.
4. **Lokalizacja – Blacklist (odrzucenie bezwzględne):**
   * Wykrycie w tytule, lokalizacji lub treści opisu którejkolwiek z fraz: `Matysówka`, `Matysowska`, `Tyczyn`, `Chmielnik`, `Biała`, `Zwięczyca`, `Kielanówka`, `Górna Słocina`, `św. Rocha`, `skarpie`, `teren osuwiskowy` -> **natychmiastowe odrzucenie**.
5. **Lokalizacja – Whitelist (priorytetowe dopuszczenie i status `QUALIFIED_WHITELIST`):**
   * **Słocina:** wyłącznie dolna (rejon Paderewskiego, Witolda, Powstańców Wielkopolskich).
   * **Zalesie:** wyłącznie dolne/centralne (Łukasiewicza, Dunikowskiego, Spacerowa).
   * **Staromieście:** rejon Staromieście Ogrody, Borowa, Lubelska i okolice.
   * **Północ/Wschód:** Trzebownisko, Nowa Wieś, Terliczka, Krasne (wzdłuż DK94), Głogów Małopolski (Niwa, Rogoźnica, rejon stacji PKA).

### Etap II: Analiza semantyczna opisu (RegEx / LLM)
1. **Typ segmentu (`IS_CORNER`):**
   * Wykrywanie cech segmentu skrajnego/narożnego: `skrajny`, `narożny`, `ostatni w rzędzie`.
   * **Reguła segmentu środkowego:** Jeśli nieruchomość jest segmentem środkowym, a działka wynosi `< 200 m²` -> **odrzucenie**.
2. **Standard dojazdu:**
   * Odrzucenie ofert ze stwierdzeniami: `dojazd drogą polną`, `droga nieutwardzona`, `brak bezpośredniego zjazdu`, `droga gruntowa`.
   * Promowanie dojazdu asfaltem lub kostką brukową.
3. **Miejsca postojowe:**
   * Sprawdzanie obecności garażu w bryle budynku lub min. 2 miejsc na podjeździe (wyróżniane w zaletach powiadomienia).
4. **Weryfikacja ukształtowania terenu:**
   * Wykrywanie wzmianek o spadkach terenu, gliniastym podłożu, skarpach i terenach podmokłych.

### Deduplikacja Agencyjna (`property_fingerprint`)
W celu uniknięcia wysyłania 5 powiadomień o tej samej nieruchomości wystawionej przez różne agencje, system generuje unikalny hash bazujący na:
* Znormalizowanej cenie (przedziały co 10 000 zł)
* Metrażu domu z tolerancją +/- 2 m² (przedziały o szerokości 4 m²)
* Metrażu działki z tolerancją +/- 10 m² (przedziały o szerokości 10 m²)
* Ekstrahowanym tokenie ulicy (z ignorowaniem prefiksów, patronów i imion, np. "Paderewskiego" zamiast "Ignacego")

---

## 🚀 Szybki Start

### 1. Instalacja zależności

```bash
# Sklonuj repozytorium lub wejdź do katalogu
cd Universal-Real-Estate-Hunter

# Zainstaluj zależności produkcyjne i testowe
pip install -r requirements.txt
```

### 2. Konfiguracja (.env)

Skopiuj plik `.env.example` do `.env` i uzupełnij Webhook Discorda:

```bash
cp .env.example .env
```

Przykładowy `.env`:
```env
DATABASE_URL=sqlite+aiosqlite:///listings.db
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/TWOJ_WEBHOOK_ID/TWOJ_TOKEN
CHECK_INTERVAL_MINUTES=20

MAX_PRICE=1300000.0
MIN_AREA_HOME=90.0
MAX_AREA_HOME=145.0
MIN_AREA_PLOT=250.0

FETCH_DETAILS=true
```

### 3. Komendy CLI (`main.py`)

* **Uniwersalny cykl scrapingu (dowolne miasto i promień):**
  ```bash
  # Domyślna lokalizacja (z search_config.json / Rzeszów):
  python main.py once

  # Dowolne inne miasto i promień (+km):
  python main.py once --city Kraków --radius 20
  python main.py once --city Warszawa --radius 15
  python main.py once --city Wrocław --radius 25
  ```

* **Uruchomienie ciągłego demona monitorującego (co 20 minut z harmonogramem):**
  ```bash
  python main.py run
  # lub z wybranym miastem:
  python main.py run --city Lublin --radius 15
  ```

* **Uruchomienie serwera Live Universal Dashboard (Mapa Leaflet + CRM + Split View):**
  ```bash
  python main.py dashboard
  # lub
  python main.py server --port 8080
  ```
  Otwiera w przeglądarce interaktywny pulpit nawigacyjny pod adresem `http://127.0.0.1:8080`:
  * **⚙️ Konfiguracja wyszukiwania w locie:** zmiana miasta docelowego, promienia (+km), progów cenowych, metrażu, whitelist i blacklist bezpośrednio w panelu UI z opcją natychmiastowego startu scrapingu!
  * **Filtry w czasie rzeczywistym:** suwak maksymalnej ceny, metraż od/do, minimalna działka, selektor rynku (pierwotny/wtórny) i typu budynku (szeregowiec, bliźniak, wolnostojący).
  * **Ulepszone wyświetlanie ofert:** powiększanie zdjęć w modalnym Lightboxie, bogate tagi cech (`🌱 Działka`, `🏠 Dom`, `🏗️ Pierwotny`, `🛣️ Droga`, `📅 Rok`), boks z dokładnymi powodami odrzucenia dla ofert niespełniających kryteriów.
  * **Interaktywna mapa OpenStreetMap / Leaflet:** kolorowe pinezki ze spiderfyingiem / eliminacją nakładania się ofert w tych samych inwestycjach.
  * **Widok Split (50/50) z dwukierunkową synchronizacją:** kliknięcie w pinezkę przewija listę i podświetla ofertę; kliknięcie *"📍 Pokaż na mapie"* wycentrowuje widok.
  * **Wbudowany CRM & Notatki:** oznaczanie ofert jako ⭐ Ulubione, 📅 Do obejrzenia, 🗑️ Odrzucone oraz prywatne notatki zapisywane w SQLite.
  * **Live Progress Bar:** podgląd paska postępu scrapingu na żywo i dziennik operacji.

* **Geokodowanie brakujących współrzędnych (Nominatim + Cache SQLite):**
  ```bash
  python main.py geocode
  ```

* **Podgląd ofert bezpośrednio w terminalu:**
  ```bash
  python main.py view --status QUALIFIED_WHITELIST --limit 10
  ```

* **Generowanie statycznego pliku raportu HTML:**
  ```bash
  python main.py report
  ```

* **Test powiadomienia Discord Webhook:**
  ```bash
  python main.py test-webhook
  ```

* **Test silnika filtrów na syntetycznych scenariuszach:**
  ```bash
  python main.py test-filter
  ```

* **Inicjalizacja tabel bazy danych:**
  ```bash
  python main.py init-db
  ```

* **Uruchomienie testów jednostkowych:**
  ```bash
  pytest -v
  ```

---

## 📊 Format Powiadomień Discord Embed

Gdy system wykryje nową ofertę lub zmianę ceny zakwalifikowanej nieruchomości, wysyła czytelną kartę:

* **Kolor zielony (`#2ECC71`):** Oferty z Whitelist (np. Słocina Dolna, Zalesie Dolne, Staromieście Ogrody, Trzebownisko, Krasne DK94).
* **Kolor niebieski (`#3498DB`):** Oferty spełniające kryteria ogólne.
* **Kolor pomarańczowy (`#F39C12`):** Oferty zakwalifikowane wymagające weryfikacji ręcznej (np. brak podanego metrażu działki).
* **Pola karty:**
  * **Cena & Metraż:** np. `1 150 000 zł (8 846 zł/m²) | Dom: 130.0 m² | Działka: 380 m²`
  * **Typ & Lokalizacja:** np. `Szeregowiec (skrajny/narożny) | ul. Witolda, Słocina, Rzeszów`
  * **Dojazd & Infrastruktura:** np. `Droga: asfalt | 🚗 Parking/Garaż: TAK`
  * **Kluczowe zalety:** lista wypunktowana (np. Pompa ciepła, Rekuperacja, Garaż w bryle)
  * **Wykryte minusy / uwagi:** np. Wzmianka o nachyleniu działki
  * **Zdjęcie główne:** podgląd miniatury z ogłoszenia
