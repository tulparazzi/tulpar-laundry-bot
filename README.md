# Tulpar Laundry Bot
## Description
The Tulpar Laundry Bot is a Telegram Bot used to track realtime Laundry machine usage in CAPT's Tulpar House.

## Dependencies
The following python version is used:
* Python 3.12 (the Docker image is based on `python:3.12-slim-bookworm`)

The following Python packages are used (exact versions are pinned in `requirements.txt`):
* `python-telegram-bot[job-queue]`: Handling bot requests and integration with Telegram API
* `firebase-admin`: Integration of the bot with Firebase Realtime Database
* `python-dotenv`: Use of environment variables from `.env` file
* `tzdata`: Time zone data used to display times in Singapore time

## Services
The following services are used:
* `Firebase Realtime Database`: Cloud database used to persist bot data
* `Telegram BotFather`: Telegram's bot management bot used to create and set up bot

## Bot Commands

### `/start`
Starts the bot.

### `/status`
Check the usage status of each Washer and Dryer machine.

### `/use`
Use a Washer or Dryer machine.

### `/ping`
Notify the user of a Washer or Dryer that their cycle has completed.

### `/done`
Indicate that you have already removed your clothes after the machine is done.

### `/cancel`
Cancel your use of any machine in case of errors.

### `/refund`
Provides refund procedures.

### `/help`
Help function

## Configuration
Copy `.env.example` to `.env` and fill in the values: the Telegram bot token (`TELEGRAM_TOKEN`),
the Firebase Realtime Database URL (`DATABASE_URL`) and the fields of the Firebase service-account key.
The bot exits with an error listing any missing required variables.

Timestamps are stored in the database as UTC ISO-8601 strings and displayed in Singapore time.

## Running on Server

### Run Using Docker Compose
1. Make sure the `.env` file is in the project root
2. Run `docker compose up -d --build` to build and run the bot in the background. It restarts automatically if it crashes or the server reboots.
3. To read logs, run `docker compose logs -f`
4. To stop the bot, run `docker compose down`
5. To update the bot, run `git pull` then `docker compose up -d --build`

Reminders for machines in use are rescheduled from the database when the bot starts, so restarts and redeploys do not lose them.

## Development
Run the unit tests (they use an in-memory fake database and never contact Telegram or Firebase):
```
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

`scripts/seed.py --yes` resets every machine in the configured database to `AVAILABLE`.
