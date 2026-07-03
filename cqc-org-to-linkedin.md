# CQC Provider → LinkedIn numeric company ID

How to take a CQC **provider** (the parent legal entity, not an individual care site) and
resolve it to a **LinkedIn numeric company ID** — the id the LinkedIn Search Export
phantom needs in `currentCompany=["<ID>"]`.

Tested end-to-end on 2026-07-01 with `https://www.cqc.org.uk/provider/1-116865921`.

**Result:** provider `1-116865921` → *Practice Plus Group Hospitals Limited* (brand
"Practice Plus Group") → LinkedIn company `practiceplusgroup` → **numeric id `68842389`**.

---

## The pipeline

```
CQC provider id  ──GET /providers/{id}──▶  company name + brand + signals
                                              │
                          search linkedin.com │  (pick the PARENT company page,
                                              ▼   not a hospital/showcase site page)
                                     linkedin.com/company/<vanity>
                                              │
                              fetch page, regex│
                                              ▼
                                urn:li:organization:<NUMERIC ID>
```

A useful mental model: **CQC provider ≈ LinkedIn company (parent); CQC location ≈ LinkedIn
showcase / per-site page.** We want the provider ↔ company mapping.

---

## Step 1 — CQC Syndication API: get the provider

- Base URL: `https://api.service.cqc.org.uk/public/v1`
- Spec: [cqc/syndication.yaml](cqc/syndication.yaml)
- Auth: header `Ocp-Apim-Subscription-Key: <key>` (or `?subscription-key=` query param).
- Endpoint: `GET /providers/{id}` — the provider *is* the parent legal entity; its
  `locationIds[]` are the sites underneath it. Use this, **not** `/locations/{id}`.

```bash
curl -s "https://api.service.cqc.org.uk/public/v1/providers/1-116865921" \
  -H "Ocp-Apim-Subscription-Key: <CQC_SUBSCRIPTION_KEY>" | jq .
```

Fields that matter for the LinkedIn match (verified response for `1-116865921`):

| Field | Value | Use |
|-------|-------|-----|
| `name` | `Practice Plus Group Hospitals Limited` | legal entity name |
| `brandName` | `BRAND Practice Plus Group` → *Practice Plus Group* | **best search term** (the trading brand) |
| `brandId` | `BD122` | groups sibling providers under one brand |
| `companiesHouseNumber` | `03462881` | verification signal (cross-check identity) |
| `website` | `null` | when present, the strongest match signal |
| `postalAddressTownCity` / `region` | `Bristol` / `South West` | disambiguation |
| `locationIds` | 125 ids | these are the *sites*, not what we want |
| `organisationType` | `Provider` | confirms this is a parent, not a location |

Matching tips:
- **Prefer `brandName` over `name`.** LinkedIn lists the trading brand ("Practice Plus
  Group"), not the Companies House legal name ("… Hospitals Limited"). Strip the leading
  `BRAND ` prefix CQC adds.
- If `website` is present, match its domain against the LinkedIn page — most reliable.
- Otherwise cross-check with town/region and, if needed, `companiesHouseNumber`.

---

## Step 2 — Resolve to the LinkedIn numeric id (via Phantombuster)

The robust, production method runs **inside Phantombuster**, logged in with our LinkedIn
`li_at` session cookie, so we get LinkedIn's real (client-rendered) pages from a
LinkedIn-friendly environment. It's implemented as an **ephemeral** custom phantom (create
→ run → delete; see [EPHEMERAL-WORKFLOW.md](EPHEMERAL-WORKFLOW.md)) so nothing persists.

The phantom does the whole "search companies → numeric id" primitive in a real browser:

1. `page.setCookie({ name: "li_at", ... })` — authenticate.
2. Go to `linkedin.com/search/results/companies/?keywords=<brand>` and take the first
   `/company/<vanity>/` result → resolves the parent company's **vanity + name**.
3. Open `linkedin.com/company/<vanity>/` (now fully rendered because we're logged in) and
   read the id from the DOM: `urn:li:fsd_company:<ID>` / `urn:li:organization:<ID>`.

Runtime that matters (learned from the docs + testing):

- Use the directive **`"phantom image: web-node:v1"`** → **Node 16 + Puppeteer bundled**
  (`require("puppeteer")`). The old `"phantombuster package: 5"` gives **Node 8 and no
  browser**, and LinkedIn's logged-in pages are client-rendered, so a headless browser is
  required — a plain HTTP GET of the company page returns an SPA shell with no id in it.

Run it end-to-end (CQC → id) with the packaged example:

```bash
python examples/cqc_to_linkedin.py 1-116865921
```

which drives [resolver/resolver_phantom.js](resolver/resolver_phantom.js) via
`resolver.resolve_ephemeral(...)` (a thin wrapper over `Phantombuster.run_ephemeral`).
**Tested output:**

```
CQC provider 1-116865921
  name : Practice Plus Group Hospitals Limited
  brand: BRAND Practice Plus Group  ->  search term: 'Practice Plus Group'
Resolving LinkedIn id via ephemeral phantom (search by name, authenticated) …
LinkedIn match:
  name      : Practice Plus Group
  vanity    : practiceplusgroup
  companyId : 68842389   <-- use in currentCompany=["68842389"]
```

**Numeric id = `68842389`.**

### Fallback: unauthenticated page scrape

Quick and dependency-free, but best-effort — LinkedIn often auth-walls or rate-limits by
IP, and doesn't render the same markup. Handy for spot checks:

```bash
UA="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 \
(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
curl -s -A "$UA" -L "https://www.linkedin.com/company/practiceplusgroup/" \
  | grep -oE 'urn:li:organization:[0-9]+|f_C=[0-9]+' | sort -u
# -> urn:li:organization:68842389
```

Note vanity slugs aren't predictable from the name: `practice-plus-group` (dashed)
**301-redirects** to the canonical `practiceplusgroup`. When picking the company from
search results, choose the **parent** company page and skip per-site ones
(`…/company/practice-plus-group-hospital-plymouth`, `…/showcase/ppg-emersons-green/`) —
those correspond to CQC *locations*, not the provider.

---

## Step 3 — Use the id

Plug it into a LinkedIn people search URL for the LinkedIn Search Export phantom:

```
https://www.linkedin.com/search/results/people/?currentCompany=%5B%2268842389%22%5D
```

(`%5B%22…%22%5D` is the URL-encoding of `["68842389"]`.) This is exactly the shape of the
existing phantom's saved argument, which used `currentCompany=["473831"]`.

---

## Caveats

- **Use a browser, not raw HTTP, when authenticated.** LinkedIn's logged-in company page
  is client-rendered — a plain GET returns an SPA shell with no id. Puppeteer
  (`web-node:v1`) renders it; that's why the phantom uses a real browser. (The old voyager
  JSON endpoints also need `JSESSIONID` + a matching `csrf-token`, not just `li_at`, so the
  DOM route is simpler.)
- **Keep the `li_at` cookie fresh.** It expires / can be invalidated. We reuse the cookie
  stored on the existing LinkedIn Search Export agent; supply your own via
  `LINKEDIN_SESSION_COOKIE` if needed.
- **Name ambiguity — always verify.** Brand vs legal name vs multiple LinkedIn entities:
  confirm the picked company against a CQC signal (website domain, town, or Companies
  House number). The phantom returns the matched `name` so you can sanity-check it.
- **One brand → many providers.** `brandId` (`BD122`) groups sibling CQC providers; they
  usually map to the *same* LinkedIn company id, so you can cache by brand.
- **Cost:** each lookup is one ephemeral phantom run (a few seconds of execution time).
  Batch and cache by `brandId` to stay economical.

---

## Verified summary

| Stage | Value |
|-------|-------|
| CQC provider id | `1-116865921` |
| CQC name | Practice Plus Group Hospitals Limited |
| CQC brand | Practice Plus Group (`BD122`) |
| Companies House | `03462881` |
| LinkedIn vanity | `practiceplusgroup` (dashed variant redirects here) |
| **LinkedIn numeric id** | **`68842389`** |
