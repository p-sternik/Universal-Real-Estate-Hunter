import io
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from PIL import Image

from src.services.geoportal import GeoportalService


def _png_with_colored_pixels(colors: list[tuple[int, int, int]], size: int = 200) -> bytes:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    px = img.load()
    assert px is not None
    for i, color in enumerate(colors):
        for x in range(i * 20, i * 20 + 20):
            for y in range(10, 30):
                px[x, y] = (*color, 255)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_geoportal_url_generator():
    svc = GeoportalService()
    url_parcel = svc.generate_geoportal_url(parcel_id="181609_2.0001.2643/7")
    assert "identifyParcel=181609_2.0001.2643/7" in url_parcel

    url_coords = svc.generate_geoportal_url(lat=50.04, lon=22.01)
    assert "locatePoint" in url_coords
    assert "50.04" in url_coords

    gunb_url = svc.generate_gunb_url()
    assert gunb_url == "https://wyszukiwarka.gunb.gov.pl/"


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


@pytest.mark.asyncio
async def test_get_gesut_networks_detects_networks():
    svc = GeoportalService()
    png = _png_with_colored_pixels([(0, 0, 255), (255, 0, 0), (128, 51, 0)])
    empty = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    empty_buf = io.BytesIO()
    empty.save(empty_buf, format="PNG")

    def _resp_for(url, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        resp.content = png if "erzeszow" in url else empty_buf.getvalue()
        return resp

    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.side_effect = _resp_for

    res = await svc.get_gesut_networks(client_mock, 50.0375, 22.0047)
    assert res["coverage"] is True
    assert res["networks"]["woda"] is True
    assert res["networks"]["prad"] is True
    assert res["networks"]["kanalizacja"] is True
    assert res["networks"]["gaz"] is False
    assert res["networks"]["cieplo"] is False
    assert res["networks"]["telekomunikacja"] is False
    assert res["sources"] == ["Miasto Rzeszów"]
    assert res["checked_radius_m"] > 0


@pytest.mark.asyncio
async def test_get_gesut_networks_no_coverage():
    svc = GeoportalService()
    img = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = buf.getvalue()
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_gesut_networks(client_mock, 49.2, 22.35)
    assert res["coverage"] is False
    assert all(not v for v in res["networks"].values())
    assert res["sources"] == []


@pytest.mark.asyncio
async def test_get_landslide_risk_sopo_detected():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "features": [
            {
                "id": "sopo.1",
                "properties": {"NAZWA": "Osuwisko Dynów", "STAN": "aktywne"},
            }
        ]
    }
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_landslide_risk_sopo(client_mock, 715000.0, 215000.0)
    assert res["risk"] == "OSUWISKO"
    assert res["has_risk"] is True
    assert "Obszar osuwiska" in res["description"]


@pytest.mark.asyncio
async def test_get_landslide_risk_sopo_safe():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"features": []}
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_landslide_risk_sopo(client_mock, 716000.0, 216000.0)
    assert res["risk"] == "BRAK"
    assert res["has_risk"] is False
    assert "Brak osuwisk" in res["description"]


@pytest.mark.asyncio
async def test_get_egib_full_audit_building_and_soil():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<html><body><table>"
        "<tr><td>Oznaczenie konturu</td><td>B</td></tr>"
        "<tr><td>Klasoużytek</td><td>RIIIa</td></tr>"
        "</table></body></html>"
    )
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_egib_full_audit(client_mock, 717000.0, 217000.0)
    assert res["building_status"] == "UJAWNIONY"
    assert res["soil_class"] == "RIIIa"
    assert res["is_protected_soil"] is True
    assert "RIIIa" in res["protected_classes"]


@pytest.mark.asyncio
async def test_get_egib_full_audit_missing_building():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<html><body><table>"
        "<tr><td>Oznaczenie konturu</td><td>R</td></tr>"
        "<tr><td>Klasa</td><td>RIVb</td></tr>"
        "</table></body></html>"
    )
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_egib_full_audit(client_mock, 718000.0, 218000.0)
    assert res["building_status"] == "BRAK_W_EWIDENCJI"
    assert res["soil_class"] == "RIVb"
    assert res["is_protected_soil"] is False


@pytest.mark.asyncio
async def test_get_gdos_protected_areas():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "features": [
            {
                "id": "gdos.1",
                "properties": {"nazwa": "Dolina Wisłoka", "kodinspire": "PLH180030"},
            }
        ]
    }
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_gdos_protected_areas(client_mock, 719000.0, 219000.0)
    assert res["is_protected"] is True
    assert "Dolina Wisłoka" in res["zone_type"]
    assert "GDOŚ" in res["description"]


@pytest.mark.asyncio
async def test_get_nid_monuments():
    svc = GeoportalService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = (
        "<TABLE class='mainTb'>"
        "<TR><TH>SITENAME</TH><TD>Dwór szlachecki</TD></TR>"
        "<TR><TH>LEGALFOUNDATIONDOCUMENT</TH><TD>Decyzja WKZ A-123/84</TD></TR>"
        "</TABLE>"
    )
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.return_value = mock_resp

    res = await svc.get_nid_monuments(client_mock, 720000.0, 220000.0)
    assert res["is_monument"] is True
    assert res["name"] == "Dwór szlachecki"
    assert "A-123/84" in res["document"]


def test_get_cemetery_proximity():
    svc = GeoportalService()
    # 1. Direct cemetery in MPZP
    res_imm = svc.get_cemetery_proximity(100.0, 200.0, mpzp_zone="1.ZC: tereny cmentarza")
    assert res_imm["has_cemetery_risk"] is True
    assert res_imm["zone"] == "<50m"

    # 2. Cemetery in surrounding parcels
    res_surr = svc.get_cemetery_proximity(
        100.0, 200.0, mpzp_zone="MN", surrounding_risks=["Teren sąsiedni to cmentarz"]
    )
    assert res_surr["has_cemetery_risk"] is True
    assert res_surr["zone"] == "50-150m"

    # 3. Safe
    res_safe = svc.get_cemetery_proximity(100.0, 200.0, mpzp_zone="MN", surrounding_risks=[])
    assert res_safe["has_cemetery_risk"] is False
    assert res_safe["zone"] == "BRAK"


@pytest.mark.asyncio
async def test_get_noise_level_audit_transit_hub():
    svc = GeoportalService()
    client_mock = AsyncMock(spec=httpx.AsyncClient)
    client_mock.get.side_effect = Exception("API error")

    # Coords close to Węzeł Świlcza (50.0631, 21.9167)
    res = await svc.get_noise_level_audit(client_mock, 50.0633, 21.9169)
    assert res["exceeds_threshold"] is True
    assert res["noise_level_db"] >= 68.0
    assert "WYSOKI_HAŁAS" in res["zone"]
