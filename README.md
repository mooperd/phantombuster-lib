# phantombuster-lib

A small Python client library for the [Phantombuster API](https://hub.phantombuster.com/docs/api)
plus a Flask + Bootstrap demo frontend that exercises every feature of the library.

See [API-guidence.md](API-guidence.md) for the underlying API notes (verified against the
live API).

## Layout

```
phantombuster/        # the library
  client.py           # Phantombuster client + helpers (redact, parse_json_field)
webapp/               # Flask + Bootstrap demo (no custom CSS — Bootstrap 5 CDN only)
  app.py
  templates/
API-guidence.md       # API reference / field notes
```

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Library usage

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

## CQC Syndication client

`cqc/` contains a separate client for the [CQC Syndication API](cqc/syndication.yaml)
(care providers/locations, ratings, inspection areas, reports). See
[cqc-org-to-linkedin.md](cqc-org-to-linkedin.md) and
[examples/cqc_to_linkedin.py](examples/cqc_to_linkedin.py) for a CQC-provider →
LinkedIn-company-id pipeline.

```python
from cqc import CQC

cqc = CQC("your-subscription-key")
provider = cqc.get_provider("1-116865921")         # parent organisation
for p in cqc.iter_providers(region="London"):      # auto-paginates
    ...
report_pdf = cqc.get_report("<link-id>")           # PDF bytes (or as_text=True)
```

## Run the demo frontend

```bash
export PHANTOMBUSTER_API_KEY=...     # optional; falls back to the demo key
export CQC_SUBSCRIPTION_KEY=...      # optional; for the CQC → LinkedIn resolver
python webapp/app.py                 # http://127.0.0.1:5057
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

### CQC → LinkedIn resolve API

Long-running but **stateless**: the Phantombuster `containerId` is the job handle
(Phantombuster stores status + results; a single managed resolver agent is reused).

```
POST /api/resolve   {"cqc_id": "1-116865921"}
  → 202 { job_id, search_term, cqc: {provider, locations, inspectionAreas, ...}, job_url }
GET  /api/jobs/<job_id>
  → { state: running|finished|error, container, console, linkedin: {companyId, ...}, results }
```

The resolve step returns as much data as possible from both sides: the full CQC provider
bundle (provider + locations + inspection areas + assessment groups) and rich LinkedIn
company data (id, name, industry, size, followers, HQ, website, specialties, logo).

Every object is rendered with a recursive macro, so all attributes returned by the API
are surfaced in the GUI. The API key stays server-side and is never sent to the browser.
