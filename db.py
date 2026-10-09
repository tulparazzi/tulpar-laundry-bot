import logging
import os
from typing import Callable, Dict, Optional

import firebase_admin
from firebase_admin import credentials
from firebase_admin import db as rtdb

from constants import USER_ID
from utils import assert_valid_machine

logger = logging.getLogger(__name__)

# Firebase service-account fields, mapped from environment variables.
REQUIRED_CREDENTIAL_ENV = {
    "type": "TYPE",
    "project_id": "PROJECT_ID",
    "private_key_id": "PRIVATE_KEY_ID",
    "private_key": "PRIVATE_KEY",
    "client_email": "CLIENT_EMAIL",
    "client_id": "CLIENT_ID",
    "token_uri": "TOKEN_URI",
}
OPTIONAL_CREDENTIAL_ENV = {
    "auth_uri": "AUTH_URI",
    "auth_provider_x509_cert_url": "AUTH_PROVIDER_X509_CERT_URL",
    "client_x509_cert_url": "CLIENT_X509_CERT_URL",
    "universe_domain": "UNIVERSE_DOMAIN",
}
REQUIRED_ENV = ["DATABASE_URL", *REQUIRED_CREDENTIAL_ENV.values()]


def setup_db():
    logger.info("Setting up database...")
    info = {key: os.environ[env] for key, env in REQUIRED_CREDENTIAL_ENV.items()}
    info["private_key"] = info["private_key"].replace('\\n', '\n')
    for key, env in OPTIONAL_CREDENTIAL_ENV.items():
        if os.getenv(env):
            info[key] = os.environ[env]
    firebase_admin.initialize_app(credentials.Certificate(info), {
        'databaseURL': os.environ["DATABASE_URL"],
    })
    logger.info("Connected to database")


def _machine_ref(machine: str):
    assert_valid_machine(machine)
    return rtdb.reference(f"/machines/{machine}")


def get_statuses() -> Dict:
    """Return the /machines node, or {} if it is missing or malformed."""
    statuses = rtdb.reference("/machines").get()
    if not isinstance(statuses, dict):
        if statuses is not None:
            logger.warning("Unexpected /machines value of type %s", type(statuses).__name__)
        return {}
    return statuses


def transact_machine(machine: str, update_fn: Callable[[Optional[Dict]], Dict]) -> Dict:
    """Atomically transform /machines/<machine>.

    update_fn receives the current value (possibly None) and returns the new
    value; raising inside update_fn aborts without writing.
    """
    logger.debug("Transaction on %s", machine)
    return _machine_ref(machine).transaction(update_fn)


def get_user_id(machine: str):
    return _machine_ref(machine).child(USER_ID).get()


def get_machine(machine: str) -> Optional[Dict]:
    value = _machine_ref(machine).get()
    return value if isinstance(value, dict) else None
