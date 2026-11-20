"""Loads settings from the .env file in the project root.

On first run the file is created with a random session key and a random
admin password, so nothing secret ever lives in the code or in git.
"""
import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"

TEMPLATE = """# Warrior booking - local settings. Never commit this file.
SECRET_KEY={secret}

# Password for the barber's admin page at /admin
ADMIN_PASSWORD={password}

# Public address of the site, used for links in e-mails
PUBLIC_URL=http://localhost:5000

# Set to 1 when the site runs on https
COOKIE_SECURE=0

# E-mail confirmations (leave SMTP_HOST empty to turn e-mail off)
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
MAIL_FROM=
# The barber gets a copy of every new booking and cancellation here
NOTIFY_EMAIL=
"""


def load() -> bool:
    """Read .env into os.environ. Returns True if the file was just created."""
    created = False
    if not ENV_PATH.exists():
        ENV_PATH.write_text(
            TEMPLATE.format(secret=secrets.token_hex(32), password=secrets.token_urlsafe(9)),
            encoding="utf-8",
        )
        created = True
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
    return created


def get(key: str, default: str = "") -> str:
    return os.environ.get(key, default)
