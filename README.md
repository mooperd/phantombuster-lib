# phantombuster-lib

Python clients for the [Phantombuster API](https://hub.phantombuster.com/docs/api) and the
[CQC Syndication API](https://api-portal.service.cqc.org.uk/api-details#api=syndication),
plus a blueprint-based Flask + Bootstrap web app that exercises them — including a
**CQC provider → LinkedIn company** resolver built on ephemeral/managed phantoms.

## Layout

```
phantombuster/          # Phantombuster API client
  client.py             #   client + helpers (run_and_wait, run_ephemeral, redact, ...)
cqc/                    # CQC Syndication API client
  client.py             #   client (providers/locations/changes/reports, auto-paging)
  syndication.yaml      #   the OpenAPI spec
webapp/                 # Flask + Bootstrap app (app factory, no custom CSS)
  __init__.py           #   create_app(): filters, error handlers, blueprint registration
  app.py                #   dev entrypoint
  clients.py            #   shared client instances
  resolver.py           #   CQC->LinkedIn logic (managed resolver agent, CQC gather)
  resolver_phantom.js   #   the Puppeteer phantom (UK-HQ company search + scrape)
  blueprints/           #   dashboard / agents / containers / resolve
  templates/            #   Bootstrap templates + a recursive "render everything" macro
examples/               # runnable scripts (see below)
API-guidence.md         # Phantombuster API notes (verified live)
EPHEMERAL-WORKFLOW.md   # create->run->extract-to-SQLite->delete pattern
cqc-org-to-linkedin.md  # how CQC id -> LinkedIn numeric id works
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Keys are read from the environment, with demo fallbacks:
`PHANTOMBUSTER_API_KEY`, `CQC_SUBSCRIPTION_KEY`, `LINKEDIN_SESSION_COOKIE` (optional; else
borrowed from an existing agent's identity). See [.env.example](.env.example).

## Phantombuster client

```python
from phantombuster import Phantombuster

pb = Phantombuster("YOUR_API_KEY")

pb.get_resources()                 # plan + quota
agents = pb.list_agents()          # all agents (with manifest)
agent  = pb.get_agent(agents[0]["id"])

# Launch, poll to completion, and fetch parsed results in one call:
run = pb.run_and_wait(agents[0]["id"], bonus_argument={"numberOfResultsPerLaunch": 5})
print(run.succeeded, run.exit_code, len(run.result))

# Or drive the lifecycle manually:
cid = pb.launch(agents[0]["id"])
pb.get_container(cid)              # status / exitCode / timestamps
pb.get_output(cid)                # console log + live progress
pb.get_result(cid)                # parsed structured rows (list of dicts)
```

`redact()` masks secrets (session cookies, tokens) before display; `parse_json_field()`
decodes the fields the API returns as JSON strings (`argument`, `resultObject`).

### Ephemeral phantoms

Create a throwaway script + agent, run it, and delete both in one call — nothing persists
in your account. See [EPHEMERAL-WORKFLOW.md](EPHEMERAL-WORKFLOW.md) and
[examples/ephemeral_workflow.py](examples/ephemeral_workflow.py) (extracts run data into a
local SQLAlchemy SQLite DB).

```python
run = pb.run_ephemeral(name="ephemeral leads", code=NODE_SCRIPT, argument={"count": 5})
print(run.exit_code, len(run.result))   # phantom is already deleted
```

Node phantoms need a config header. Plain Node: `"phantombuster command: nodejs"` +
`"phantombuster package: 5"`. Headless browser (Node 16 + Puppeteer): `"phantom image:
web-node:v1"`. `create_script` / `create_agent` / `delete_*` cover the pieces.

## CQC Syndication client

```python
from cqc import CQC

cqc = CQC("your-subscription-key")
provider = cqc.get_provider("1-116865921")         # parent organisation (not a site)
cqc.get_provider_locations("1-116865921")          # the sites underneath it
for p in cqc.iter_providers(region="London"):      # auto-paginates
    ...
report_pdf = cqc.get_report("<link-id>")           # PDF bytes (or as_text=True)
```

Covers every endpoint in [cqc/syndication.yaml](cqc/syndication.yaml): provider/location
detail, assessment-service-groups, inspection areas, the paginated `providers` /
`locations` / `changes` lists (with `iter_*` helpers), the taxonomy, and reports.

## Run the web app

```bash
export PHANTOMBUSTER_API_KEY=...     # optional; falls back to the demo key
export CQC_SUBSCRIPTION_KEY=...      # optional; for the CQC → LinkedIn resolver
python webapp/app.py                 # http://127.0.0.1:5057  (PORT overrides)
# or: gunicorn "webapp:create_app()"
```

The app uses an **application factory** (`webapp/create_app`) and is fully
**blueprint-based** — every page and JSON endpoint lives in a small blueprint under
[webapp/blueprints/](webapp/blueprints/); shared clients/filters live in
[webapp/clients.py](webapp/clients.py) and the factory.

Pages:

- **Dashboard** (`dashboard`) — plan, agent count, execution-time quota bars, raw resources.
- **Agents** (`agents`) — list, agent detail (*every* attribute, secrets masked, run
  history), **Launch**/**Abort**.
- **Container detail** (`containers`) — status, live-polling console, full results table.
- **CQC → LinkedIn** (`resolve`) — enter a CQC provider id, watch the job resolve.

Every object is rendered with a recursive macro, so all attributes returned by the APIs
are surfaced in the GUI. The API keys stay server-side and are never sent to the browser.

### CQC → LinkedIn resolve API

Long-running but **stateless**: the Phantombuster `containerId` is the job handle
(Phantombuster stores status + results; a single managed resolver agent, created on first
use, is reused).

```
POST /api/resolve   {"cqc_id": "1-116865921"}
  → 202 { job_id, search_term, cqc: {provider, locations, inspectionAreas, ...}, job_url }
  → 200 { job_id: null, skipped: true, reason, cqc }   # deregistered provider: no lookup
GET  /api/jobs/<job_id>
  → { state: running|finished|error, container, console, linkedin: {companyId, ...}, results }
```

It returns as much data as possible from both sides: the full CQC provider bundle
(provider + locations + inspection areas + assessment groups) and rich LinkedIn company
data (id, name, industry, size, followers, HQ, website, specialties, logo). Deregistered
providers short-circuit before any phantom runs.

**Matching accuracy (known limitation).** The LinkedIn step searches by the provider's
brand/legal name, constrained to **UK-headquartered** companies
(`companyHqGeo` facet), and takes the top hit. The UK filter removes foreign lookalikes,
but name-only matching is inherently unsafe: near-identical names can be different legal
entities (e.g. *A L A Care Limited* ≠ *L A Care Ltd*), and providers with no LinkedIn
presence can still return a spurious top hit. Treat low-signal matches as unconfirmed;
website-domain / Companies-House corroboration is the reliable path (not yet implemented).
See [cqc-org-to-linkedin.md](cqc-org-to-linkedin.md).

## Examples

Run from the repo root with the venv active:

- [examples/ephemeral_workflow.py](examples/ephemeral_workflow.py) — ephemeral phantom → SQLite.
- [examples/cqc_to_linkedin.py](examples/cqc_to_linkedin.py) `<cqc_id>` — one-shot CQC → LinkedIn id.
- [examples/linkedin_company_id.js](examples/linkedin_company_id.js) — the Puppeteer lookup phantom.
- [examples/test_resolve.py](examples/test_resolve.py) `<cqc_id>` — drives the running web API; writes the full object to `.cache/<id>.json`.
- [examples/batch_resolve_test.py](examples/batch_resolve_test.py) `[N]` — resolves N random providers in parallel to eyeball match quality.
