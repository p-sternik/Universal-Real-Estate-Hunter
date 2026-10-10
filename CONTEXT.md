# Universal Real Estate Hunter — Domain Context

Domain model, terminology, and core business rules for Universal Real Estate Hunter.

---

## 1. System Identity & Mission

**Universal Real Estate Hunter** (`rzeszow-houses-scrapper`) is an automated pipeline that continuously crawls real estate portals, parses unstructured Polish listing descriptions, cross-references official spatial and environmental registries, executes multi-stage forensic evaluation (including LLM and Vision AI), computes market valuations, and provides an interactive dashboard and push notifications for high-conviction residential properties.

---

## 2. Evidence Provenance & Conflict Resolution

No single listing source proves the property's complete physical state. Keep each claim tied to its source and confidence:

| Source | What it can establish | Limits |
| :--- | :--- | :--- |
| Seller/agent description | Specific claims about rooms, fixtures, materials, dates, and included items | Marketing claims; not independently verified |
| Listing photos | Visible features of the photographed scene | May be stale, staged, rendered, or depict another unit; unseen features remain unknown |
| Official registries | Facts recorded by the named authority (parcel, zoning, flood designation, permits) | Coverage, location matching, update dates, and registry scope can limit certainty |
| Portal metadata | The value selected in a portal field | Frequently stale, defaulted, or copied from another offer |

Resolve portal-tag conflicts using better-sourced evidence, while preserving the conflict and its provenance in `discrepancies`. Describe seller statements as claims until independently confirmed. A photo supports only what is actually visible and does not prove that the scene belongs to the current listing.

---

## 3. Finish Condition Taxonomy & The Living Quarters Principle

The finish condition is strictly governed by the **Living Quarters Principle**: readiness of primary residential interior spaces (kitchen, bathrooms, living room, bedrooms, finished floors, functional installations).

### Taxonomy Enums ([`src.models.enums.FinishCondition`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/models/enums.py))

1. **`pod_klucz` / `DO_ZAMIESZKANIA`**:
   - **Target State**: Turnkey. Ready for immediate move-in without interior construction work.
   - **Positive Indicators (claims that require corroboration)**: Equipped kitchen with appliances, finished/tiled bathrooms with fixtures, laid floors (parkiet, panele, gres), painted walls, operational heating, or currently inhabited.
   - **Ancillary Elements Rule**: If interior living quarters are turnkey, but minor outdoor or cosmetic works remain (e.g. *taras do wykończenia*, *niezagospodarowany ogród*, *brak kostki brukowej*, *poddasze do adaptacji*), the property **MUST REMAIN `DO_ZAMIESZKANIA`**. Record unfinished exterior items in `finish_note` (e.g. *"Wnętrze mieszkalne w pełni wykończone; do zrobienia taras i ogród"*). Do **not** downgrade to `DO_WYKONCZENIA`.
   - **False-Friend Traps**: Disregard historical statements (*"kupiony w stanie deweloperskim i wykończony"*) and mentions of other units (*"dostępne inne segmenty do wykończenia"*). Focus strictly on the subject unit.

2. **`do_wykonczenia` / `DO_WYKONCZENIA`**:
   - **Target State**: Building shell is erected, but interior living quarters require major trades before move-in (bare screeds/plasters, no bathroom fittings, no kitchen, raw floors).
   - Distinct from developer primary-market sale with future delivery date.

3. **`deweloperski` / `DEWELOPERSKI`**:
   - **Target State**: Primary market sale by a developer/builder, standard developer finish (*stan deweloperski*), or actively under construction with planned delivery (*"oddanie IV kwartał 2025"*).

4. **`surowy_zamkniety` / `SUROWY_ZAMKNIETY`** & **`surowy_otwarty` / `SUROWY_OTWARTY`**:
   - Explicitly labeled raw building shells (SSZ / SSO).

5. **`do_remontu` / `DO_REMONTU`**:
   - Previously inhabited building requiring renovation or modernization.

---

## 4. Property & Segment Taxonomies

### Property Category ([`src.models.enums.PropertyCategory`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/models/enums.py))
- `DOM`: Houses (detached, semi-detached, terraced).
- `MIESZKANIE`: Apartments / flats.
- `DZIALKA`: Land plots.

### Building Types & Segment Subtypes ([`src.models.enums.BuildingType`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/models/enums.py), [`src.models.enums.SegmentSubtype`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/models/enums.py))
- `WOLNOSTOJACY`: Detached house.
- `BLIZNIAK`: Semi-detached house.
- `SZEREGOWIEC`: Terraced house / row house.
  - `SKRAJNY`: Corner/end segment (larger plot, fewer direct neighbours).
  - `SRODKOWY`: Middle segment (smaller plot, neighbours on both sides). Minimum plot threshold rule: houses with plot < 200 m² are rejected (Stage 1 absolute floor; Stage 2 applies the same floor to middle segments and to plots extracted from the description).
  - `NIEOKRESLONY`: Subtype not specified in title/metadata, resolved semantically from description.

### Access Road Types ([`src.models.enums.RoadType`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/models/enums.py))
- `ASFALT`: Asphalt municipal or public road.
- `KOSTKA`: Paving stones.
- `UTWARDZONA`: Hardened gravel/macadam.
- `POLNA`: Dirt / unpaved road (triggers con or rejection unless municipal takeover is documented).
- `NIEZNANA`: Unresolved.

---

## 5. Spatial & Extended Due Diligence Terms

- **GUGiK ULDK**: Central Cadastral Parcel register. Resolves parcel identifier (`main_parcel_id`, e.g. `186301_1.0001.123/4`), cadastral area, front width, and aspect ratio.
- **ISOK**: System for Flood Protection. Identifies flood risk zones (`ZAGROŻENIE_POWODZIOWE`).
- **MPZP**: Local Spatial Development Plan (*Miejscowy Plan Zagospodarowania Przestrzennego*). Validates zoning (`OBOWIĄZUJĄCY` vs `BRAK_PLANU_LUB_CYFRYZACJI` requiring WZ decision).
- **SOPO (PIG-PIB)**: Landslide Counteraction System. Identifies active landslides (`OSUWISKO`) or landslide hazard areas (`ZAGROŻENIE_OSUWISKIEM`), which penalize qualification scores heavily (-50 pts).
- **EGiB**: Cadastral Land and Building Register. Checks whether house is registered (`UJAWNIONY` with usage code B/Br) vs `BRAK_W_EWIDENCJI` (risk of unpermitted construction / *samowola budowlana* or lack of occupancy permit).
- **SIDUSIS (internet.gov.pl)**: Official broadband registry. Confirms active FTTH fiber (`ŚWIATŁOWÓD_AKTYWNY`), planned public network (KPO/FERC), or lack of coverage.
- **GUNB / RWDZ**: Central Construction Registry. Audits building permits and contentious investments within 200 m radius.
- **CAMS & GIOŚ**: Atmospheric monitoring combining Copernicus CAMS reanalysis and State Environmental Protection (GIOŚ) stations for heating season smog risk (PM2.5 averages and smog days count).
- **OSRM**: Open Source Routing Machine for drive and rail/pedestrian commute modeling.
- **KRS / REGON**: Developer verification auditing registered share capital, age of entity, and legal status to detect special-purpose shells (*spółki celowe z minimalnym kapitałem 5 000 PLN*).

---

## 6. Listing Lifecycle & Physical Fingerprinting

- **Physical Fingerprint**: A normalized hash generated via [`generate_physical_fingerprint`](file:///C:/Users/User/WebstormProjects/apartments-scrapper/src/filters/fingerprint.py) combining:
  `{street_token}_{rounded_area_m2}_{price_bracket}`.
  Prevents duplicate listings when different real estate agencies post the same property on Otodom, Morizon, and OLX with differing titles or prices.
- **Status Lifecycles**:
  - `ListingStatus`: `ACTIVE` (currently available) vs `DELISTED` / `REMOVED`.
  - `UserCRMStatus`: `NEW` -> `FAVORITE` / `TO_VISIT` / `REJECTED`.
  - `PriceHistory`: Recorded on every price delta for tracking negotiation leverage and days on market.
