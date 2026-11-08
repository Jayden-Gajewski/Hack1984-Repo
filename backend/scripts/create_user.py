"""Create a local login (or reset its password) in the local Postgres.

Same rules as the signup page: the email is lowercased, the password needs 8+ characters,
and it's stored as an scrypt hash (app/auth.py). Nothing leaves this laptop.

    cd backend
    python -m scripts.create_user --email admin@gmail.com            # prompts for the password
    python -m scripts.create_user --email admin@gmail.com --reset    # new password, ends sessions

The app has no admin role: every local account can do the same things.
"""

import argparse
import getpass
import sys

from pydantic import ValidationError

from app import auth, db
from app.models import Credentials


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local Dossier login.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", help="Omit to be prompted (keeps it out of shell history).")
    parser.add_argument("--reset", action="store_true", help="Set a new password if the account exists.")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    try:
        creds = Credentials(email=args.email, password=password)
    except ValidationError as exc:
        print("; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors()), file=sys.stderr)
        return 2

    try:
        db.init_schema()  # creates the users and sessions tables if they don't exist yet
        hashed = auth.hash_password(creds.password)
        if db.create_user(creds.email, hashed):
            print(f"Created {creds.email}.")
            return 0
        if args.reset and db.set_password(creds.email, hashed):
            print(f"Reset the password for {creds.email} and ended its sessions.")
            return 0
    except Exception as exc:
        print(f"Postgres isn't reachable ({exc}). Start it with `docker compose up -d`.", file=sys.stderr)
        return 1
    print(f"{creds.email} already exists. Use --reset to set a new password.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
