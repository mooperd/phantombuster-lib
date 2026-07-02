"""Shared, module-level client instances and config for the webapp.

Kept out of the blueprints so each blueprint stays tiny and nothing is duplicated.
The API key stays here (server-side) and is never sent to the browser.
"""

from __future__ import annotations

import os

from cqc import CQC
from phantombuster import Phantombuster

PB_KEY = os.environ.get("PHANTOMBUSTER_API_KEY", "dVCrfE41LEd155tAsxjgMJ1kysU65VD1HOtdAT2Z0bs")
CQC_KEY = os.environ.get("CQC_SUBSCRIPTION_KEY", "d8b7af065705408b89737e290a4515cf")

pb = Phantombuster(PB_KEY)
cqc = CQC(CQC_KEY, partner_code="phantombuster-lib")
