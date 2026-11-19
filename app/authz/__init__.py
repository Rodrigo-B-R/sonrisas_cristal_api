"""Authorization engine: Casbin, with the rules in model.conf and policy.csv (same folder).

The engine answers one question: may this ROLE call this ROUTE with this METHOD?
Which rows of data the caller may see is decided later by the queries (app/access.py).
Nothing in the policy is allowed by default.
"""

from pathlib import Path

import casbin

_FOLDER = Path(__file__).parent

# Built once at start-up. enforce() only reads, so every request thread can share it.
enforcer = casbin.Enforcer(str(_FOLDER / "model.conf"), str(_FOLDER / "policy.csv"))


def is_allowed(role: str, route: str, method: str) -> bool:
    return bool(enforcer.enforce(role, route, method.upper()))
