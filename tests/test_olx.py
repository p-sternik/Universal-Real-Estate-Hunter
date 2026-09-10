import asyncio
import pytest
from src.models.enums import BuildingType
from src.scrapers.olx import OLXScraper


def test_olx_extract_prerendered_state_double_encoded():
    scraper = OLXScraper()

    html = (
        '<script>window.__PRERENDERED_STATE__= "'
        '{\\"listing\\": {\\"listing\\": {\\"ads\\": [{\\"id\\": 123, \\"title\\": \\"Dom testowy\\"}]}}}";</script>'
    )
    state = scraper._extract_prerendered_state(html)
    assert state is not None
    assert state["listing"]["listing"]["ads"][0]["id"] == 123


def test_olx_extract_prerendered_state_object_form():
    scraper = OLXScraper()

    html = (
        '<script>window.__PRERENDERED_STATE__= {"listing": {"listing": {"ads": [{"id": 77}]}}};</script>'
    )
    state = scraper._extract_prerendered_state(html)
    assert state is not None
    assert state["listing"]["listing"]["ads"][0]["id"] == 77


def test_olx_params_dict_prefers_normalized_value():
    scraper = OLXScraper()

    params = [
        {"key": "builttype", "name": "Rodzaj zabudowy", "type": "text", "value": "Wolnostojący", "normalizedValue": "wolnostojacy"},
        {"key": "market", "name": "Rynek", "type": "text", "value": "Wtórny", "normalizedValue": "secondary"},
        {"key": "floor_select", "name": "Liczba pięter", "type": "text", "value": "Parterowy", "normalizedValue": "floor_0"},
        {"key": "area", "name": "Powierzchnia działki", "type": "text", "value": "600 m²"},
    ]
    params_map = scraper._parse_params_dict(params)

    assert params_map["builttype"] == "wolnostojacy"
    assert params_map["market"] == "secondary"
    assert params_map["floor_select"] == "floor_0"
    assert params_map["area"] == "600 m²"  # no normalizedValue -> raw value


@pytest.mark.asyncio
async def test_olx_parse_ad_house_params():
    scraper = OLXScraper()

    ad = {
        "id": 999,
        "title": "Dom wolnostojący na sprzedaż",
        "url": "/d/oferta/dom-IDabcde.html",
        "price": {"regularPrice": {"value": 850000}},
        "params": [
            {"key": "m", "value": "120 m²"},
            {"key": "area", "value": "900 m²"},
            {"key": "builttype", "value": "Wolnostojący", "normalizedValue": "wolnostojacy"},
            {"key": "floor_select", "value": "Parterowy", "normalizedValue": "floor_0"},
            {"key": "market", "value": "Wtórny", "normalizedValue": "secondary"},
        ],
        "location": {"cityName": "Rzeszów", "districtName": "Słocina"},
        "map": {"lat": 50.1, "lon": 22.0},
        "description": "<br />Dom do wykończenia w dobrym stanie.",
    }
    listing = await scraper.parse_ad(ad)

    assert listing is not None
    assert listing.area_home == 120.0
    assert listing.area_plot == 900.0  # 'area' = plot for houses
    assert listing.building_type == BuildingType.WOLNOSTOJACY
    assert listing.floor is None  # floor_select means floors for houses
    assert listing.floors_in_building == 1  # parterowy -> 1 kondygnacja
    assert listing.coordinates == (50.1, 22.0)


@pytest.mark.asyncio
async def test_olx_parse_ad_flat_params():
    scraper = OLXScraper()
    scraper.profile = type("P", (), {"category": "mieszkanie", "name": "test"})  # type: ignore

    ad = {
        "id": 1000,
        "title": "Mieszkanie 3 pokoje",
        "url": "/d/oferta/mieszkanie-IDxyz.html",
        "price": {"regularPrice": {"value": 450000}},
        "params": [
            {"key": "m", "value": "55 m²"},
            {"key": "floor_select", "value": "Poziom 2", "normalizedValue": "floor_2"},
            {"key": "builttype", "value": "Blok", "normalizedValue": "blok"},
        ],
        "location": {"cityName": "Rzeszów"},
        "description": "Mieszkanie do remontu.",
    }
    listing = await scraper.parse_ad(ad)

    assert listing is not None
    assert listing.area_home == 55.0
    assert listing.area_plot is None
    assert listing.floor == 2
    assert listing.floors_in_building is None
