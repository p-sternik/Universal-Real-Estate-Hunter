from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.services.geoportal import GeoportalService


def test_geoportal_url_generator():
    svc = GeoportalService()
    url_parcel = svc.generate_geoportal_url(parcel_id="181609_2.0001.2643/7")
    assert "identifyParcel=181609_2.0001.2643/7" in url_parcel

    url_coords = svc.generate_geoportal_url(lat=50.04, lon=22.01)
    assert "locatePoint" in url_coords
    assert "50.04" in url_coords


@pytest.mark.asyncio
async def test_get_mpzp_info_active():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<GetFeatureInfo_Result><ROWSET name='MPZP_PRZEZNACZENIE_TERENU'>"
        "<ROW><FUN_SYMB>MN</FUN_SYMB><FUN_NAZWA>tereny mieszkaniowe</FUN_NAZWA>"
        "<NAZWA_PLAN>Plan Centrum</NAZWA_PLAN></ROW></ROWSET></GetFeatureInfo_Result>"
    )
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_mpzp_info(client_mock, 100.0, 200.0)
    assert res["status"] == "OBOWIĄZUJĄCY"
    assert res["symbol"] == "MN"
    assert "MN: tereny mieszkaniowe" in res["zone"]
    assert res["plan_name"] == "Plan Centrum"


@pytest.mark.asyncio
async def test_get_mpzp_info_missing():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "m. Rzeszów: brak wyniku dla wskazanego obszaru"
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_mpzp_info(client_mock, 300.0, 400.0)
    assert res["status"] == "BRAK_PLANU_LUB_CYFRYZACJI"
    assert "Brak MPZP" in res["zone"]


@pytest.mark.asyncio
async def test_get_flood_risk_isok_hazard():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "features": [
            {
                "id": "NZ.RiskZone.1",
                "properties": {"lor_qualitativevalue": "wysokie ryzyko"},
            }
        ]
    }
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_flood_risk_isok(client_mock, 500.0, 600.0)
    assert res["flood_zone"] == "ZAGROŻENIE_POWODZIOWE"
    assert res["risk_level"] == "wysokie ryzyko"
    assert "strefie zagrożenia powodziowego" in res["description"]


@pytest.mark.asyncio
async def test_get_flood_risk_isok_safe():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"features": []}
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_flood_risk_isok(client_mock, 700.0, 800.0)
    assert res["flood_zone"] == "BRAK"
    assert res["risk_level"] is None
    assert "poza strefą ISOK" in res["description"]
