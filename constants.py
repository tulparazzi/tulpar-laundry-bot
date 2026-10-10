from enum import Enum

# Database keys under /machines/<machine>/
STATUS = "status"
USER_USERNAME = "user_username"
USER_ID = "user_id"
START_TIME = "start_time"
CYCLE_TIME = "cycle_time"

DEFAULT_CYCLE_TIME = 30

SG_TZ = "Asia/Singapore"

CANCEL_CALLBACK = "cancel"


# Callback data prefixes
class Encoders(Enum):
    CONFIRM_ENCODER = "+"
    PING_ENCODER = "~"
    DONE_ENCODER = "-"
    CLEAR_ENCODER = "="
    CYCLE_ENCODER = "@"
    # Cycle selection after the user explicitly chose to override a machine in use
    OVERRIDE_CYCLE_ENCODER = "!"


# Machines
class Machines(Enum):
    DRYER_1 = "dryer_1"
    DRYER_2 = "dryer_2"
    WASHER_1 = "washer_1"
    WASHER_2 = "washer_2"

    @classmethod
    def get_values(cls):
        return [machine.value for machine in cls]

    @classmethod
    def get_washers(cls):
        return [cls.WASHER_1.value, cls.WASHER_2.value]

    @classmethod
    def get_dryers(cls):
        return [cls.DRYER_1.value, cls.DRYER_2.value]


# Statuses
class Status(Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    DONE = "DONE"


class WasherLoad(Enum):
    LIGHT = 30
    MEDIUM = 32
    HEAVY = 34


class DryerTime(Enum):
    SHORT = 30
    MEDIUM = 45
    LONG = 60
