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
from phantombuster import Phantombuster
from resolver import resolve_ephemeral, search_term

CQC_KEY = os.environ.get("CQC_SUBSCRIPTION_KEY", "")
PB_KEY = os.environ.get("PHANTOMBUSTER_API_KEY", "")


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
    run = resolve_ephemeral(pb, term)

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
