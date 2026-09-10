import pytest
from src.services.geoportal import GeoportalService


def test_geoportal_url_generator():
    svc = GeoportalService()
    url_parcel = svc.generate_geoportal_url(parcel_id="181609_2.0001.2643/7")
    assert "identifyParcel=181609_2.0001.2643/7" in url_parcel

    url_coords = svc.generate_geoportal_url(lat=50.04, lon=22.01)
    assert "locatePoint" in url_coords
    assert "50.04" in url_coords