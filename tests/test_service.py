from datetime import datetime, timedelta, timezone

import pytest

import service
from conftest import AVAILABLE, done, in_use
from constants import Status
from exceptions import InvalidStatusError, MachineInUseError, NotOwnerError

NOW = datetime(2026, 10, 9, 10, 10, tzinfo=timezone.utc)


# --- ownership checks on done / cancel -------------------------------------

def test_done_by_owner_sets_available(fake_db):
    fake_db.machines["washer_1"] = done(111)
    service.release_machine("washer_1", 111, [Status.DONE])
    assert fake_db.machines["washer_1"]["status"] == "AVAILABLE"
    # Other fields are kept, matching the previous plain status update
    assert fake_db.machines["washer_1"]["user_id"] == 111


def test_done_by_non_owner_rejected(fake_db):
    fake_db.machines["washer_1"] = done(111)
    with pytest.raises(NotOwnerError):
        service.release_machine("washer_1", 222, [Status.DONE])
    assert fake_db.machines["washer_1"]["status"] == "DONE"


def test_done_wrong_status_rejected(fake_db):
    fake_db.machines["washer_1"] = in_use(111)
    with pytest.raises(InvalidStatusError):
        service.release_machine("washer_1", 111, [Status.DONE])
    assert fake_db.machines["washer_1"]["status"] == "IN_USE"


def test_cancel_in_use_by_owner(fake_db):
    fake_db.machines["dryer_2"] = in_use(111)
    service.release_machine("dryer_2", 111, [Status.IN_USE, Status.DONE])
    assert fake_db.machines["dryer_2"]["status"] == "AVAILABLE"


def test_cancel_available_rejected(fake_db):
    fake_db.machines["dryer_2"] = {**AVAILABLE, "user_id": 111}
    with pytest.raises(InvalidStatusError):
        service.release_machine("dryer_2", 111, [Status.IN_USE, Status.DONE])


def test_release_missing_record_or_empty_owner_rejected(fake_db):
    with pytest.raises(NotOwnerError):
        service.release_machine("washer_2", 111, [Status.DONE])
    fake_db.machines["washer_2"] = {**done(111), "user_id": ""}
    with pytest.raises(NotOwnerError):
        service.release_machine("washer_2", 111, [Status.DONE])


def test_owner_match_tolerates_string_user_id(fake_db):
    fake_db.machines["washer_1"] = done("111")
    service.release_machine("washer_1", 111, [Status.DONE])
    assert fake_db.machines["washer_1"]["status"] == "AVAILABLE"


# --- claim transaction -------------------------------------------------------

def test_claim_available(fake_db):
    fake_db.machines["washer_1"] = dict(AVAILABLE)
    result = service.claim_machine("washer_1", 111, "alice_tg", 32, now=NOW)
    record = fake_db.machines["washer_1"]
    assert record == {"status": "IN_USE", "user_id": 111, "user_username": "alice_tg",
                      "start_time": "2026-10-09T10:10:00+00:00", "cycle_time": 32}
    assert result.start_time == record["start_time"]
    assert result.displaced_user_id is None


def test_claim_missing_record_and_done_machine(fake_db):
    service.claim_machine("washer_1", 111, "alice_tg", 30, now=NOW)
    assert fake_db.machines["washer_1"]["status"] == "IN_USE"
    fake_db.machines["washer_2"] = done(222)
    service.claim_machine("washer_2", 111, "alice_tg", 30, now=NOW)
    assert fake_db.machines["washer_2"]["user_id"] == 111


def test_claim_in_use_rejected_without_override(fake_db):
    fake_db.machines["washer_1"] = in_use(222)
    with pytest.raises(MachineInUseError):
        service.claim_machine("washer_1", 111, "alice_tg", 30, now=NOW)
    assert fake_db.machines["washer_1"]["user_id"] == 222


def test_claim_in_use_with_override_reports_displaced(fake_db):
    fake_db.machines["washer_1"] = in_use(222)
    result = service.claim_machine("washer_1", 111, "alice_tg", 30, override=True, now=NOW)
    assert fake_db.machines["washer_1"]["user_id"] == 111
    assert result.displaced_user_id == 222


def test_override_own_machine_does_not_report_displaced(fake_db):
    fake_db.machines["washer_1"] = in_use(111)
    result = service.claim_machine("washer_1", 111, "alice_tg", 30, override=True, now=NOW)
    assert result.displaced_user_id is None


def test_claim_dryer_clears_only_own_done_washers(fake_db):
    fake_db.machines.update({"washer_1": done(111), "washer_2": done(222)})
    result = service.claim_machine("dryer_1", 111, "alice_tg", 45, now=NOW)
    assert result.cleared_washers == ["washer_1"]
    assert fake_db.machines["washer_1"]["status"] == "AVAILABLE"
    assert fake_db.machines["washer_2"]["status"] == "DONE"


# --- username fallback / status message -------------------------------------

def test_status_handles_missing_username_and_bad_data():
    statuses = {
        "washer_1": {"status": "IN_USE", "user_id": 1, "start_time": "2026-10-09T10:00:00+00:00", "cycle_time": 30},
        "washer_2": {"status": "BROKEN"},
        "dryer_1": "garbage",
        # dryer_2 missing entirely
    }
    message = service.build_status_message(statuses, now=NOW)
    assert "Washer 1:</b> ❌ In Use (20 mins - unknown user)" in message
    assert "Washer 2:</b> ❗️ Error" in message
    assert "Dryer 1:</b> ❗️ Error" in message
    assert "Dryer 2:</b> ❗️ Error" in message


def test_status_none_statuses():
    assert service.build_status_message(None).count("Error") == 4


def test_status_escapes_html_and_formats_names():
    statuses = {
        "washer_1": in_use(1, username="<b>Eve</b>"),
        "washer_2": in_use(2, username="alice_tg"),
        "dryer_1": in_use(3, username="Bob Tan"),
    }
    message = service.build_status_message(statuses, now=NOW)
    assert "&lt;b&gt;Eve&lt;/b&gt;" in message and "<b>Eve" not in message
    assert "@alice_tg" in message
    assert "- Bob Tan)" in message


def test_status_done_shows_singapore_time_for_legacy_naive_timestamp():
    statuses = {"washer_1": done(1, start_time="2026-10-09T10:00:00.123456")}
    # 10:00 UTC + 30 min = 18:30 in Singapore
    assert "09/10/26 06:30PM - @bob_tg" in service.build_status_message(statuses, now=NOW)


def test_status_in_use_with_bad_start_time():
    statuses = {"washer_1": in_use(1, start_time="not a date")}
    assert "In Use (@bob_tg)" in service.build_status_message(statuses, now=NOW)


def test_filter_machines_handles_bad_data():
    statuses = {"washer_1": done(111), "washer_2": {"status": None}, "dryer_1": None, "dryer_2": done(222)}
    assert [m["value"] for m in service.filter_machines(statuses, [Status.DONE])] == ["dryer_2", "washer_1"]
    assert [m["value"] for m in service.filter_machines(statuses, [Status.DONE], 111)] == ["washer_1"]
    assert service.filter_machines(None, [Status.DONE]) == []


# --- stale alarms ------------------------------------------------------------

def test_alarm_for_current_session_marks_done(fake_db):
    fake_db.machines["washer_1"] = in_use(111, start_time="2026-10-09T10:00:00+00:00")
    assert service.mark_done_if_current("washer_1", 111, "2026-10-09T10:00:00+00:00")
    assert fake_db.machines["washer_1"]["status"] == "DONE"


def test_stale_alarm_ignored(fake_db):
    fake_db.machines["washer_1"] = in_use(111, start_time="2026-10-09T10:05:00+00:00")
    assert not service.mark_done_if_current("washer_1", 111, "2026-10-09T10:00:00+00:00")
    assert fake_db.machines["washer_1"]["status"] == "IN_USE"
    # Different owner or not in use
    assert not service.mark_done_if_current("washer_1", 222, "2026-10-09T10:05:00+00:00")
    fake_db.machines["washer_2"] = {**AVAILABLE}
    assert not service.mark_done_if_current("washer_2", 111, AVAILABLE["start_time"])


# --- startup rescheduling ---------------------------------------------------

def test_compute_reschedule_future_and_past_due():
    statuses = {
        "washer_1": in_use(111, start_time="2026-10-09T10:00:00+00:00", cycle_time=30),  # due 10:30
        "washer_2": in_use(222, start_time="2026-10-09T09:00:00", cycle_time=30),  # legacy naive, past due
        "dryer_1": done(333),
        "dryer_2": in_use("", start_time="2026-10-09T10:00:00+00:00"),  # no owner: skipped
    }
    jobs = {job["machine"]: job for job in service.compute_reschedule(statuses, now=NOW)}
    assert set(jobs) == {"washer_1", "washer_2"}
    assert jobs["washer_1"]["delay"] == pytest.approx(timedelta(minutes=20).total_seconds())
    assert jobs["washer_1"]["user_id"] == 111
    assert jobs["washer_1"]["start_time"] == "2026-10-09T10:00:00+00:00"
    assert jobs["washer_2"]["delay"] == 0
    assert jobs["washer_2"]["start_time"] == "2026-10-09T09:00:00"


def test_compute_reschedule_handles_none_and_missing_cycle_time():
    assert service.compute_reschedule(None, now=NOW) == []
    record = in_use(111, start_time="2026-10-09T10:00:00+00:00")
    del record["cycle_time"]
    [job] = service.compute_reschedule({"washer_1": record}, now=NOW)
    assert job["delay"] == pytest.approx(20 * 60)  # default 30 min cycle
