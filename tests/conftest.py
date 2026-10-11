from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import controller
import service
import utils


class FakeDB:
    """In-memory stand-in for db.py (the /machines node)."""

    def __init__(self, machines=None):
        self.machines = deepcopy(machines or {})

    def get_statuses(self):
        return deepcopy(self.machines)

    def get_machine(self, machine):
        utils.assert_valid_machine(machine)
        value = self.machines.get(machine)
        return deepcopy(value) if isinstance(value, dict) else None

    def get_user_id(self, machine):
        utils.assert_valid_machine(machine)
        return (self.machines.get(machine) or {}).get("user_id")

    def transact_machine(self, machine, update_fn):
        utils.assert_valid_machine(machine)
        new_value = update_fn(deepcopy(self.machines.get(machine)))
        self.machines[machine] = new_value
        return new_value


class FakeJob:
    def __init__(self, callback, when, name, chat_id, data, job_kwargs=None, interval=None):
        self.callback, self.when, self.name, self.chat_id, self.data = callback, when, name, chat_id, data
        self.job_kwargs, self.interval = job_kwargs or {}, interval
        self.removed = False

    def schedule_removal(self):
        self.removed = True


class FakeJobQueue:
    def __init__(self):
        self.jobs = []

    def run_once(self, callback, when, name=None, chat_id=None, data=None, job_kwargs=None, **_):
        job = FakeJob(callback, when, name, chat_id, data, job_kwargs)
        self.jobs.append(job)
        return job

    def run_repeating(self, callback, interval, first=None, name=None, job_kwargs=None, **_):
        job = FakeJob(callback, first, name, None, None, job_kwargs, interval)
        self.jobs.append(job)
        return job

    def get_jobs_by_name(self, name):
        return [job for job in self.jobs if job.name == name and not job.removed]

    def active(self):
        return [job for job in self.jobs if not job.removed]


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(service, "db", fake)
    monkeypatch.setattr(controller, "db", fake)
    return fake


def make_user(user_id=111, username="alice_tg", first_name="Alice"):
    return SimpleNamespace(id=user_id, username=username, first_name=first_name)


def make_update(data=None, user=None, chat_id=None):
    user = user or make_user()
    query = None
    if data is not None:
        query = SimpleNamespace(data=data, answer=AsyncMock(), edit_message_text=AsyncMock())
    return SimpleNamespace(
        callback_query=query,
        effective_user=user,
        effective_chat=SimpleNamespace(id=chat_id if chat_id is not None else user.id),
    )


def make_context(job=None):
    return SimpleNamespace(bot=SimpleNamespace(send_message=AsyncMock()), job_queue=FakeJobQueue(), job=job)


def in_use(user_id, start_time="2026-10-09T10:00:00+00:00", username="bob_tg", cycle_time=30):
    return {"status": "IN_USE", "user_id": user_id, "user_username": username,
            "start_time": start_time, "cycle_time": cycle_time}


def done(user_id, start_time="2026-10-09T10:00:00+00:00", username="bob_tg", cycle_time=30):
    return {**in_use(user_id, start_time, username, cycle_time), "status": "DONE"}


AVAILABLE = {"status": "AVAILABLE", "user_id": "", "user_username": "", "start_time": "2026-10-01T00:00:00"}
