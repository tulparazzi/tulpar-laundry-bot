import logging
import os
import sys

from dotenv import load_dotenv

from db import REQUIRED_ENV, setup_db
from controller import run_bot_polling

TOKEN_ENV = "TELEGRAM_TOKEN"

logger = logging.getLogger(__name__)


def configure_logging():
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,
    )
    # httpx logs every request URL at INFO, and those URLs contain the bot token
    logging.getLogger("httpx").setLevel(logging.WARNING)


def missing_env() -> list:
    return [name for name in [TOKEN_ENV, *REQUIRED_ENV] if not os.getenv(name)]


def main():
    # Values already in the environment (e.g. docker compose env_file) take precedence
    load_dotenv()
    configure_logging()
    missing = missing_env()
    if missing:
        logger.critical("Missing required environment variables: %s", ", ".join(missing))
        sys.exit(1)
    setup_db()
    run_bot_polling(os.environ[TOKEN_ENV])


if __name__ == '__main__':
    main()
