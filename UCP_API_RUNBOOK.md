# UCP / MCP catalog API — runbook

**Written 2026-08-13.** Everything here was executed and verified on that date,
not inferred. If a claim below is not accompanied by "verified", treat it as
unverified.

This exists because six of our seven active retailers publish an official
catalog API, and getting into it took several wrong turns that would otherwise
have to be rediscovered. Read this before writing any UCP code.

---

## 1. Who has it

Verified by fetching `/.well-known/ucp` on all seven active retailers:

| retailer | UCP profile |
|---|---|
| spring-hill | 200 |
| nature-hills | 200 |
| planting-tree | 200 |
| fast-growing-trees | 200 |
| proven-winners-direct | 200 |
| great-garden-plants | 200 |
| **stark-bros** | **404 — non-Shopify, stays on HTML scraping** |

Fast Growing Trees' own `robots.txt` states that agents should use UCP/MCP for
catalog rather than scraping the storefront, and their `/agents.md` says to
prefer it "over screen-scraping". We are not working around anyone here; we
are using the interface they published and asked for.

## 2. Our agent profile

Live at `https://www.plantpricetracker.com/.well-known/ucp-agent.json`
(source: `site/.well-known/ucp-agent.json`, shipped in `818741f4`).

**Read-only by construction.** It declares only
`dev.ucp.shopping.catalog.search` and `dev.ucp.shopping.catalog.lookup`. It
does NOT declare cart, checkout, order, discount, or any `payment_handlers`,
so capability intersection cannot grant this agent anything that transacts.
**Keep it that way.** If a future change needs a new capability, that is a
decision for the owner, not a convenience edit.

It carries an Ed25519 public key, `kid: ppt-2026-08-13`. **The private key is
not in this repo.** It was generated outside the tree. Nothing signs anything
today; read-only catalog calls do not need it. If webhook signing ever becomes
necessary, the private key belongs in GitHub Secrets, never in the repo.

`site/vercel.json` sets `Cache-Control: public, max-age=300` and
`application/json` on the profile path. The spec REQUIRES `public` with
`max-age >= 60`, forbids `private`/`no-store`/`no-cache`, and forbids serving
the profile behind a 3xx. Do not "tidy" those headers.

## 3. How to call it — the parts that cost time

### Endpoint
Take the MCP endpoint from the retailer's `/.well-known/ucp` discovery
document. It is a `*.myshopify.com` origin, NOT the storefront domain — some
storefronts sit behind Cloudflare and will not serve the API host. Note that
`ucp.services["dev.ucp.shopping"]` is a **list**, not an object.

### Request shape
```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"search_catalog",
   "arguments":{"meta":{"ucp-agent":{"profile":"<our profile URL>"}},
                "catalog":{"query":"nellie stevens holly"}}}}
```

Two things that are easy to get wrong and produce identical unhelpful errors:

- The profile goes in **`params.arguments.meta['ucp-agent'].profile`**. It is
  NOT `params._meta`, NOT `params.meta`, NOT `arguments._meta`, and not any
  other placement — eight variants were tried and all returned
  `Missing profile uri`.
- **BOTH** the HTTP header `UCP-Agent: profile="<url>"` **and** the `meta`
  field above are required. Sending the meta without the header returns
  **HTTP 422**. This is not documented anywhere obvious; it was found by
  removing the header and watching a working call break.

### Error meanings
| error | cause |
|---|---|
| `invalid_profile_url` / `Missing profile uri` | profile not supplied where the server looks — see above |
| `profile_malformed: Invalid capability structure` | our profile is reachable but wrong; capability values must be **arrays** of version objects, and the catalog capabilities are named `dev.ucp.shopping.catalog.search` / `.catalog.lookup`. There is no bare `dev.ucp.shopping.catalog` |
| HTTP 422 with no body detail | usually the missing `UCP-Agent` header |

Authoritative reference profile to diff ours against:
`https://shopify.dev/ucp/agent-profiles/examples/2026-04-08/valid-with-capabilities.json`
Docs: `https://shopify.dev/docs/agents/catalog/storefront-catalog`

## 4. What comes back

Per variant: `id` (a `gid://shopify/ProductVariant/...`), `sku`, `title`,
`price {amount, currency}` where **amount is in MINOR UNITS** (2195 = $21.95),
`availability.available` (boolean), `options [{name,label}]`, `media`.

Product level: `handle`, `url`, `title`, `price_range`, and `options` listing
**every** size label the product has.

**Size labels arrive verbatim and distinct** — "1 Quart" and "2 Quart" are
separate options with their own price and stock. There is nothing to normalise
out of free text and no collision to resolve. This is the single biggest
reason to be on this path.

### Three limits, verified
1. **`search_catalog` returns at most 10 variants per product.** Nellie
   Stevens Holly has 12 sizes; two were silently absent. **This is
   detectable** — `product.options` still lists all 12 — so always compare the
   option-label count to the variant count and top up. A migration that skips
   this check will silently drop sizes and nothing will complain.
2. **`get_product` returns only ONE variant**, the selected one. To fetch a
   specific size:
   `catalog: {"id": "<product gid>", "selected": [{"name":"Size","label":"6-7 Feet"}]}`
   Verified: asking for "6-7 Feet" returned exactly that variant.
   Measured across current data: only **1 of 274** tracked (plant, retailer)
   rows on UCP retailers has more than 10 sizes, so the top-up cost is about
   one extra call per full pass.
3. **No compare-at / list price.** `list_price_range` came back as 0 and
   variant `list_price` as null, so **was-price and sale detection are not
   available on this path.**

**No rate-limit headers are advertised.** Three sequential calls took 1.9s with
no throttling. The ceiling is unknown — stay conservative, sequential, >=1.5s
between calls, and back off hard on 429/503.

## 5. Why this migration exists — the FGT measurement

Run on 2026-08-13 across all 68 tracked FGT products.

| | in stock | sold out |
|---|---|---|
| what our site publishes | **121 of 121** | 0 |
| FGT's own API | 136 | **142** |

The live product page corroborates the API: 22 `OutOfStock` markers against 5
`InStock`. **We show every FGT product as available; roughly half are not.**

Prices are systematically low. On every cleanly matched size label:

```
bing-cherry 5-6ft    FGT $168.95   ours $153.95
fuji-apple 5-6ft     FGT $109.95   ours  $99.95
honeycrisp 4-5ft     FGT $129.95   ours $117.95
honeycrisp 5-6ft     FGT $153.95   ours $139.95
pink-lemonade 2gal   FGT  $48.95   ours  $44.95   <- live page says $48.95
```

Consistently ~10% under. **Cause not yet diagnosed** — was-price, member
price, stale value, or wrong element. Diagnosing it is part of the migration
plan.

### Caveats on that run, stated plainly
- Search-by-handle matched **49 of 68** products. The other 19 are an
  unresolved question about the query, not proof FGT delisted anything.
- The large "sizes in API but not in ours" gap is mostly label-format
  difference, not genuine absence. Do not cite it as evidence.
- The price finding rests on 5 cleanly matched labels; all 5 agree in
  direction and one is confirmed against the live page.

### The oracle result worth repeating
For planting-tree / nellie-stevens-holly, API vs our published data:
**11 of 12 sizes matched exactly.** The one disagreement was "1 Quart" $21.95
available, missing from our data — precisely the bug the owner found by eye.
Two independent sources, one disagreement, and it was the real one.

## 6. Feeds vs a live API — a distinction that matters

A merchant *feed* (Google Merchant Center, affiliate datafeeds) is a batch
export on its own refresh cycle and genuinely drifts from the live site; that
is why Google's mismatch-disapproval machinery exists. **UCP is not that.**
Measured here, an API response matched the live product page on the same
minute, and the stale source was our own scrape.

That does not retire the concern — it argues for the same architecture either
way: **two independent sources, with disagreement as the signal.** Keep the
scraper. On 2026-08-13 the disagreement caught *us* being wrong.

## 7. Intended architecture

- The API becomes the **published source** for a retailer, feeding the
  EXISTING pipeline: the same `data/prices/*.jsonl` row shape written at
  `scrapers/runner.py:~557`, the same `build.py`, the same audits and sanity
  gate. It is a new **source**, not a new **destination**. Do not write to
  `site/` directly and do not bypass the gates.
- The HTML scraper is **not deleted**. It runs against a small daily sample
  (order 10-15 products), writing to a shadow location that never reaches the
  site. The API-vs-scraper disagreement rate is the health metric.
- **Total retailer traffic must stay below today's.** Today is roughly 548
  requests across UCP retailers. API-only is ~275. API plus a sampled shadow
  scrape is ~300. Shadow-scraping everything would be ~820 — more load than
  today, for no extra signal. Do not do that.
- Rationale for keeping the scraper alive: API access is explicitly revocable
  ("merchants MAY enforce additional rules"), and a scraper that never runs
  rots silently and fails when it is most needed.

## 8. Traps that have already bitten

- **Agent `.output` files can be written 0 bytes.** All three subagent report
  files on 2026-08-13 were empty; the reports existed only in notifications.
  An agent told to read one worked blind on half its input. **Check
  `ls -la` on any agent output file before relying on it.**
- A query-string cache-buster does **not** bust Vercel's cache for static
  files — `?cb=` returns HIT with the same ETag. Compare served bytes against
  `git show origin/main:site/...` instead.
- Two agents given "different branches" but the SAME worktree path collided
  and mixed their edits. Give each agent its own `git worktree add` path.
- PowerShell: no heredocs (write the message to a file and use
  `git commit -F`), no `&&`, no `grep`. The Bash tool has grep.

## 9. Reproducing any of this

Probe scripts written 2026-08-13 (session scratchpad, may not survive —
the calling convention in §3 is the durable part):
`ucp_probe.py` (single retailer), `fgt_oracle.py` (all FGT + comparison).

Minimum viable check that the profile still works:
```
POST <endpoint>  with the §3 body and BOTH the header and meta
```
A 200 with `structuredContent.products` means the profile is valid and
reachable. `profile_malformed` means our profile changed or the spec moved.

## 10. Standing constraints

- **The owner approves every deploy.** Agent work ends at "ready to ship plus
  evidence". Never push to `main` without explicit approval.
- Every fix must be proven with executed evidence, not asserted.
- Every change is red-teamed by an INDEPENDENT agent before it ships.
- Be respectful on the API: sequential, >=1.5s apart, honest user agent,
  never more traffic than the scraper it replaces.
