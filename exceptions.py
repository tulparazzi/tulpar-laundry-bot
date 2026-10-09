class InvalidMachineError(Exception):
    def __init__(self, machine):
        self.message = f"{machine!r} is not a valid machine"
        super().__init__(self.message)


class InvalidCallbackDataError(Exception):
    def __init__(self, data):
        self.message = f"{data!r} is not valid callback data"
        super().__init__(self.message)


class MachineInUseError(Exception):
    """Raised when claiming a machine that someone else is using (without override)."""

    def __init__(self, machine):
        self.machine = machine
        super().__init__(f"{machine} is currently in use")


class NotOwnerError(Exception):
    """Raised when a user tries to release a machine they are not using."""

    def __init__(self, machine):
        self.machine = machine
        super().__init__(f"{machine} is not being used by this user")


class InvalidStatusError(Exception):
    """Raised when a machine is not in the status required by an action."""

    def __init__(self, machine, status):
        self.machine = machine
        self.status = status
        super().__init__(f"{machine} has unexpected status {status!r}")
