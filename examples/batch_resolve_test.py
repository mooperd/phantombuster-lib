"""Resolve a random sample of CQC providers to LinkedIn and eyeball the matches.

Runs in-process (no webapp needed): launches all resolutions in parallel on the managed
resolver agent, polls them, writes each full object to .cache, and prints a table.

    python examples/batch_resolve_test.py [N]
"""

import json
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import resolver

from webapp.clients import cqc, pb

CACHE_DIR = ".cache"
N = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def random_provider_ids(n):
    page = random.randint(1, 300)
    listing = cqc.providers(page=page, per_page=50)
    stubs = listing.get("providers", [])
    picks = random.sample(stubs, min(n, len(stubs)))
    return [p["providerId"] for p in picks]


MAX_ACTIVE = 5  # agent maxParallelism


def main():
    os.makedirs(CACHE_DIR, exist_ok=True)
    agent_id = resolver.get_or_create_resolver(pb)
    cookie = resolver.linkedin_session_cookie(pb)

    ids = random_provider_ids(N)
    print(f"Sampled {len(ids)} providers: {ids}\n")

    # Gather CQC data up front; queue tasks for launching.
    queue = []
    for cqc_id in ids:
        try:
            bundle = resolver.gather_cqc(cqc, cqc_id)
        except Exception as e:
            print(f"  {cqc_id}: CQC error {e}")
            continue
        if bundle["provider"].get("registrationStatus") == "Deregistered":
            print(f"  {cqc_id}: skipped (deregistered)")
            continue
        queue.append({"cqc_id": cqc_id, "bundle": bundle,
                      "term": resolver.search_term(bundle["provider"])})

    jobs = []
    active = set()
    deadline = time.monotonic() + 300
    while (queue or active) and time.monotonic() < deadline:
        # Fill free parallelism slots.
        while queue and len(active) < MAX_ACTIVE:
            task = queue.pop(0)
            cid = pb.launch(agent_id, argument={"sessionCookie": cookie, "keywords": task["term"]})
            task["container"] = cid
            jobs.append(task)
            active.add(cid)
            print(f"  launched {task['cqc_id']}  term={task['term']!r}  container={cid}")
        time.sleep(5)
        for j in jobs:
            cid = j.get("container")
            if cid not in active:
                continue
            c = pb.get_container(cid)
            if c.get("status") in ("finished", "error"):
                j["result"] = (pb.get_result(cid) or [None])[0]
                active.discard(cid)

    print("\n" + "=" * 100)
    print(f"{'CQC name':32} {'brand/term':22} -> {'LinkedIn name':28} {'id':>10}  {'HQ'}")
    print("=" * 100)
    for j in jobs:
        prov = j["bundle"]["provider"]
        li = j.get("result") or {}
        with open(os.path.join(CACHE_DIR, f"{j['cqc_id']}.json"), "w") as fh:
            json.dump({"cqc_id": j["cqc_id"], "term": j["term"],
                       "cqc": j["bundle"], "linkedin": li}, fh, indent=2)
        print(f"{(prov.get('name') or '')[:31]:32} "
              f"{(j['term'] or '')[:21]:22} -> "
              f"{(li.get('name') or '—')[:27]:28} "
              f"{str(li.get('companyId') or '—'):>10}  "
              f"{li.get('headquarters') or '—'}")
    print("\nFull objects written to .cache/<id>.json")


if __name__ == "__main__":
    main()
