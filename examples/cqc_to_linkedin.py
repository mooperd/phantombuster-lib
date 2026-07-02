"""CQC provider id -> LinkedIn numeric company id, end to end.

1. Fetch the provider (the parent legal entity) from the CQC Syndication API.
2. Run an *ephemeral* Phantombuster phantom that, using a LinkedIn session cookie,
   searches LinkedIn companies by the provider's brand name and reads the numeric
   company id off the authenticated company page.
3. Print the mapping. The phantom (script + agent) is deleted afterwards.

    python examples/cqc_to_linkedin.py 1-116865921

Env: CQC_SUBSCRIPTION_KEY, PHANTOMBUSTER_API_KEY, LINKEDIN_SESSION_COOKIE (optional;
falls back to the cookie stored on the existing LinkedIn Search Export agent).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cqc import CQC
from phantombuster import Phantombuster, parse_json_field

CQC_KEY = os.environ.get("CQC_SUBSCRIPTION_KEY", "d8b7af065705408b89737e290a4515cf")
PB_KEY = os.environ.get("PHANTOMBUSTER_API_KEY", "dVCrfE41LEd155tAsxjgMJ1kysU65VD1HOtdAT2Z0bs")
PHANTOM = os.path.join(os.path.dirname(__file__), "linkedin_company_id.js")
# The agent whose identity (li_at cookie) we borrow when none is supplied via env.
SOURCE_AGENT = os.environ.get("PB_SOURCE_AGENT", "474380569535162")


def search_term(provider: dict) -> str:
    """Prefer the trading brand (LinkedIn lists brands, not legal names)."""
    brand = (provider.get("brandName") or "").replace("BRAND ", "").strip()
    return brand or provider.get("name") or ""


def linkedin_session_cookie(pb: Phantombuster) -> str:
    cookie = os.environ.get("LINKEDIN_SESSION_COOKIE")
    if cookie:
        return cookie
    arg = parse_json_field(pb.get_agent(SOURCE_AGENT)["argument"])
    return arg["identities"][0]["sessionCookie"]


def main() -> None:
    provider_id = sys.argv[1] if len(sys.argv) > 1 else "1-116865921"
    pb = Phantombuster(PB_KEY)
    cqc = CQC(CQC_KEY, partner_code="phantombuster-lib")

    provider = cqc.get_provider(provider_id)
    term = search_term(provider)
    print(f"CQC provider {provider_id}")
    print(f"  name : {provider.get('name')}")
    print(f"  brand: {provider.get('brandName')}  ->  search term: {term!r}")
    print(f"  companiesHouse: {provider.get('companiesHouseNumber')}  town: {provider.get('postalAddressTownCity')}")

    print("Resolving LinkedIn id via ephemeral phantom (search by name, authenticated) …")
    run = pb.run_ephemeral(
        name="cqc-to-linkedin",
        code=open(PHANTOM).read(),
        argument={
            "sessionCookie": linkedin_session_cookie(pb),
            "keywords": term,
        },
        timeout=280,
        poll=6,
    )

    if not run.result:
        print("No LinkedIn match found. Console tail:")
        print((run.output or "")[-400:])
        return
    hit = run.result[0]
    print("LinkedIn match:")
    print(f"  name      : {hit.get('name')}")
    print(f"  vanity    : {hit.get('vanity')}")
    print(f"  companyId : {hit.get('companyId')}   <-- use in currentCompany=[\"{hit.get('companyId')}\"]")


if __name__ == "__main__":
    main()
