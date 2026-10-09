import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import Forbidden

import app
import controller
from conftest import AVAILABLE, FakeJobQueue, done, in_use, make_context, make_update, make_user


def run(coro):
    return asyncio.run(coro)


def edited_text(update):
    return update.callback_query.edit_message_text.await_args.kwargs["text"]


# --- done / cancel ownership ---------------------------------------------------

def test_done_machine_owner(fake_db):
    fake_db.machines["washer_1"] = done(111)
    update, context = make_update("-washer_1", make_user(111)), make_context()
    run(controller.done_machine(update, context))
    update.callback_query.answer.assert_awaited_once()
    assert fake_db.machines["washer_1"]["status"] == "AVAILABLE"
    assert edited_text(update) == "Your laundry in Washer 1 has been cleared!"


def test_done_machine_non_owner_rejected(fake_db):
    fake_db.machines["washer_1"] = done(111)
    update = make_update("-washer_1", make_user(222))
    run(controller.done_machine(update, make_context()))
    assert fake_db.machines["washer_1"]["status"] == "DONE"
    assert edited_text(update) == "You are not using Washer 1!"


def test_done_machine_wrong_status_rejected(fake_db):
    fake_db.machines["washer_1"] = in_use(111)
    update = make_update("-washer_1", make_user(111))
    run(controller.done_machine(update, make_context()))
    assert fake_db.machines["washer_1"]["status"] == "IN_USE"
    assert edited_text(update) == "Washer 1 is not done yet!"


def test_cancel_machine_owner_removes_alarm(fake_db):
    fake_db.machines["dryer_1"] = in_use(111)
    context = make_context()
    controller.schedule_alarm(context.job_queue, "dryer_1", 111, 111, "x", 60)
    update = make_update("=dryer_1", make_user(111))
    run(controller.cancel_machine(update, context))
    assert fake_db.machines["dryer_1"]["status"] == "AVAILABLE"
    assert context.job_queue.active() == []


def test_cancel_machine_non_owner_rejected(fake_db):
    fake_db.machines["dryer_1"] = in_use(111)
    context = make_context()
    controller.schedule_alarm(context.job_queue, "dryer_1", 111, 111, "x", 60)
    update = make_update("=dryer_1", make_user(222))
    run(controller.cancel_machine(update, context))
    assert fake_db.machines["dryer_1"]["status"] == "IN_USE"
    assert len(context.job_queue.active()) == 1
    assert edited_text(update) == "You are not using Dryer 1!"


# --- claim flow --------------------------------------------------------------

def test_set_duration_claims_and_schedules_alarm(fake_db):
    fake_db.machines["washer_1"] = dict(AVAILABLE)
    update, context = make_update("@washer_1__MEDIUM", make_user(111), chat_id=-500), make_context()
    run(controller.set_duration(update, context))
    record = fake_db.machines["washer_1"]
    assert record["status"] == "IN_USE" and record["user_id"] == 111 and record["cycle_time"] == 32
    [job] = context.job_queue.active()
    assert job.name == "alarm:washer_1" and job.when == 32 * 60
    assert job.data == {"machine": "washer_1", "user_id": 111, "chat_id": -500, "start_time": record["start_time"]}
    assert edited_text(update) == "You are now using Washer 1!"


def test_set_duration_in_use_offers_override(fake_db):
    fake_db.machines["washer_1"] = in_use(222)
    update, context = make_update("@washer_1__LIGHT", make_user(111)), make_context()
    run(controller.set_duration(update, context))
    assert fake_db.machines["washer_1"]["user_id"] == 222
    assert context.job_queue.active() == []
    assert "override" in edited_text(update)


def test_override_notifies_displaced_user_and_replaces_alarm(fake_db):
    fake_db.machines["washer_1"] = in_use(222)
    context = make_context()
    controller.schedule_alarm(context.job_queue, "washer_1", 222, 222, in_use(222)["start_time"], 60)
    update = make_update("!washer_1__LIGHT", make_user(111))
    run(controller.set_duration(update, context))
    assert fake_db.machines["washer_1"]["user_id"] == 111
    [job] = context.job_queue.active()
    assert job.data["user_id"] == 111
    context.bot.send_message.assert_awaited_once()
    kwargs = context.bot.send_message.await_args.kwargs
    assert kwargs["chat_id"] == 222 and "overridden by @alice_tg" in kwargs["text"]


def test_set_duration_without_username_stores_first_name(fake_db):
    update = make_update("@dryer_1__SHORT", make_user(111, username=None, first_name="Alice"))
    run(controller.set_duration(update, make_context()))
    assert fake_db.machines["dryer_1"]["user_username"] == "Alice"


# --- alarm -------------------------------------------------------------------

def test_stale_alarm_does_not_mark_done_or_notify(fake_db):
    fake_db.machines["washer_1"] = in_use(111, start_time="2026-10-09T11:00:00+00:00")
    job = SimpleNamespace(data={"machine": "washer_1", "user_id": 111, "chat_id": 111,
                                "start_time": "2026-10-09T10:00:00+00:00"})
    context = make_context(job)
    run(controller.alarm(context))
    assert fake_db.machines["washer_1"]["status"] == "IN_USE"
    context.bot.send_message.assert_not_awaited()


def test_current_alarm_marks_done_and_notifies_chat(fake_db):
    fake_db.machines["washer_1"] = in_use(111, start_time="2026-10-09T10:00:00+00:00")
    job = SimpleNamespace(data={"machine": "washer_1", "user_id": 111, "chat_id": -500,
                                "start_time": "2026-10-09T10:00:00+00:00"})
    context = make_context(job)
    run(controller.alarm(context))
    assert fake_db.machines["washer_1"]["status"] == "DONE"
    assert context.bot.send_message.await_args.kwargs["chat_id"] == -500


def test_reschedule_alarms_on_startup(fake_db):
    fake_db.machines.update({
        "washer_1": in_use(111, start_time="2000-01-01T00:00:00"),
        "dryer_1": done(222),
    })
    application = SimpleNamespace(job_queue=FakeJobQueue())
    run(controller.reschedule_alarms(application))
    [job] = application.job_queue.active()
    assert job.name == "alarm:washer_1" and job.when == 0
    assert job.data == {"machine": "washer_1", "user_id": 111, "chat_id": 111, "start_time": "2000-01-01T00:00:00"}


# --- ping ----------------------------------------------------------------------

@pytest.mark.parametrize("record", [{"status": "DONE"}, {"status": "DONE", "user_id": ""}, None])
def test_ping_with_missing_user_id_does_not_crash(fake_db, record):
    if record is not None:
        fake_db.machines["washer_1"] = record
    update, context = make_update("~washer_1"), make_context()
    run(controller.ping_user(update, context))
    context.bot.send_message.assert_not_awaited()
    assert edited_text(update) == "The user could not be notified."


def test_ping_when_user_blocked_bot(fake_db):
    fake_db.machines["washer_1"] = done(111)
    update, context = make_update("~washer_1"), make_context()
    context.bot.send_message = AsyncMock(side_effect=Forbidden("blocked"))
    run(controller.ping_user(update, context))
    assert edited_text(update) == "The user could not be notified."


def test_ping_notifies_user(fake_db):
    fake_db.machines["washer_1"] = done(111)
    update, context = make_update("~washer_1"), make_context()
    run(controller.ping_user(update, context))
    assert context.bot.send_message.await_args.kwargs["chat_id"] == 111
    assert edited_text(update) == "User has been notified!"


# --- misc --------------------------------------------------------------------

def test_status_command_with_empty_db(fake_db):
    update, context = make_update(), make_context()
    run(controller.status(update, context))
    assert "Error" in context.bot.send_message.await_args.kwargs["text"]


def test_handlers_registered_and_patterns_route():
    application = controller.setup_bot("123:TEST")
    from telegram.ext import CallbackQueryHandler
    handlers = [h for h in application.handlers[0] if isinstance(h, CallbackQueryHandler)]

    def route(data):
        for handler in handlers:
            if handler.pattern is None or handler.pattern.match(data):
                return handler.callback
    assert route("washer_1") is controller.use_machine
    assert route("+washer_1") is controller.confirm_use_machine
    assert route("@washer_1__LIGHT") is controller.set_duration
    assert route("!washer_1__LIGHT") is controller.set_duration
    assert route("cancel") is controller.cancel_usage
    assert route("~dryer_2") is controller.ping_user
    assert route("-dryer_2") is controller.done_machine
    assert route("=dryer_2") is controller.cancel_machine
    assert route("-dryer_2x") is controller.unknown_callback
    assert route("xcancel") is controller.unknown_callback
    assert application.error_handlers


def test_error_handler_notifies_chat():
    from datetime import datetime
    from telegram import Chat, Message, Update
    update = Update(1, message=Message(message_id=1, date=datetime.now(), chat=Chat(id=5, type="private")))
    context = SimpleNamespace(error=RuntimeError("boom"), bot=SimpleNamespace(send_message=AsyncMock()))
    run(controller.error_handler(update, context))
    assert context.bot.send_message.await_args.kwargs["chat_id"] == 5
    # Errors without an update (e.g. in jobs) are only logged
    run(controller.error_handler(None, context))
    assert context.bot.send_message.await_count == 1


def test_missing_env(monkeypatch):
    for name in ["TELEGRAM_TOKEN", *app.REQUIRED_ENV]:
        monkeypatch.setenv(name, "x")
    assert app.missing_env() == []
    monkeypatch.delenv("PRIVATE_KEY")
    monkeypatch.setenv("TELEGRAM_TOKEN", "")
    assert app.missing_env() == ["TELEGRAM_TOKEN", "PRIVATE_KEY"]
