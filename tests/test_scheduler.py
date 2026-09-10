import pytest
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