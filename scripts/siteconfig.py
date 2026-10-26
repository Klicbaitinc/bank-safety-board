"""Shared site URL settings for the builder and the checker."""
import os

SITE_NAME = "Bank Safety & Savings Board"
CONTACT = "kennethdavis+banks@mail.grokbot.com"
FOOTER = (
    "Data from FDIC and NCUA public records. Not financial advice. "
    "Not affiliated with the FDIC or NCUA. Some links may be affiliate links. "
    "See disclosure."
)


def env_or(name, default):
    value = os.environ.get(name, "").strip()
    return value if value else default


SITE_URL = env_or("SITE_URL", "https://klicbaitinc.github.io").rstrip("/")
_base = env_or("BASE_PATH", "/bank-safety-board")
if _base == "/":
    BASE = ""
else:
    BASE = _base.rstrip("/")
    if BASE and not BASE.startswith("/"):
        BASE = "/" + BASE
PUBLIC = SITE_URL + BASE
