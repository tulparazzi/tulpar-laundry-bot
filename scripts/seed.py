"""Initialise /machines with every machine AVAILABLE.

WARNING: this overwrites all machine records in the database configured by
the environment (.env). Run from the project root:

    python scripts/seed.py --yes
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
from firebase_admin import db as rtdb  # noqa: E402

from constants import Machines, Status, STATUS, USER_ID, USER_USERNAME, START_TIME  # noqa: E402
from db import setup_db  # noqa: E402
from utils import now_utc, to_iso  # noqa: E402


def main():
    if "--yes" not in sys.argv:
        sys.exit("This overwrites /machines. Re-run with --yes to confirm.")
    load_dotenv()
    setup_db()
    now = to_iso(now_utc())
    rtdb.reference("/machines").set({
        machine: {STATUS: Status.AVAILABLE.value, USER_USERNAME: "", USER_ID: "", START_TIME: now}
        for machine in Machines.get_values()
    })
    print("Seeded machines:", ", ".join(Machines.get_values()))


if __name__ == "__main__":
    main()
