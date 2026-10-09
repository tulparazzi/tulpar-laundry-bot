import re
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import db
import utils
from constants import Encoders
from exceptions import InvalidCallbackDataError, InvalidMachineError


def test_parse_aware_timestamp():
    dt = utils.parse_timestamp("2026-10-09T18:00:00+08:00")
    assert dt == datetime(2026, 10, 9, 10, 0, tzinfo=timezone.utc)
    assert dt.tzinfo == timezone.utc


def test_parse_legacy_naive_timestamp_as_utc():
    dt = utils.parse_timestamp("2026-10-09T10:00:00.123456")
    assert dt == datetime(2026, 10, 9, 10, 0, 0, 123456, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", [None, "", "garbage", 12345])
def test_parse_invalid_timestamp(value):
    assert utils.parse_timestamp(value) is None


def test_to_iso_round_trip_is_utc():
    s = utils.to_iso(datetime(2026, 10, 9, 18, 0, tzinfo=utils.SG_ZONE))
    assert s == "2026-10-09T10:00:00+00:00"
    assert utils.to_sg(utils.parse_timestamp(s)).hour == 18


def test_decode_machine_uses_prefix_only():
    assert utils.decode_machine("-dryer_1", Encoders.DONE_ENCODER) == "dryer_1"
    assert utils.decode_machine("~washer_2", Encoders.PING_ENCODER) == "washer_2"
    for bad in ["--dryer_1", "-dryer_1-", "dryer_1", "-dryer_9", "~dryer_1", "-"]:
        with pytest.raises(InvalidCallbackDataError):
            utils.decode_machine(bad, Encoders.DONE_ENCODER)


def test_decode_cycle():
    assert utils.decode_cycle("@washer_1__HEAVY", Encoders.CYCLE_ENCODER) == ("washer_1", 34)
    assert utils.decode_cycle("@dryer_2__LONG", Encoders.CYCLE_ENCODER) == ("dryer_2", 60)
    assert utils.decode_cycle("!dryer_1__SHORT", Encoders.OVERRIDE_CYCLE_ENCODER) == ("dryer_1", 30)
    for bad in ["@washer_1__LONG", "@dryer_1__HEAVY", "@washer_1", "@washer_1__LIGHT__X", "@washer_9__LIGHT",
                "@washer_1__light", "washer_1__LIGHT"]:
        with pytest.raises(InvalidCallbackDataError):
            utils.decode_cycle(bad, Encoders.CYCLE_ENCODER)


def test_encode_decode_round_trip():
    data = utils.encode_cycle("washer_2", "MEDIUM", Encoders.CYCLE_ENCODER)
    assert re.match(utils.cycle_callback_pattern(Encoders.CYCLE_ENCODER), data)
    assert utils.decode_cycle(data, Encoders.CYCLE_ENCODER) == ("washer_2", 32)


def test_callback_patterns_are_anchored():
    pattern = utils.callback_pattern(Encoders.DONE_ENCODER)
    assert re.match(pattern, "-washer_1")
    for bad in ["-washer_1x", "x-washer_1", "-washer_3", "-washer_1\n"]:
        assert not re.match(pattern, bad)
    assert re.match(utils.machine_pattern(), "dryer_2")
    assert not re.match(utils.machine_pattern(), "dryer_22")
    assert not re.match(utils.cycle_callback_pattern(Encoders.CYCLE_ENCODER), "@washer_1__LIGHT__X")


def test_db_layer_validates_machine():
    with pytest.raises(InvalidMachineError):
        db.transact_machine("../users", lambda current: current)
    with pytest.raises(InvalidMachineError):
        db.get_user_id("washer_1/user_id")


def test_username_fallback():
    assert utils.user_display_name(SimpleNamespace(id=1, username="alice_tg", first_name="Alice")) == "alice_tg"
    assert utils.user_display_name(SimpleNamespace(id=1, username=None, first_name="Alice")) == "Alice"
    assert utils.user_display_name(SimpleNamespace(id=7, username=None, first_name=None)) == "7"


def test_format_user():
    assert utils.format_user("alice_tg") == "@alice_tg"
    assert utils.format_user("Bob Tan") == "Bob Tan"
    assert utils.format_user(None) == "unknown user"
    assert utils.format_user("") == "unknown user"
