"""Basic test driver for the CQC → LinkedIn resolve API.

Start the webapp first (python webapp/app.py), then:

    python examples/test_resolve.py 1-116865921

Env: BASE_URL (default http://127.0.0.1:5001).
"""

import json
import os
import sys
import time

import requests

CACHE_DIR = os.environ.get("CACHE_DIR", ".cache")


def _write_cache(cqc_id, obj):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{cqc_id}.json")
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2)
    print(f"\nWrote full data object -> {path}")

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:5057")


def main() -> None:
    cqc_id = sys.argv[1] if len(sys.argv) > 1 else "1-116865921"

    try:
        r = requests.post(f"{BASE}/api/resolve", json={"cqc_id": cqc_id}, timeout=30)
    except requests.exceptions.ConnectionError:
        print(f"Cannot reach the webapp at {BASE}.")
        print("Start it first (in another terminal):  python webapp/app.py")
        print("Override the target with:  BASE_URL=http://host:port python examples/test_resolve.py")
        sys.exit(1)
    if r.status_code != 202:
        print("resolve failed:", r.status_code, r.text)
        return
    d = r.json()
    prov = d["cqc"]["provider"]
    locs = (d["cqc"].get("locations") or {}).get("locations", [])
    print(f"CQC  : {prov['name']}  (brand: {prov.get('brandName')}, {len(locs)} locations)")

    if d.get("skipped"):
        print(f"SKIPPED: {d.get('reason')}")
        _write_cache(cqc_id, {"cqc_id": cqc_id, "resolve": d, "job": None})
        return

    print(f"term : {d['search_term']}")
    print(f"job  : {d['job_id']}")

    while True:
        j = requests.get(f"{BASE}{d['job_url']}", timeout=30).json()
        print(f"  state={j['state']}")
        if j["state"] != "running":
            break
        time.sleep(4)

    li = j.get("linkedin")
    if li:
        print("\nLinkedIn:")
        for k in ("companyId", "name", "linkedinUrl", "industry", "companySize",
                  "followers", "headquarters", "website"):
            print(f"  {k:12}: {li.get(k)}")
    else:
        print("\nNo LinkedIn match. Console tail:")
        print((j.get("console") or "")[-300:])

    # Write the entire data object (CQC bundle + full job/LinkedIn data) to disk.
    _write_cache(cqc_id, {"cqc_id": cqc_id, "resolve": d, "job": j})


if __name__ == "__main__":
    main()
