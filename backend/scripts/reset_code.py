"""Create a one-time password reset code from the terminal.

For when nobody can do it in the app, e.g. the only admin forgot their password. Running
this needs access to this laptop and its database, so it gives no more power than that.

    python -m scripts.reset_code --username alice

The user enters the code under "Forgot password?" on the login screen. It works once and
expires after auth.RESET_MINUTES.
"""

import argparse
import sys

from app import auth, db


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a one-time password reset code.")
    parser.add_argument("--username", required=True)
    args = parser.parse_args()

    username = args.username.strip().lower()
    found = db.user_with_hash(username)
    if found is None:
        print(f"No user named {username!r}.", file=sys.stderr)
        return 1
    user = found[0]
    code = auth.new_reset_code()
    expires_at = db.create_reset(auth.token_hash(code), user["id"], auth.RESET_MINUTES)
    print(f"Reset code for {user['username']} ({user['role']}): {code}")
    print(f"Works once, until {expires_at}. Enter it under 'Forgot password?' on the login screen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
