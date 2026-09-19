from unittest.mock import AsyncMock, patch

import pytest

from src.models.enums import BuildingType, QualificationStatus, RoadType, SegmentSubtype
from src.models.listing import FilterResult, ListingSchema
from src.services.config_manager import ConfigManager, NotificationSettings, SearchConfig
from src.services.discord_notifier import DiscordNotifier
from src.services.pipeline import _should_notify
from src.services.telegram_notifier import TelegramNotifier


def _sample_listing() -> ListingSchema:
    return ListingSchema(
        id="notif-1",
        portal="Otodom",
        title="Dom wolnostojący Słocina",
        url="https://otodom.pl/oferta/notif-1",
        price=850_000,
        price_per_m2=7_000,
        area_home=120.0,
        area_plot=600.0,
        building_type=BuildingType.WOLNOSTOJACY,
        segment_subtype=SegmentSubtype.NIEOKRESLONY,
        location_raw="Rzeszów, Słocina",
        access_road_type=RoadType.ASFALT,
    )


def _sample_filter_result(score: float = 85.0) -> FilterResult:
    return FilterResult(
        is_qualified=True,
        status=QualificationStatus.QUALIFIED,
        score=score,
        passed_stage1=True,
        passed_stage2=True,
    )


def test_notification_settings_defaults():
    s = NotificationSettings()
    assert s.enabled is True
    assert s.telegram_enabled is True
    assert s.discord_enabled is True
    assert s.notify_on_new_qualified is True
    assert s.notify_on_price_drop is True
    assert s.notify_on_cycle_summary is True
    assert s.notify_on_cycle_summary_only_if_changes is False
    assert s.notify_on_errors is True
    assert s.min_score_threshold == 0.0
    assert s.quiet_hours_enabled is False
    assert s.is_in_quiet_hours() is False


def test_notification_quiet_hours():
    s = NotificationSettings(
        quiet_hours_enabled=True,
        quiet_hours_start="00:00",
        quiet_hours_end="23:59",
    )
    assert s.is_in_quiet_hours() is True

    s_off = NotificationSettings(
        quiet_hours_enabled=False,
        quiet_hours_start="00:00",
        quiet_hours_end="23:59",
    )
    assert s_off.is_in_quiet_hours() is False


def test_config_manager_notification_roundtrip(tmp_path):
    cfg_file = tmp_path / "search_config.json"
    mgr = ConfigManager(config_path=cfg_file)

    cfg = mgr.get_config()
    assert hasattr(cfg, "notifications")
    assert cfg.notifications.enabled is True

    # Update notification settings
    updated = mgr.update_config(
        {
            "notifications": {
                "telegram_bot_token": "token_123",
                "telegram_chat_id": "chat_456",
                "discord_webhook_url": "https://discord.com/api/webhooks/test",
                "min_score_threshold": 45.0,
                "quiet_hours_enabled": True,
            }
        }
    )
    assert updated.notifications.telegram_bot_token == "token_123"
    assert updated.notifications.telegram_chat_id == "chat_456"
    assert updated.notifications.discord_webhook_url == "https://discord.com/api/webhooks/test"
    assert updated.notifications.min_score_threshold == 45.0
    assert updated.notifications.quiet_hours_enabled is True

    # Reload from disk
    mgr2 = ConfigManager(config_path=cfg_file)
    cfg2 = mgr2.get_config()
    assert cfg2.notifications.telegram_bot_token == "token_123"
    assert cfg2.notifications.min_score_threshold == 45.0


@pytest.mark.asyncio
async def test_telegram_test_message():
    tg = TelegramNotifier(bot_token="test_token", chat_id="12345")
    mock_client = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_client.post.return_value = mock_resp

    ok = await tg.send_test_message(client=mock_client)
    assert ok is True
    assert tg.last_error is None
    assert mock_client.post.called
    call_args = mock_client.post.call_args
    assert "https://api.telegram.org/bottest_token/sendMessage" in call_args[0][0]


@pytest.mark.asyncio
async def test_telegram_cycle_summary():
    tg = TelegramNotifier(bot_token="test_token", chat_id="12345")
    mock_client = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_client.post.return_value = mock_resp

    summary = {
        "total_scraped": 42,
        "new_listings": 5,
        "price_changes": 2,
        "qualified": 3,
        "notified": 3,
        "llm_successes": 3,
        "llm_calls": 3,
    }
    ok = await tg.send_cycle_summary(summary, elapsed_seconds=65.2, profile_name="Domy Rzeszów", client=mock_client)
    assert ok is True
    assert mock_client.post.called
    payload = mock_client.post.call_args[1]["json"]
    assert "Domy Rzeszów" in payload["text"]
    assert "1m 5s" in payload["text"]
    assert "42" in payload["text"]


@pytest.mark.asyncio
async def test_telegram_price_drop():
    tg = TelegramNotifier(bot_token="test_token", chat_id="12345")
    mock_client = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 200
    mock_client.post.return_value = mock_resp

    listing = _sample_listing()
    ok = await tg.send_price_drop(listing, old_price=900_000, new_price=850_000, client=mock_client)
    assert ok is True
    payload = mock_client.post.call_args[1]["json"]
    assert "OBNIŻKA CENY" in payload["text"]
    assert "850 000 zł" in payload["text"]


@pytest.mark.asyncio
async def test_discord_cycle_summary():
    dc = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
    mock_client = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 204
    mock_client.post.return_value = mock_resp

    summary = {
        "total_scraped": 100,
        "new_listings": 10,
        "price_changes": 4,
        "qualified": 2,
        "notified": 2,
        "llm_successes": 2,
        "llm_calls": 2,
    }
    ok = await dc.send_cycle_summary(summary, elapsed_seconds=45.0, client=mock_client)
    assert ok is True
    payload = mock_client.post.call_args[1]["json"]
    assert "embeds" in payload
    embed = payload["embeds"][0]
    assert "Podsumowanie cyklu scrapingu" in embed["title"]


@pytest.mark.asyncio
async def test_discord_price_drop():
    dc = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
    mock_client = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 204
    mock_client.post.return_value = mock_resp

    listing = _sample_listing()
    ok = await dc.send_price_drop(listing, old_price=1_000_000, new_price=950_000, client=mock_client)
    assert ok is True
    payload = mock_client.post.call_args[1]["json"]
    embed = payload["embeds"][0]
    assert "OBNIŻKA CENY" in embed["title"]
    assert any("50 000 zł" in f["value"] for f in embed["fields"])


@pytest.mark.asyncio
async def test_discord_system_alert():
    dc = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/test")
    mock_client = AsyncMock()
    mock_resp = AsyncMock()
    mock_resp.status_code = 204
    mock_client.post.return_value = mock_resp

    ok = await dc.send_system_alert(
        "Blokada IP", "Otrzymano kod 403 z portalu Otodom", level="error", client=mock_client
    )
    assert ok is True
    payload = mock_client.post.call_args[1]["json"]
    embed = payload["embeds"][0]
    assert "Alert systemowy: Blokada IP" in embed["title"]


def test_pipeline_should_notify_filters():
    # 1. Unqualified
    assert _should_notify(is_qualified=False, is_new=True, price_changed=False, score=90.0) is False

    # 2. Neither new nor price changed
    assert _should_notify(is_qualified=True, is_new=False, price_changed=False, score=90.0) is False

    # 3. Normal qualified & new with defaults -> True
    assert _should_notify(is_qualified=True, is_new=True, price_changed=False, score=90.0) is True

    # 4. Filter by min_score_threshold
    with patch("src.services.config_manager.config_manager.get_config") as mock_cfg:
        mock_cfg.return_value = SearchConfig(notifications=NotificationSettings(min_score_threshold=75.0))
        assert _should_notify(is_qualified=True, is_new=True, price_changed=False, score=60.0) is False
        assert _should_notify(is_qualified=True, is_new=True, price_changed=False, score=80.0) is True

    # 5. Master toggle disabled
    with patch("src.services.config_manager.config_manager.get_config") as mock_cfg:
        mock_cfg.return_value = SearchConfig(notifications=NotificationSettings(enabled=False))
        assert _should_notify(is_qualified=True, is_new=True, price_changed=False, score=95.0) is False

    # 6. Price drop notification disabled
    with patch("src.services.config_manager.config_manager.get_config") as mock_cfg:
        mock_cfg.return_value = SearchConfig(notifications=NotificationSettings(notify_on_price_drop=False))
        assert _should_notify(is_qualified=True, is_new=False, price_changed=True, score=95.0) is False
        assert _should_notify(is_qualified=True, is_new=True, price_changed=False, score=95.0) is True


@pytest.mark.asyncio
async def test_api_notifications_test_endpoint():
    from aiohttp.test_utils import TestClient, TestServer

    from src.services.live_dashboard import LiveDashboardServer

    server = LiveDashboardServer()
    async with TestClient(TestServer(server.app)) as client:
        # 1. Missing credentials
        resp = await client.post(
            "/api/notifications/test",
            json={"channel": "telegram", "telegram_bot_token": "", "telegram_chat_id": ""},
        )
        assert resp.status == 200
        data = await resp.json()
        assert data["success"] is False
        assert data["results"]["telegram"]["ok"] is False

        # 2. Mocked Telegram test
        with patch(
            "src.services.telegram_notifier.TelegramNotifier.send_test_message", new_callable=AsyncMock
        ) as mock_tg:
            mock_tg.return_value = True
            resp2 = await client.post(
                "/api/notifications/test",
                json={"channel": "telegram", "telegram_bot_token": "valid_token", "telegram_chat_id": "12345"},
            )
            assert resp2.status == 200
            data2 = await resp2.json()
            assert data2["success"] is True
            assert data2["results"]["telegram"]["ok"] is True

        # 3. Mocked Discord test
        with patch(
            "src.services.discord_notifier.DiscordNotifier.send_test_message", new_callable=AsyncMock
        ) as mock_dc:
            mock_dc.return_value = True
            resp3 = await client.post(
                "/api/notifications/test",
                json={"channel": "discord", "discord_webhook_url": "https://discord.com/api/webhooks/test"},
            )
            assert resp3.status == 200
            data3 = await resp3.json()
            assert data3["success"] is True
            assert data3["results"]["discord"]["ok"] is True
