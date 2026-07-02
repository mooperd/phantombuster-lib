# Ephemeral Phantom Workflow

Spin up a phantom on demand, run it, pull the results into a local **SQLAlchemy + SQLite**
database, then delete the phantom so **nothing persists** in your Phantombuster account.

Everything below was **tested live** against the account on 2026-07-01 (Start plan). The
reusable helper is `Phantombuster.run_ephemeral()`; the worked example is
[examples/ephemeral_workflow.py](examples/ephemeral_workflow.py).

---

## Why ephemeral?

- **Clean slate every run.** A brand-new phantom has *no* accumulated de-duplication
  state, so it scrapes from scratch. (Recall the dedup gotcha in
  [API-guidence.md](API-guidence.md): a reused agent can return 0 rows because it "already
  retrieved all results".)
- **Stay under your agent cap.** The Start plan allows 5 agents; ephemeral phantoms are
  created and torn down within a single job, so they don't occupy a permanent slot.
- **No config drift / secrets left lying around.** The phantom exists only for the run.

---

## The object model (recap)

```
Script (code, org-owned)  →  Agent (a run config bound to a script)  →  Container (one run)  →  resultObject (rows)
```

To create a phantom from nothing you must create **both** a script and an agent, then
launch. To remove it you delete both.

---

## ⚠️ Key finding: only *org-owned* scripts can be created via the API

This is the single most important thing discovered while building this, and it was
verified empirically:

- `scripts/fetch-all` for this account returns `[]` — the org owns **no** scripts.
- The existing **LinkedIn Search Export** agent runs a **store** script
  (`scriptId 3149`, `scriptOrgName "phantombuster"`) that lives in Phantombuster's org,
  **not** yours.
- `agents/save` resolves its `script` field **by name within your own org only**. Every
  attempt to create an agent pointing at the store script failed with
  `Script … not found` / `Missing script to determine target code`. Adding a store
  phantom to your account is a **hub-only** action; it cannot be done through the public
  API.

**Consequence:** the ephemeral create→run→delete lifecycle works for **your own
(custom) Node scripts**. It does **not** let you instantiate a marketplace phantom like
LinkedIn Search Export from scratch. See [Store phantoms](#store-phantoms-linkedin-etc)
below for the recommended alternative.

---

## The create requirements (learned the hard way)

Four non-obvious rules, each confirmed by a failed→fixed test:

| # | Rule | Symptom when wrong |
|---|------|--------------------|
| 1 | `scripts/save` takes **`code`** (the JS) and **`branch`**. | Wrong field name → empty script. |
| 2 | A newly saved script lands on branch **`master`** but environment **`staging`** (not `release`). The agent's `environment` **must match** — use `environment="staging"`. | `Script doesn't exist in the specified branch` |
| 3 | Node phantoms need the full config block, including **`"phantombuster package: 5"`**. Without it the runner falls back to the legacy CasperJS/PhantomJS engine and the script won't parse. | `unknown command "nodejs"` → `SyntaxError: Parse error` → exit 1 |
| 4 | Delete endpoints (`agents/delete`, `scripts/delete`) return a plain `OK` body, **not** JSON. | A naive client throws on "non-JSON response". |

The required script header:

```js
// Phantombuster configuration {
"phantombuster command: nodejs"
"phantombuster package: 5"
// }
const Buster = require("phantombuster")
const buster = new Buster()
;(async () => {
  // ... your logic ...
  await buster.setResultObject(rows)   // rows = array of objects -> this is your data
  process.exit()
})()
```

`buster.setResultObject(rows)` is what makes the rows show up in
`containers/fetch-result-object` (i.e. `run.result` in the library).

---

## The workflow

```
1. scripts/save   (no id)         -> create org-owned script      -> script_id
2. agents/save    (no id)         -> create agent on that script  -> agent_id
3. agents/launch                  -> start a run                  -> container_id
4. poll containers/fetch          -> until status == "finished"
5. containers/fetch-result-object -> parse rows
6. write rows -> SQLAlchemy SQLite
7. agents/delete + scripts/delete -> tear the phantom down
```

Steps 1–5 and 7 are wrapped by one library call:

```python
from phantombuster import Phantombuster

pb = Phantombuster(API_KEY)
run = pb.run_ephemeral(
    name="ephemeral leads",
    code=PHANTOM_SCRIPT,          # Node source with the config block
    argument={"count": 5},        # becomes buster.argument in the script
    timeout=180,
)
print(run.exit_code, len(run.result))   # 0, 5
# script + agent are already deleted here (teardown runs in a finally block)
```

Pass `keep=True` to leave the phantom in place for debugging.

### Extracting to SQLite (SQLAlchemy 2.0)

```python
from sqlalchemy import Integer, String, JSON, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

class Base(DeclarativeBase): ...
class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    container_id: Mapped[str] = mapped_column(String)
    name: Mapped[str] = mapped_column(String)
    email: Mapped[str] = mapped_column(String)
    raw: Mapped[dict] = mapped_column(JSON)   # keep the whole row for unmapped fields

engine = create_engine("sqlite:///leads.db")
Base.metadata.create_all(engine)

with Session(engine) as s:
    for row in run.result:
        s.add(Lead(container_id=run.container_id, name=row.get("name"),
                   email=row.get("email"), raw=row))
    s.commit()
```

Tip: keep the full row in a `JSON` column (`raw`) so schema changes in the phantom's
output never lose data — you map the columns you care about and still retain everything.

---

## Teardown guarantee

`run_ephemeral` deletes the agent and script in a `finally` block, so the phantom is
removed **even if the launch or polling fails**. If your process could be killed
mid-run, also delete defensively on the next start:

```python
for a in pb.list_agents():
    if a["name"].startswith("ephemeral"):
        pb.delete_agent(a["id"])
for s in pb.list_scripts():
    pb.delete_script(s["id"])
```

---

## Tested result

Running [examples/ephemeral_workflow.py](examples/ephemeral_workflow.py):

```
Running ephemeral phantom …
  container=6612627108295521 exit=0 rows=5
SQLite now holds 5 lead row(s):
   1  Lead 1     lead1@example.com
   ...
   5  Lead 5     lead5@example.com
Ephemeral agents remaining in account: 0
```

After the run, `list_agents()` shows only the pre-existing agent and `list_scripts()` is
`[]` — the account is exactly as it started.

---

## Store phantoms (LinkedIn, etc.) {#store-phantoms-linkedin-etc}

Because marketplace scripts can't be created via the API (see the key finding above),
you cannot make **LinkedIn Search Export** truly ephemeral by create/delete. Two
alternatives:

1. **Persistent template, ephemeral *state*.** Keep one store agent permanently, and get
   a "clean slate" per job by resetting its accumulated data between runs (clear the
   result database / start from a fresh search input) rather than deleting the agent.
   You still extract per-run data via `containers/fetch-result-object` into SQLite exactly
   as above.
2. **Bring your own scraper.** If you write the scraping logic as your own Node script
   (using an identity/session cookie via `buster` APIs), it becomes an org-owned script
   and the full ephemeral create→run→delete lifecycle applies.

For both, the SQLite extraction half of this workflow is identical.
