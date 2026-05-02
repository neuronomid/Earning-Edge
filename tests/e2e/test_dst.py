from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from freezegun import freeze_time

from app.scheduler.scheduler import build_cron_trigger


@freeze_time("2026-05-04 14:29:00+00:00")
def test_default_montreal_schedule_maps_to_monday_1030() -> None:
    trigger = build_cron_trigger("monday", "10:30", "America/Toronto")

    next_fire = trigger.get_next_fire_time(None, datetime.now(UTC))

    assert next_fire == datetime(2026, 5, 4, 10, 30, tzinfo=ZoneInfo("America/Toronto"))
    assert next_fire.astimezone(UTC) == datetime(2026, 5, 4, 14, 30, tzinfo=UTC)


@freeze_time("2026-03-01 05:00:00+00:00")
def test_spring_forward_transition_fires_exactly_once() -> None:
    zone = ZoneInfo("America/Toronto")
    trigger = build_cron_trigger("sunday", "02:30", "America/Toronto")

    first = trigger.get_next_fire_time(None, datetime.now(UTC).astimezone(zone))
    assert first is not None

    second = trigger.get_next_fire_time(first, first)
    third = trigger.get_next_fire_time(second, second) if second is not None else None

    assert first.astimezone(UTC) == datetime(2026, 3, 1, 7, 30, tzinfo=UTC)
    assert second is not None
    assert second.astimezone(UTC) == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert third is not None
    assert third.astimezone(UTC) == datetime(2026, 3, 15, 6, 30, tzinfo=UTC)
