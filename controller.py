import asyncio
import logging

from telegram import CallbackQuery, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder, ContextTypes, CommandHandler, CallbackQueryHandler

import db
import service as svc
import utils
from constants import Encoders, WasherLoad, DryerTime, Status, CANCEL_CALLBACK
from exceptions import MachineInUseError, NotOwnerError, InvalidStatusError

logger = logging.getLogger(__name__)

CANCEL_BUTTON = [InlineKeyboardButton("Cancel", callback_data=CANCEL_CALLBACK)]


# ---------------------------------------------------------------------------
# Alarm jobs
# ---------------------------------------------------------------------------

def alarm_job_name(machine: str) -> str:
    return f"alarm:{machine}"


def remove_alarms(job_queue, machine: str):
    for job in job_queue.get_jobs_by_name(alarm_job_name(machine)):
        job.schedule_removal()


def schedule_alarm(job_queue, machine: str, user_id, chat_id, start_time: str, delay: float):
    """Schedule the end-of-cycle alarm, replacing any previous alarm for the machine."""
    remove_alarms(job_queue, machine)
    job_queue.run_once(
        alarm,
        delay,
        name=alarm_job_name(machine),
        chat_id=chat_id,
        data={"machine": machine, "user_id": user_id, "chat_id": chat_id, "start_time": start_time},
    )


async def alarm(context: ContextTypes.DEFAULT_TYPE):
    data = context.job.data
    machine = data["machine"]
    # Only the session that scheduled this alarm may mark the machine DONE
    if not await asyncio.to_thread(svc.mark_done_if_current, machine, data["user_id"], data["start_time"]):
        logger.info("Ignoring stale alarm for %s", machine)
        return
    try:
        await context.bot.send_message(
            chat_id=data["chat_id"], text=f'Your laundry in {utils.get_display_label(machine)} is done!'
        )
    except TelegramError:
        logger.warning("Could not send done notification for %s", machine, exc_info=True)


async def reschedule_alarms(application: Application):
    """Restore alarms for IN_USE machines after a restart (the job queue is in memory)."""
    try:
        statuses = await asyncio.to_thread(db.get_statuses)
    except Exception:
        logger.exception("Could not read machines to reschedule alarms")
        return
    jobs = svc.compute_reschedule(statuses)
    for job in jobs:
        # The originating chat is not stored in the DB; notify the user privately.
        schedule_alarm(application.job_queue, job["machine"], job["user_id"], job["user_id"],
                       job["start_time"], job["delay"])
    logger.info("Rescheduled %d alarm(s) from the database", len(jobs))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Start")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = await asyncio.to_thread(svc.get_status)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=message, parse_mode="HTML")


async def use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton(machine["label"], callback_data=machine["value"])] for machine in svc.get_machines()]
    keyboard.append(CANCEL_BUTTON)
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Please select a machine:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    machines = await asyncio.to_thread(svc.get_machines_with_options, [Status.DONE])
    if not machines:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="There are no machines that are done!")
        return
    keyboard = [[InlineKeyboardButton(machine["label"], callback_data=utils.encode_machine(machine["value"], Encoders.PING_ENCODER))] for machine in machines]
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Please select a machine to ping user:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Show only machines registered to the user
    machines = await asyncio.to_thread(svc.get_machines_with_options, [Status.DONE], update.effective_user.id)
    if not machines:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="There are no machines used by you that are done!")
        return
    keyboard = [[InlineKeyboardButton(machine["label"], callback_data=utils.encode_machine(machine["value"], Encoders.DONE_ENCODER))] for machine in machines]
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Please select the machine that you are done using:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    machines = await asyncio.to_thread(svc.get_machines_with_options, [Status.IN_USE, Status.DONE], update.effective_user.id)
    if not machines:
        await context.bot.send_message(chat_id=update.effective_chat.id, text="You are not using any machines!")
        return
    keyboard = [[InlineKeyboardButton(machine["label"], callback_data=utils.encode_machine(machine["value"], Encoders.CLEAR_ENCODER))] for machine in machines]
    await context.bot.send_message(
        chat_id=update.effective_chat.id, text="Please select the machine that you want to cancel:", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def refund(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="To request for a refund, please fill in the form here: https://forms.gle/VrghaVuxPmicVu9b9.")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="To seek assistance on any Washer & Dryer related issues, please contact Fresh Laundry Pte Ltd at +65 9655 3600 or @freshlaundrysg on Telegram. Alternatively, you can also contact your nearest RA.")


# ---------------------------------------------------------------------------
# Callback queries: /use flow
# ---------------------------------------------------------------------------

async def show_override_prompt(query: CallbackQuery, machine: str):
    machine_label = utils.get_display_label(machine)
    keyboard = [[InlineKeyboardButton(f"Use {machine_label}", callback_data=utils.encode_machine(machine, Encoders.CONFIRM_ENCODER))], CANCEL_BUTTON]
    await query.edit_message_text(
        text=f"{machine_label} is currently in use, are you sure you want to override?", reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def show_cycle_options(query: CallbackQuery, machine: str, override: bool):
    encoder = Encoders.OVERRIDE_CYCLE_ENCODER if override else Encoders.CYCLE_ENCODER
    if utils.is_washer(machine):
        keyboard = [[InlineKeyboardButton(load.name.capitalize(), callback_data=utils.encode_cycle(machine, load.name, encoder))] for load in WasherLoad]
        text = "Please select the wash cycle:"
    else:
        keyboard = [[InlineKeyboardButton(f"{time.value} Minutes", callback_data=utils.encode_cycle(machine, time.name, encoder))] for time in DryerTime]
        text = "Please select the dryer time:"
    keyboard.append(CANCEL_BUTTON)
    await query.edit_message_text(text=text, reply_markup=InlineKeyboardMarkup(keyboard))


async def use_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    machine = query.data
    utils.assert_valid_machine(machine)
    if await asyncio.to_thread(svc.is_machine_in_use, machine):
        await show_override_prompt(query, machine)
    else:
        await show_cycle_options(query, machine, override=False)


async def confirm_use_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    machine = utils.decode_machine(query.data, Encoders.CONFIRM_ENCODER)
    await show_cycle_options(query, machine, override=True)


async def set_duration(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    override = query.data.startswith(Encoders.OVERRIDE_CYCLE_ENCODER.value)
    encoder = Encoders.OVERRIDE_CYCLE_ENCODER if override else Encoders.CYCLE_ENCODER
    machine, cycle_time = utils.decode_cycle(query.data, encoder)
    user = update.effective_user
    username = utils.user_display_name(user)

    try:
        result = await asyncio.to_thread(svc.claim_machine, machine, user.id, username, cycle_time, override)
    except MachineInUseError:
        # Someone claimed it after the machine was selected
        await show_override_prompt(query, machine)
        return

    schedule_alarm(context.job_queue, machine, user.id, update.effective_chat.id, result.start_time, cycle_time * 60)
    for washer in result.cleared_washers:
        remove_alarms(context.job_queue, washer)

    machine_label = utils.get_display_label(machine)
    if result.displaced_user_id is not None:
        try:
            await context.bot.send_message(
                chat_id=result.displaced_user_id,
                text=f"Your usage of {machine_label} has been overridden by {utils.format_user(username)}.",
            )
        except TelegramError:
            logger.warning("Could not notify displaced user of %s", machine, exc_info=True)

    await query.edit_message_text(text=f"You are now using {machine_label}!")


# ---------------------------------------------------------------------------
# Callback queries: ping / done / cancel
# ---------------------------------------------------------------------------

async def ping_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    machine = utils.decode_machine(query.data, Encoders.PING_ENCODER)
    user_id = await asyncio.to_thread(svc.get_user_id, machine)
    if user_id in (None, ""):
        await query.edit_message_text(text="The user could not be notified.")
        return
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"Please clear your laundry in {utils.get_display_label(machine)} immediately as there are other users waiting!",
        )
    except TelegramError:
        logger.warning("Could not ping user of %s", machine, exc_info=True)
        await query.edit_message_text(text="The user could not be notified.")
        return
    await query.edit_message_text(text="User has been notified!")


async def _release(update: Update, context: ContextTypes.DEFAULT_TYPE, encoder: Encoders, expected, success_text: str, wrong_status_text: str):
    query = update.callback_query
    await query.answer()
    machine = utils.decode_machine(query.data, encoder)
    machine_label = utils.get_display_label(machine)
    try:
        await asyncio.to_thread(svc.release_machine, machine, update.effective_user.id, expected)
    except NotOwnerError:
        await query.edit_message_text(text=f"You are not using {machine_label}!")
        return
    except InvalidStatusError:
        await query.edit_message_text(text=wrong_status_text.format(machine_label))
        return
    remove_alarms(context.job_queue, machine)
    await query.edit_message_text(text=success_text.format(machine_label))


async def done_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _release(update, context, Encoders.DONE_ENCODER, [Status.DONE],
                   "Your laundry in {} has been cleared!", "{} is not done yet!")


async def cancel_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _release(update, context, Encoders.CLEAR_ENCODER, [Status.IN_USE, Status.DONE],
                   "Your usage of {} has been cancelled!", "You are not using {}!")


async def cancel_usage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(text="Your selection has been cancelled!")


async def unknown_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer(text="This option is no longer valid.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Error while handling an update", exc_info=context.error)
    if isinstance(update, Update) and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id, text="Sorry, something went wrong. Please try again."
            )
        except TelegramError:
            logger.warning("Could not send error message", exc_info=True)


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

def setup_bot(token: str) -> Application:
    logger.info("Setting up bot...")
    application = ApplicationBuilder().token(token).post_init(reschedule_alarms).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('use', use))
    application.add_handler(CommandHandler('ping', ping))
    application.add_handler(CommandHandler('done', done))
    application.add_handler(CommandHandler('cancel', cancel))
    application.add_handler(CommandHandler('refund', refund))
    application.add_handler(CommandHandler('help', help_command))

    application.add_handler(CallbackQueryHandler(use_machine, pattern=utils.machine_pattern()))
    application.add_handler(CallbackQueryHandler(confirm_use_machine, pattern=utils.callback_pattern(Encoders.CONFIRM_ENCODER)))
    application.add_handler(CallbackQueryHandler(set_duration, pattern=utils.cycle_callback_pattern(Encoders.CYCLE_ENCODER)))
    application.add_handler(CallbackQueryHandler(set_duration, pattern=utils.cycle_callback_pattern(Encoders.OVERRIDE_CYCLE_ENCODER)))
    application.add_handler(CallbackQueryHandler(cancel_usage, pattern=f"^{CANCEL_CALLBACK}\\Z"))
    application.add_handler(CallbackQueryHandler(ping_user, pattern=utils.callback_pattern(Encoders.PING_ENCODER)))
    application.add_handler(CallbackQueryHandler(done_machine, pattern=utils.callback_pattern(Encoders.DONE_ENCODER)))
    application.add_handler(CallbackQueryHandler(cancel_machine, pattern=utils.callback_pattern(Encoders.CLEAR_ENCODER)))
    application.add_handler(CallbackQueryHandler(unknown_callback))

    application.add_error_handler(error_handler)
    return application


def run_bot_polling(token: str):
    application = setup_bot(token)
    logger.info("Starting bot...")
    application.run_polling()
