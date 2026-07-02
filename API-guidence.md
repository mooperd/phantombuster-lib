# Phantombuster API — Guidance

Practical notes for building a Python library (and a Flask + Bootstrap demo frontend)
that controls Phantombuster. Everything below was verified against the **live API**
with the provided key on 2026-07-01, unless marked *(from docs)*.

---

## 1. Mental model

Phantombuster has a small, clean object hierarchy. Get this right and the whole API
falls into place:

```
Script   →  Agent          →  Container            →  results
(template)  (configured        (one execution /        - console output (log text)
            instance of a       "run" of an agent)      - resultObject (structured rows)
            script, with                                 - files on S3 (CSV / JSON)
            an argument)
```

- **Script** – a program from the Phantombuster store (e.g. `LinkedIn Search Export.js`,
  `scriptId: 3149`). You rarely touch scripts directly for a control panel.
- **Agent** – a *configured instance* of a script. It holds the `argument` (the JSON
  config: search URL, session cookie, result limits, notifications, etc.). This is the
  main object your library manages. The demo account has **1 agent**:
  `LinkedIn Search Export` (`id: 474380569535162`).
- **Container** – a single **run** of an agent. Every launch creates a new container
  with its own `status`, `exitCode`, timestamps, console output, and results.
- **Results** – produced by a container:
  - **console output** – plain-text log of the run.
  - **resultObject** – the structured scraped data (JSON string → array of row objects).
  - **S3 files** – CSV/JSON files stored under the agent's S3 folders.

> ⚠️ **Security:** an agent's `argument` contains a **live LinkedIn `sessionCookie`**
> (and can contain other credentials). Treat the full agent object as a secret. Never
> log it, never render it raw in the frontend, and redact `sessionCookie` before display.
> Same for the API key — keep it server-side only, never ship it to the browser.

---

## 2. Connection basics

| Item | Value |
|------|-------|
| Base URL | `https://api.phantombuster.com/api/v2/` *(verified)* |
| Auth header | `X-Phantombuster-Key-1: <API_KEY>` *(verified working)* — alias `X-Phantombuster-Key` |
| Accept | `application/json` |
| Content-Type (POST) | `application/json` |
| Time fields | **milliseconds** since epoch (v2 differs from v1's seconds) |
| Org header | `X-Phantombuster-Org` only needed for third-party keys *(from docs; not needed here)* |

Auth can also be passed as a `?key=` query param, but the header is preferred.

**Error shape** — on failure the API returns HTTP 200 with a body like:

```json
{ "status": "error", "error": "Endpoint not found" }
```

So your library must inspect the JSON body, not just the HTTP status code. A missing/bad
key returns:
`{"status":"error","error":"Missing session cookie or API key ..."}`.

Successful GETs generally return the payload **directly** (an array or object), *not*
wrapped in a `{status, data}` envelope.

---

## 3. Endpoints (verified)

### Agents

#### `GET /agents/fetch-all`
Returns an **array** of agent objects, each including its full `manifest` (the store
metadata: description, argument form, tutorial URLs, output column descriptions, etc.).
The manifest is large — for a listing UI, project down to a few fields.

Trimmed example:
```json
[
  {
    "id": "474380569535162",
    "name": "LinkedIn Search Export",
    "script": "LinkedIn Search Export.js",
    "scriptId": "3149",
    "scriptOrgName": "phantombuster",
    "branch": "master",
    "environment": "release",
    "manifest": { "...": "large object" }
  }
]
```

#### `GET /agents/fetch?id=<agentId>`
Full detail of one agent. **Does not include `manifest`**, but includes the live
`argument`. Verified keys:

```
argument, branch, code, environment, fileMgmt, id, lastEndType, launchType,
maxParallelism, name, nbLaunches, notifications, orgS3Folder, s3Folder, script,
scriptId, scriptOrgName, updatedAt, wasSetupValidWhenSubmittedByTheFrontend
```

Notable fields:
- `argument` — a **JSON string** (not an object). Parse it. Contains config +
  `identities[].sessionCookie` (**secret**).
- `nbLaunches` — total run count (e.g. `3`).
- `lastEndType` — e.g. `"finished"`.
- `launchType` — e.g. `"manually"`.
- `maxParallelism` — e.g. `1`.
- `s3Folder` / `orgS3Folder` — where output files live on S3.
- `notifications` — object of email-notification toggles.

#### `POST /agents/launch` *(verified)*
Starts a new run (creates a container). Body:

| Field | Type | Notes |
|-------|------|-------|
| `id` | string | **required** — agent id |
| `argument` | string \| object | overrides the saved argument for this run |
| `arguments` | string \| object | alias of `argument` |
| `bonusArgument` | string \| object | single-use, **merged** into the base argument |
| `saveArgument` / `saveArguments` | bool | persist the argument as the new default |
| `manualLaunch` | bool | mark as manually launched |
| `maxInstanceCount` | number ≥1 | refuse to launch if this many instances already run |
| `userCustomMetadata` / `internalMetadata` | object | container tags |

Returns the new **`containerId`** (verified: `{"containerId":"2631549211834447"}`).
Poll that container for progress/results. A launch via the API shows up on the container
as `launchType: "user api call"`.

> **Dedup gotcha (verified):** re-running the LinkedIn Search Export against a search it
> already scraped produces `exitCode: 0` but logs
> `⚠️ We've already retrieved all results from that search`, and
> `fetch-result-object` returns `resultObject: null` — i.e. a *successful run with no new
> rows*. Your library/UI must treat `resultObject == null` as "no new results", **not**
> as an error. To force fresh rows you need a new/different search input.

#### `POST /agents/abort` *(from docs)*
Stops running container(s) for an agent. Body: `{ "id": "<agentId>" }`.

#### `POST /agents/delete` / `POST /agents/save` *(from docs)*
Delete an agent / create-or-update an agent's config.

### Containers

#### `GET /containers/fetch-all?agentId=<agentId>`
Run history for an agent. Returns:

```json
{
  "maxLimitReached": false,
  "containers": [
    {
      "id": "5233239439174507",
      "status": "finished",
      "createdAt": 1782885147509,
      "launchType": "manual",
      "endType": "finished",
      "endedAt": 1782885179512,
      "exitCode": 0,
      "retryNumber": 0
    }
  ]
}
```
`exitCode: 0` = success, non-zero = failure (the demo history has one `exitCode: 1`).

#### `GET /containers/fetch?id=<containerId>`
Single container detail:
```json
{
  "id": "5233239439174507",
  "createdAt": 1782885147509,
  "launchedAt": 1782885147895,
  "endedAt": 1782885179512,
  "status": "finished",
  "launchType": "manual",
  "retryNumber": 0,
  "exitCode": 0,
  "endType": "finished"
}
```
`status` values seen: `finished`. While running you'll see `running` / `starting`
*(from docs)*.

#### `GET /containers/fetch-output?id=<containerId>`
The **console log** of the run. Returns:
```json
{
  "status": null,
  "containerStatus": null,
  "progress": null,
  "output": "(node:1) NOTE: ...\r\n* Container 5233239439174507 started ...\r\n* Spawning Node v16.20.2"
}
```
For a **finished** container the live status fields are `null` and `output` holds the
full log. For a **running** container these carry live values *(from docs)*:
- `containerStatus` / `status` — run state,
- `progress` — `{ label, percentage, ... }`,
- and it supports incremental fetches via `mode` / `fromOutputPos` query params to poll
  only new log lines.

**Use this to build a live "console" view** — poll every ~2s while `status` is running.

#### `GET /containers/fetch-result-object?id=<containerId>`
The **structured results**. `resultObject` is a **JSON string** → array of row objects.
Real sample (one LinkedIn profile row, truncated):
```json
{
  "status": null,
  "resultObject": "[{\"profileUrl\":\"https://linkedin.com/in/ns-sharpe-252145405\",\"fullName\":\"NS Sharpe\",\"connectionDegree\":\"3rd\",\"timestamp\":\"2026-07-01T05:52:56.627Z\",\"category\":\"People\",\"query\":\"https://www.linkedin.com/search/...\"}]"
}
```
The row schema matches the agent manifest's `outputDescription` (for this script:
`profileUrl, fullName, firstName, lastName, vmid, job, location, ...`).
**Parse `resultObject` and render as a Bootstrap table** — this is the money shot for the
demo frontend.

### Org / account

#### `GET /orgs/fetch-resources`
Plan + quota usage. Great for a dashboard header. Live sample:
```json
{
  "agentCount": 1,
  "planName": "freeForever_2",
  "monthlyExecutionTime": 31379,
  "dailyExecutionTime": 0,
  "s3Storage": 0,
  "dailyResourceNextResetAt": 1782947468811,
  "monthlyResourceNextResetAt": 1785268597446,
  "plan": {
    "name": "Free",
    "agents": 1,
    "parallelism": 10,
    "dailyExecutionTime": 1800000,
    "monthlyExecutionTime": 1800000,
    "dailyCaptchas": 50,
    "s3Storage": 50000000
  }
}
```
Execution time is in **ms**. On the Free plan you get ~30 min/day of runtime — so the
demo should **avoid needless launches**.

### Endpoints that 404 (don't use these names)
- `GET /agents/fetch-all-containers` → `Endpoint not found` (use `/containers/fetch-all?agentId=`)
- `GET /user` → `Endpoint not found` (use `/orgs/fetch-resources` for account info)

---

## 4. The launch → poll → results lifecycle

This is the core flow your library should expose as one high-level helper:

```
1. POST /agents/launch { id }            -> { containerId }
2. loop: GET /containers/fetch?id=cid    -> until status == "finished" (or error)
        (optionally GET /containers/fetch-output for live log + progress)
3. GET /containers/fetch-result-object?id=cid   -> parse resultObject -> rows
   GET /containers/fetch-output?id=cid          -> final console log
4. check container.exitCode (0 = ok)
```

Guidance:
- Poll with a sensible interval (2–5s) and a hard timeout.
- Always parse `argument` and `resultObject` — both are JSON **strings**.
- Surface `exitCode` and `endType` so the UI can show success/failure clearly.

---

## 5. Suggested Python library shape

Thin, typed wrapper. Keep the HTTP concerns in one client; expose domain objects.

```python
class PhantombusterError(Exception): ...

class Phantombuster:
    def __init__(self, api_key: str,
                 base_url: str = "https://api.phantombuster.com/api/v2"): ...

    # low-level
    def _get(self, path: str, **params) -> dict | list: ...
    def _post(self, path: str, **body) -> dict: ...
    # both must raise PhantombusterError when body["status"] == "error"

    # agents
    def list_agents(self) -> list[Agent]: ...          # GET /agents/fetch-all
    def get_agent(self, agent_id: str) -> Agent: ...   # GET /agents/fetch
    def launch(self, agent_id: str, argument: dict | None = None,
               bonus_argument: dict | None = None,
               save: bool = False) -> str: ...         # -> container_id
    def abort(self, agent_id: str) -> None: ...        # POST /agents/abort

    # containers
    def list_containers(self, agent_id: str) -> list[Container]: ...
    def get_container(self, container_id: str) -> Container: ...
    def get_output(self, container_id: str) -> str: ...          # console log
    def get_result(self, container_id: str) -> list[dict]: ...   # parsed resultObject

    # org
    def get_resources(self) -> dict: ...               # plan + quota

    # high-level convenience
    def run_and_wait(self, agent_id: str, argument: dict | None = None,
                     timeout: int = 300, poll: float = 3.0) -> RunResult: ...
```

Implementation notes:
- Use `requests.Session` with the auth header set once.
- Central response handler that raises on `{"status":"error"}`.
- `Agent.argument` and container results: `json.loads(...)` the string fields.
- Add a `redact()` helper that strips `sessionCookie`/keys before serialising for the UI.

---

## 6. Flask + Bootstrap demo (no custom CSS)

Use a Bootstrap CDN (`bootstrap@5` CSS + JS bundle) and Bootstrap components only.
The API key stays in the Flask process (env var) — never sent to the browser.

Pages that showcase every library feature:

| Route | Shows | API used |
|-------|-------|----------|
| `/` (Dashboard) | plan name, agent count, daily/monthly execution time as Bootstrap progress bars | `orgs/fetch-resources` |
| `/agents` | table (card list) of agents: name, script, launches, last end type | `agents/fetch-all` |
| `/agents/<id>` | agent detail; **redacted** argument (pretty JSON in `<pre>`); "Launch" button | `agents/fetch` |
| `/agents/<id>/launch` (POST) | launch, redirect to the new container page | `agents/launch` |
| `/agents/<id>/runs` | run history table with status badges + exit codes | `containers/fetch-all` |
| `/containers/<id>` | live status badge, console log (auto-refresh), results table | `containers/fetch`, `/fetch-output`, `/fetch-result-object` |

Bootstrap-only building blocks:
- Status → colored **badges** (`bg-success` exit 0, `bg-danger` non-zero, `bg-warning`
  running).
- Quotas → **progress bars** (`monthlyExecutionTime / plan.monthlyExecutionTime`).
- Results → responsive **table** (`table table-striped table-hover`).
- Console log → a `<pre>` inside a `card`; poll via `<meta http-equiv="refresh">` or a
  tiny `fetch()` loop hitting a Flask JSON proxy endpoint.
- Timestamps are ms → divide by 1000 before `datetime.fromtimestamp`.

Demo etiquette: the Free plan has ~30 min/day of runtime, and launches actually scrape
LinkedIn using the stored cookie. For a safe demo, **default to browsing existing agents
and past containers/results** and gate the "Launch" button behind an explicit confirm.

---

## 7. Quick reference (curl)

```bash
KEY="<API_KEY>"
BASE="https://api.phantombuster.com/api/v2"
auth=(-H "X-Phantombuster-Key-1: $KEY" -H "accept: application/json")

curl -s "$BASE/agents/fetch-all" "${auth[@]}"
curl -s "$BASE/agents/fetch?id=474380569535162" "${auth[@]}"
curl -s "$BASE/containers/fetch-all?agentId=474380569535162" "${auth[@]}"
curl -s "$BASE/containers/fetch?id=<containerId>" "${auth[@]}"
curl -s "$BASE/containers/fetch-output?id=<containerId>" "${auth[@]}"
curl -s "$BASE/containers/fetch-result-object?id=<containerId>" "${auth[@]}"
curl -s "$BASE/orgs/fetch-resources" "${auth[@]}"

# launch (creates a container; consumes quota + scrapes)
curl -s -X POST "$BASE/agents/launch" "${auth[@]}" \
  -H "content-type: application/json" \
  -d '{"id":"474380569535162"}'
```
