import re
from datetime import datetime, timezone
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from constants import Machines, Encoders, WasherLoad, DryerTime, SG_TZ
from exceptions import InvalidMachineError, InvalidCallbackDataError

SG_ZONE = ZoneInfo(SG_TZ)

# Telegram usernames: 5-32 chars of letters, digits and underscores
_USERNAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_CYCLE_SEPARATOR = "__"


def get_display_label(text: str) -> str:
    return text.capitalize().replace('_', ' ')


def assert_valid_machine(machine) -> Machines:
    try:
        return Machines(machine)
    except ValueError:
        raise InvalidMachineError(machine)


def is_machine(machine) -> bool:
    try:
        assert_valid_machine(machine)
        return True
    except InvalidMachineError:
        return False


def is_washer(machine: str) -> bool:
    return machine in Machines.get_washers()


def is_dryer(machine: str) -> bool:
    return machine in Machines.get_dryers()


# ---------------------------------------------------------------------------
# Callback data
# ---------------------------------------------------------------------------

def _machines_alternation() -> str:
    return "|".join(re.escape(machine) for machine in Machines.get_values())


def machine_pattern() -> str:
    """Pattern matching exactly a bare machine name (used by the /use keyboard)."""
    return f"^(?:{_machines_alternation()})\\Z"


def callback_pattern(encoder: Encoders) -> str:
    """Pattern matching `<encoder><machine>` exactly."""
    return f"^{re.escape(encoder.value)}(?:{_machines_alternation()})\\Z"


def cycle_callback_pattern(encoder: Encoders) -> str:
    """Pattern matching `<encoder><machine>__<OPTION>`."""
    return f"^{re.escape(encoder.value)}(?:{_machines_alternation()}){_CYCLE_SEPARATOR}[A-Z]+\\Z"


def encode_machine(machine: str, encoder: Encoders) -> str:
    return f"{encoder.value}{machine}"


def decode_machine(encoded_machine: str, encoder: Encoders) -> str:
    if not isinstance(encoded_machine, str) or not encoded_machine.startswith(encoder.value):
        raise InvalidCallbackDataError(encoded_machine)
    machine = encoded_machine.removeprefix(encoder.value)
    if not is_machine(machine):
        raise InvalidCallbackDataError(encoded_machine)
    return machine


def encode_cycle(machine: str, option: str, encoder: Encoders) -> str:
    return encode_machine(f"{machine}{_CYCLE_SEPARATOR}{option}", encoder)


def decode_cycle(encoded: str, encoder: Encoders) -> Tuple[str, int]:
    """Decode `<encoder><machine>__<OPTION>` into (machine, cycle minutes)."""
    if not isinstance(encoded, str) or not encoded.startswith(encoder.value):
        raise InvalidCallbackDataError(encoded)
    parts = encoded.removeprefix(encoder.value).split(_CYCLE_SEPARATOR)
    if len(parts) != 2:
        raise InvalidCallbackDataError(encoded)
    machine, option = parts
    if is_washer(machine):
        options = WasherLoad
    elif is_dryer(machine):
        options = DryerTime
    else:
        raise InvalidCallbackDataError(encoded)
    try:
        return machine, options[option].value
    except KeyError:
        raise InvalidCallbackDataError(encoded)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def user_display_name(user) -> str:
    """Name stored in the DB: the Telegram username, else the first name."""
    return user.username or user.first_name or str(user.id)


def format_user(name) -> str:
    """Render a stored name for display; only real usernames get an @ prefix."""
    if not name:
        return "unknown user"
    name = str(name)
    return f"@{name}" if _USERNAME_RE.match(name) else name


def same_user(stored_user_id, user_id) -> bool:
    """Compare a stored user_id (int or str in the DB) against a Telegram id."""
    if stored_user_id is None or stored_user_id == "" or user_id is None:
        return False
    return str(stored_user_id) == str(user_id)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse_timestamp(value) -> Optional[datetime]:
    """Parse a stored ISO timestamp into an aware UTC datetime.

    Legacy values were written with a naive `datetime.now()` on a UTC server,
    so naive values are interpreted as UTC. Returns None if unparseable.
    """
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_sg(dt: datetime) -> datetime:
    return dt.astimezone(SG_ZONE)
