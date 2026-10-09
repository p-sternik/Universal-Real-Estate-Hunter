from src.services.config_manager import SchedulerSettings


def test_scheduler_settings_defaults():
    sched = SchedulerSettings()
    assert sched.interval_minutes == 20
    assert sched.night_mode is True
    assert sched.night_interval_minutes == 60
    assert sched.quiet_hours_start == "22:00"
    assert sched.quiet_hours_end == "07:00"
    assert sched.get_current_interval_minutes() in (20, 60)


def test_scheduler_settings_night_mode_off():
    sched = SchedulerSettings(interval_minutes=15, night_mode=False)
    assert sched.get_current_interval_minutes() == 15


def test_scheduler_enabled_defaults_on():
    sched = SchedulerSettings()
    assert sched.enabled is True


def test_scheduler_long_intervals_accepted():
    sched = SchedulerSettings(interval_minutes=1440, night_interval_minutes=720)
    assert sched.get_current_interval_minutes() in (1440, 720)


def test_scheduler_runner_disabled_runs_no_cycles(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from src.scheduler.runner import SchedulerRunner

    runner = SchedulerRunner(idle_poll_seconds=0.01)
    runner.pipeline.run_cycle = AsyncMock()
    monkeypatch.setattr(runner, "is_enabled", lambda: False)

    # Signal stop so idle loop terminates immediately
    runner.stop()
    asyncio.run(runner.start())
    runner.pipeline.run_cycle.assert_not_awaited()
    assert runner.running is False


def test_scheduler_runner_disabled_resumes_when_enabled(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from src.scheduler.runner import SchedulerRunner

    runner = SchedulerRunner(idle_poll_seconds=0.01)
    runner.pipeline.run_cycle = AsyncMock(side_effect=lambda **kw: runner.stop())

    states = [False, True]

    def mock_enabled():
        if states:
            return states.pop(0)
        return True

    monkeypatch.setattr(runner, "is_enabled", mock_enabled)
    asyncio.run(runner.start())
    runner.pipeline.run_cycle.assert_awaited_once()
    assert runner.running is False


def test_scheduler_runner_cli_interval_overrides_disabled_switch(monkeypatch):
    from src.scheduler.runner import SchedulerRunner
    from src.services.config_manager import SchedulerSettings, SearchConfig, config_manager

    runner = SchedulerRunner(interval_minutes=30)
    monkeypatch.setattr(config_manager, "get_config", lambda: SearchConfig(scheduler=SchedulerSettings(enabled=False)))
    assert runner.is_enabled() is True


def test_config_manager_reloads_when_file_modified_on_disk(tmp_path):
    import json
    import os
    import time

    from src.services.config_manager import ConfigManager

    cfg_file = tmp_path / "search_config.json"
    cm = ConfigManager(config_path=cfg_file)
    cfg1 = cm.get_config()
    assert cfg1.scheduler.interval_minutes == 20

    # Simulate another process updating search_config.json on disk (e.g. from Web UI)
    data = cfg1.model_dump()
    data["scheduler"]["interval_minutes"] = 360
    data["scheduler"]["night_mode"] = False
    with cfg_file.open("w", encoding="utf-8") as f:
        json.dump(data, f)
    # Ensure mtime is strictly greater
    future_time = time.time() + 2.0
    os.utime(cfg_file, (future_time, future_time))

    cfg2 = cm.get_config()
    assert cfg2.scheduler.interval_minutes == 360
    assert cfg2.scheduler.night_mode is False


def test_config_manager_preserves_malformed_file(tmp_path):
    from src.services.config_manager import ConfigManager

    cfg_file = tmp_path / "search_config.json"
    cfg_file.write_text("{partially-written", encoding="utf-8")
    manager = ConfigManager(config_path=cfg_file)

    assert cfg_file.read_text(encoding="utf-8") == "{partially-written"
    assert manager.get_config().profiles


def test_scheduler_heartbeat_lifecycle(tmp_path, monkeypatch):
    import src.scheduler.runner as runner_module

    fake_hb = tmp_path / ".scheduler_heartbeat.json"
    monkeypatch.setattr(runner_module, "get_heartbeat_path", lambda: fake_hb)

    assert runner_module.is_scheduler_active() is False

    runner_module.write_heartbeat(status="waiting", interval_minutes=360)
    assert fake_hb.exists()
    assert runner_module.is_scheduler_active() is True
    assert runner_module.get_scheduler_heartbeat()["status"] == "waiting"

    runner_module.write_heartbeat(status="stopped", interval_minutes=360)
    assert runner_module.is_scheduler_active() is False
    assert runner_module.get_scheduler_heartbeat()["status"] == "stopped"


def test_scheduler_heartbeat_uses_shared_config_volume_for_postgres(tmp_path, monkeypatch):
    from config import settings
    from src.scheduler.runner import get_heartbeat_path
    from src.services.config_manager import config_manager

    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://user:pass@db/example")
    monkeypatch.setattr(config_manager, "config_path", tmp_path / "shared" / "search_config.json")

    assert get_heartbeat_path() == (tmp_path / "shared" / ".scheduler_heartbeat.json").resolve()


def test_scheduler_heartbeat_reports_stale_and_future_timestamps(tmp_path, monkeypatch):
    import json
    import time

    import src.scheduler.runner as runner_module

    heartbeat = tmp_path / ".scheduler_heartbeat.json"
    monkeypatch.setattr(runner_module, "get_heartbeat_path", lambda: heartbeat)
    heartbeat.write_text(json.dumps({"status": "waiting", "time_epoch": time.time() - 120}), encoding="utf-8")
    assert runner_module.get_scheduler_heartbeat()["status"] == "stale"
    assert runner_module.is_scheduler_active() is False

    heartbeat.write_text(json.dumps({"status": "waiting", "time_epoch": time.time() + 120}), encoding="utf-8")
    assert runner_module.get_scheduler_heartbeat()["status"] == "offline"
    assert runner_module.is_scheduler_active() is False


def test_live_dashboard_with_scheduler_flag():
    from src.services.live_dashboard import LiveDashboardServer

    srv = LiveDashboardServer(port=8999, with_scheduler=True)
    assert srv.with_scheduler is True
    assert srv._scheduler_runner is None


def test_scheduler_runner_dynamic_interval_adaptation(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    from src.scheduler.runner import SchedulerRunner

    runner = SchedulerRunner(idle_poll_seconds=0.01)
    call_count = 0

    async def mock_cycle(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            runner.stop()

    runner.pipeline.run_cycle = AsyncMock(side_effect=mock_cycle)

    # First returns 360m, then switches to a tiny interval to trigger next cycle fast
    intervals = [360, 360, 0, 0]

    def mock_interval():
        if intervals:
            return intervals.pop(0)
        return 0

    monkeypatch.setattr(runner, "get_effective_interval", mock_interval)
    asyncio.run(runner.start())

    assert call_count == 2
    assert runner.running is False
