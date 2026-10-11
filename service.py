import html
import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Iterable, List, Optional

import db
import utils
from constants import (Machines, Status, STATUS, USER_ID, USER_USERNAME, START_TIME, CYCLE_TIME, DEFAULT_CYCLE_TIME,
                       OVERDUE_GRACE)
from exceptions import MachineInUseError, NotOwnerError, InvalidStatusError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers for reading possibly-malformed machine records
# ---------------------------------------------------------------------------

def parse_status(record) -> Optional[Status]:
    if not isinstance(record, dict):
        return None
    try:
        return Status(record.get(STATUS))
    except ValueError:
        return None


def parse_cycle_time(record) -> int:
    value = record.get(CYCLE_TIME) if isinstance(record, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return DEFAULT_CYCLE_TIME
    return int(value)


def end_time(record) -> Optional[datetime]:
    start = utils.parse_timestamp(record.get(START_TIME)) if isinstance(record, dict) else None
    if start is None:
        return None
    return start + timedelta(minutes=parse_cycle_time(record))


# ---------------------------------------------------------------------------
# Status / keyboards
# ---------------------------------------------------------------------------

def build_status_message(statuses: Dict, now: Optional[datetime] = None) -> str:
    now = now or utils.now_utc()
    statuses = statuses if isinstance(statuses, dict) else {}
    lines = []
    for machine in Machines.get_values():
        record = statuses.get(machine)
        label = f"<b>{html.escape(utils.get_display_label(machine))}:</b>"
        status = parse_status(record)
        if status is None:
            lines.append(f"{label} ❗️ Error (Status Unknown)")
            continue
        if status == Status.AVAILABLE:
            lines.append(f"{label} ✅ Available")
            continue

        user = html.escape(utils.format_user(record.get(USER_USERNAME)))
        finish = end_time(record)
        if status == Status.IN_USE:
            if finish is None:
                lines.append(f"{label} ❌ In Use ({user})")
            else:
                time_left = max(0, math.ceil((finish - now).total_seconds() / 60))
                mins = "min" if time_left == 1 else "mins"
                lines.append(f"{label} ❌ In Use ({time_left} {mins} - {user})")
        elif status == Status.DONE:
            if finish is None:
                lines.append(f"{label} ⏱️ Done ({user})")
            else:
                ended = utils.to_sg(finish).strftime('%d/%m/%y %I:%M%p')
                lines.append(f"{label} ⏱️ Done ({ended} - {user})")
    return "\n".join(lines) + "\n"


def get_status() -> str:
    return build_status_message(db.get_statuses())


def get_machines() -> List[Dict[str, str]]:
    return [{"label": utils.get_display_label(machine), "value": machine} for machine in Machines.get_values()]


def filter_machines(statuses: Dict, wanted: Iterable[Status], user_id=None) -> List[Dict[str, str]]:
    statuses = statuses if isinstance(statuses, dict) else {}
    wanted = set(wanted)
    options = []
    for machine in Machines.get_values():
        record = statuses.get(machine)
        if parse_status(record) not in wanted:
            continue
        if user_id is not None and not utils.same_user(record.get(USER_ID), user_id):
            continue
        options.append({"label": utils.get_display_label(machine), "value": machine})
    return options


def get_machines_with_options(wanted: Iterable[Status], user_id=None) -> List[Dict[str, str]]:
    return filter_machines(db.get_statuses(), wanted, user_id)


def get_user_id(machine):
    utils.assert_valid_machine(machine)
    return db.get_user_id(machine)


def is_machine_in_use(machine) -> bool:
    utils.assert_valid_machine(machine)
    return parse_status(db.get_machine(machine)) == Status.IN_USE


# ---------------------------------------------------------------------------
# Claiming a machine
# ---------------------------------------------------------------------------

@dataclass
class ClaimResult:
    machine: str
    start_time: str
    # Set when an explicit override displaced another user's running cycle
    displaced_user_id: Optional[object] = None
    cleared_washers: List[str] = field(default_factory=list)


def apply_claim(current, machine, user_id, username, cycle_time, start_time, override=False):
    """Pure transaction function body for claiming a machine.

    Returns (new_record, displaced_user_id). Raises MachineInUseError when the
    machine is in use and the user did not explicitly choose to override.
    """
    record = dict(current) if isinstance(current, dict) else {}
    displaced = None
    if parse_status(record) == Status.IN_USE:
        if not override:
            raise MachineInUseError(machine)
        if not utils.same_user(record.get(USER_ID), user_id) and record.get(USER_ID) not in (None, ""):
            displaced = record.get(USER_ID)
    record.update({
        STATUS: Status.IN_USE.value,
        USER_ID: user_id,
        USER_USERNAME: username,
        START_TIME: start_time,
        CYCLE_TIME: cycle_time,
    })
    return record, displaced


def claim_machine(machine, user_id, username, cycle_time, override=False, now=None) -> ClaimResult:
    utils.assert_valid_machine(machine)
    start_time = utils.to_iso(now or utils.now_utc())
    outcome = {}

    def txn(current):
        record, displaced = apply_claim(current, machine, user_id, username, cycle_time, start_time, override)
        outcome["displaced"] = displaced
        return record

    db.transact_machine(machine, txn)
    result = ClaimResult(machine=machine, start_time=start_time, displaced_user_id=outcome.get("displaced"))

    # Using a dryer means the user has collected their washing: release their DONE washers.
    if utils.is_dryer(machine):
        statuses = db.get_statuses()
        own_done_washers = [option["value"] for option in filter_machines(statuses, [Status.DONE], user_id)
                            if utils.is_washer(option["value"])]
        for washer in own_done_washers:
            try:
                release_machine(washer, user_id, [Status.DONE])
                result.cleared_washers.append(washer)
            except (NotOwnerError, InvalidStatusError):
                pass
    return result


# ---------------------------------------------------------------------------
# Releasing a machine (/done, /cancel)
# ---------------------------------------------------------------------------

def apply_release(current, machine, user_id, expected: Iterable[Status]):
    """Pure transaction function body: set AVAILABLE if user owns it and status is expected."""
    if not isinstance(current, dict) or not utils.same_user(current.get(USER_ID), user_id):
        raise NotOwnerError(machine)
    status = parse_status(current)
    if status not in set(expected):
        raise InvalidStatusError(machine, current.get(STATUS))
    record = dict(current)
    record[STATUS] = Status.AVAILABLE.value
    return record


def release_machine(machine, user_id, expected: Iterable[Status]):
    utils.assert_valid_machine(machine)
    expected = list(expected)
    db.transact_machine(machine, lambda current: apply_release(current, machine, user_id, expected))


# ---------------------------------------------------------------------------
# Alarms
# ---------------------------------------------------------------------------

class _StaleSession(Exception):
    pass


def apply_mark_done(current, user_id, start_time):
    """Pure transaction function body: IN_USE -> DONE only for the same session."""
    if (
        not isinstance(current, dict)
        or parse_status(current) != Status.IN_USE
        or not utils.same_user(current.get(USER_ID), user_id)
        or current.get(START_TIME) != start_time
    ):
        raise _StaleSession()
    record = dict(current)
    record[STATUS] = Status.DONE.value
    return record


def mark_done_if_current(machine, user_id, start_time) -> bool:
    """Mark a machine DONE if it is still the session identified by (user_id, start_time)."""
    utils.assert_valid_machine(machine)
    try:
        db.transact_machine(machine, lambda current: apply_mark_done(current, user_id, start_time))
        return True
    except _StaleSession:
        return False


def find_overdue(statuses: Dict, now: Optional[datetime] = None, grace_seconds: float = OVERDUE_GRACE) -> List[Dict]:
    """IN_USE machines whose cycle ended more than grace_seconds ago, i.e. whose alarm was lost."""
    now = now or utils.now_utc()
    statuses = statuses if isinstance(statuses, dict) else {}
    overdue = []
    for machine in Machines.get_values():
        record = statuses.get(machine)
        if parse_status(record) != Status.IN_USE:
            continue
        user_id = record.get(USER_ID)
        finish = end_time(record)
        if user_id in (None, "") or finish is None:
            continue
        if (now - finish).total_seconds() > grace_seconds:
            overdue.append({"machine": machine, "user_id": user_id, "start_time": record.get(START_TIME)})
    return overdue


def compute_reschedule(statuses: Dict, now: Optional[datetime] = None) -> List[Dict]:
    """Alarms to restore on startup: one per IN_USE machine, delay 0 if past due."""
    now = now or utils.now_utc()
    statuses = statuses if isinstance(statuses, dict) else {}
    jobs = []
    for machine in Machines.get_values():
        record = statuses.get(machine)
        if parse_status(record) != Status.IN_USE:
            continue
        user_id = record.get(USER_ID)
        finish = end_time(record)
        if user_id in (None, "") or finish is None:
            logger.warning("Cannot reschedule alarm for %s: missing user_id or start_time", machine)
            continue
        jobs.append({
            "machine": machine,
            "user_id": user_id,
            "start_time": record.get(START_TIME),
            "delay": max(0.0, (finish - now).total_seconds()),
        })
    return jobs
