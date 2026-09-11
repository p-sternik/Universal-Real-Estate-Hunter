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
