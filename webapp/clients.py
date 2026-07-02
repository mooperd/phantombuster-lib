"""Shared, module-level client instances and config for the webapp.

Kept out of the blueprints so each blueprint stays tiny and nothing is duplicated.
The API key stays here (server-side) and is never sent to the browser.
"""

from __future__ import annotations

import os

from cqc import CQC
from phantombuster import Phantombuster


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is required — set it in the environment / .env")
    return value


# Secrets come from the environment only — never hardcode keys (this is a public repo).
PB_KEY = _require("PHANTOMBUSTER_API_KEY")
CQC_KEY = _require("CQC_SUBSCRIPTION_KEY")

pb = Phantombuster(PB_KEY)
cqc = CQC(CQC_KEY, partner_code="phantombuster-lib")
