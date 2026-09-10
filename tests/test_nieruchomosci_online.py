from bs4 import BeautifulSoup

from src.models.enums import (
    BuildingType,
    FinishCondition,
    HeatingType,
    RoadType,
    SewerageType,
)
from src.scrapers.nieruchomosci_online import NieruchomosciOnlineScraper


def test_nieruchomosci_online_parse_tile():
    scraper = NieruchomosciOnlineScraper()

    sample_html = """
    <div class="tile">
        <h2><a class="title" href="https://rzeszow.nieruchomosci-online.pl/dom-szeregowy,skrajny/123456.html">Segment skrajny z garażem, Słocina</a></h2>
        <div class="tile-inner">
            <p class="province">Słocina, Rzeszów</p>
            <p class="primary-display">
                <span>950 000 zł</span>
                <span class="area">125,5 m²</span>
            </p>
            <div class="attributes__box">
                Powierzchnia działki: 380 m²
            </div>
            <div class="tile-details-teaser">
                Sprzedam segment skrajny. Garaż w bryle budynku, dojazd asfaltowy.
            </div>
            <img src="https://i.st-nieruchomosci-online.pl/test.jpg" />
        </div>
    </div>
    """

    soup = BeautifulSoup(sample_html, "html.parser")
    tile = soup.select_one("div.tile")
    listing = scraper._parse_tile(tile)

    assert listing is not None
    assert listing.id == "123456"
    assert listing.portal == "NieruchomosciOnline"
    assert listing.price == 950_000.0
    assert listing.area_home == 125.5
    assert listing.area_plot == 380.0
    assert "Słocina" in listing.location_raw
    assert listing.main_image_url == "https://i.st-nieruchomosci-online.pl/test.jpg"


def test_nieruchomosci_online_parse_detail_full():
    scraper = NieruchomosciOnlineScraper()

    detail_html = """
    <html><body>
    <div id="detailsTable">
      <ul class="list-h">
        <li><strong>Rodzaj domu:</strong> <span>dom szeregowy; rok budowy: 2021</span></li>
        <li><strong>Charakterystyka domu:</strong> <span>100 m², 4 pokoje, 2 łazienki; stan: do wykończenia</span></li>
        <li><strong>Działka:</strong> <span>200 m²</span></li>
        <li><strong>Media:</strong> <span>prąd, woda miejska, kanalizacja; ogrzewanie: gazowe, centralne ogrzewanie; światłowód</span></li>
        <li><span>dojazd drogą asfaltową, ogrodzenie całkowite</span></li>
        <li><strong>Adres:</strong> <span>Projektant, Rzeszów, podkarpackie</span></li>
      </ul>
    </div>
    <div id="boxCustomDescWrapper">
      <h2 class="header-b">Opis nieruchomości</h2>
      <p class="body-md">Dom w stanie do wykończenia we własnym zakresie. Duża działka.</p>
    </div>
    <script type="application/ld+json">
    {
      "@type": "House",
      "geo": {"@type": "GeoCoordinates", "latitude": "50.01686", "longitude": "22.006613"},
      "yearBuilt": "2021",
      "additionalProperty": [
        {"@type": "PropertyValue", "name": "Utilities included", "value": true},
        {"@type": "PropertyValue", "name": "Septic system", "value": false}
      ]
    }
    </script>
    </body></html>
    """

    detail = scraper._parse_detail(detail_html)

    assert detail["finish_condition"] == FinishCondition.DO_WYKONCZENIA
    assert detail["heating"] == HeatingType.GAZOWE
    assert detail["sewerage"] == SewerageType.MIEJSKA
    assert detail["has_fiber"] is True
    assert detail["building_type"] == BuildingType.SZEREGOWIEC
    assert detail["year_built"] == 2021
    assert detail["area_home"] == 100.0
    assert detail["area_plot"] == 200.0
    assert detail["rooms"] == 4
    assert detail["access_road_type"] == RoadType.ASFALT
    assert detail["coordinates"] == (50.01686, 22.006613)
    assert "we własnym zakresie" in detail["description"]


def test_nieruchomosci_online_parse_detail_septic_and_apply():
    scraper = NieruchomosciOnlineScraper()

    detail_html = """
    <html><body>
    <div id="detailsTable">
      <ul class="list-h">
        <li><strong>Charakterystyka domu:</strong> <span>90 m², 3 pokoje; stan: surowy zamknięty</span></li>
        <li><strong>Media:</strong> <span>woda ze studni, szambo; ogrzewanie: pompa ciepła</span></li>
      </ul>
    </div>
    <script type="application/ld+json">
    {
      "@type": "House",
      "geo": {"@type": "GeoCoordinates", "latitude": "0", "longitude": "0"},
      "additionalProperty": [{"@type": "PropertyValue", "name": "Septic system", "value": true}]
    }
    </script>
    </body></html>
    """

    detail = scraper._parse_detail(detail_html)
    assert detail["finish_condition"] == FinishCondition.SUROWY_ZAMKNIETY
    assert detail["heating"] == HeatingType.POMPA_CIEPLA
    assert detail["sewerage"] == SewerageType.SZAMBO
    assert "coordinates" not in detail  # 0,0 is not a real coordinate


def test_nieruchomosci_online_apply_detail():
    scraper = NieruchomosciOnlineScraper()

    sample_html = """
    <div class="tile">
        <h2><a class="title" href="https://rzeszow.nieruchomosci-online.pl/dom-wolnostojacy/654321.html">Dom wolnostojący, Słocina</a></h2>
        <p class="province">Słocina, Rzeszów</p>
        <p class="primary-display"><span>1 100 000 zł</span><span class="area">130 m²</span></p>
    </div>
    """
    soup = BeautifulSoup(sample_html, "html.parser")
    listing = scraper._parse_tile(soup.select_one("div.tile"))
    assert listing is not None

    scraper._apply_detail(
        listing,
        {
            "finish_condition": FinishCondition.DO_ZAMIESZKANIA,
            "heating": HeatingType.POMPA_CIEPLA,
            "year_built": 2018,
            "description": "Pełny opis z oferty.",
        },
    )
    assert listing.finish_condition == FinishCondition.DO_ZAMIESZKANIA
    assert listing.heating == HeatingType.POMPA_CIEPLA
    assert listing.year_built == 2018
    assert listing.raw_description == "Pełny opis z oferty."
