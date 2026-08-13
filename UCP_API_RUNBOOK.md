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

### THE IMPORTANT PART: look up by variant ID, not by search

**Added 2026-08-13 after measuring all five non-FGT retailers. This supersedes
the search-first approach implied below.**

`lookup_catalog` accepts **Shopify GIDs, up to 10 per call**. Our price rows
already store `variant_id`. Feed them back as
`gid://shopify/ProductVariant/<id>` and you get the exact variant — price,
availability, sku — with **no label matching whatsoever**. It returns only the
matched variant, but `product.options` still carries the full label list.

Why this is the path to build on:
- **60 calls refreshes all 577 cells across five retailers, versus 426 HTTP
  requests the scrape makes today — an 86% traffic reduction.**
- Immune to the 10-variant search cap AND to the search-relevance problem.
- It is what made the oracle numbers exact rather than approximate.

It cannot DISCOVER new variants, so pair it with a low-frequency
`search_catalog` discovery pass (213 calls, weekly ≈ 30/day). Steady state
≈ 90 requests/day against 426 today.

**Search-by-handle is unreliable and must not be the primary key.** Measured
match rate 151 of 197 (76.6%) — but **41 of the 46 misses are products the API
demonstrably holds**, proven by resolving their variant IDs. Querying the
display name recovered only 1 of 12 retries. Shopify catalog search will not
reliably surface a specific known product. This is almost certainly the
explanation for FGT's unexplained 49-of-68 too.

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
3. ~~**No compare-at / list price.**~~ **CORRECTED 2026-08-13 — this was an
   FGT-and-planting-tree-only result that I wrongly generalised.**
   `list_price` IS returned by 4 of 6 retailers: spring-hill 79/79 (14 real
   discounts), proven-winners-direct 21/21 (19 real), nature-hills 18/147,
   great-garden-plants 2/8. **Only planting-tree returns none (0 of 319)**,
   matching FGT. Was-price and sale detection ARE available on this path for
   most retailers.

### Rate limits — CORRECTED 2026-08-13

The original text said "no rate-limit headers are advertised, ceiling
unknown". Headers are still not advertised, but the ceiling is real and one
retailer enforces it hard:

- **planting-tree refuses after roughly 93 calls** with
  `HTTP 429 / -32000 "Too many requests, please retry after 1933 seconds"` —
  a **32-minute lockout**. Honour the `retry after N seconds` payload and
  ABANDON that retailer for the session. Do not retry into it: a naive
  3-attempt retry policy burned 42 refused requests before the error was
  recorded.
- **nature-hills tolerated 97 calls** in the same session without complaint.
- The other four were never pushed hard enough to find a ceiling, and
  deliberately so — probing means provoking a 429 against someone who has
  been nothing but accommodating.
- Unknown: the window length, and whether the bucket is per-IP, per-profile
  or per-shop.

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

---

## 11. Measured across the five non-FGT retailers (2026-08-13)

**The FGT failure is LOCAL, not systemic.** Keyed on stored Shopify variant
IDs so a disagreement is a real disagreement, not a label-matching artefact:

| retailer | cells | agree on price AND stock | price differs | stock differs |
|---|---|---|---|---|
| spring-hill | 79 | 79 | 0 | 0 |
| nature-hills | 147 | 146 | 0 | 1 |
| planting-tree | 319 | 316 | 0 | 3 |
| proven-winners-direct | 21 | 15 | **6** | 0 |
| great-garden-plants | 8 | 8 | 0 | 0 |
| **total** | **574** | **564 (98.3%)** | **6** | **4** |

Our data already carries sold-out cells everywhere. Nothing resembling FGT's
"121 of 121 in stock". Stock totals track within one cell per retailer.

### Two live defects this surfaced, both unrelated to FGT

**1. nature-hills exposes `Form Type` as a SEPARATE option dimension, and we
collapse it.** On `hydrangea-lime-light`, 2 forms x 6 sizes:

```
Shrub / #3 Container            $ 80.92  <- absent from our data entirely
Tree  / #3 Container | 3-4 ft   $123.88  <- what we publish as "3gal"
```

Our 3-gallon column for that plant carries the **tree-form** price, competing
against every other nursery's ordinary 3-gallon shrub. Same bug class as the
FGT multi-stem collapse that `394da845` fixed, at a different retailer, via a
dimension the scrape cannot even see — the API returns all six in one
response. `394da845` handles multi-stem/jumbo/premium/bareroot correctly;
**tree form is the gap it does not cover.**

**2. proven-winners-direct: 6 cells publish the PRE-DISCOUNT price**, ~33%
high. Our figure equals the API's `list_price` exactly with our `was_price`
null. Arbitrated against the live page: JSON-LD says $29.99/$15.74 InStock;
we publish $39.99/$20.99. **Cause not established** — a promotion may have
started between our 12:59 scrape and the read, but `little-lime` is genuinely
undiscounted in the API, which argues against a simple site-wide sale switch.
Re-running the PWD scraper and diffing settles it in one pass.

Also found: planting-tree `miscanthus-morning-light` is **delisted** — handle
returns no match, all three variant IDs `not_found`, our row is 104 days old,
and we are still publishing it.

### Size-label vocabulary — it is NOT always "Size"

Four distinct option names across five retailers: `Select Size` +
`Select Quantity` (spring-hill), `Plant Size` + `Form Type` (nature-hills),
`Size` (planting-tree, PWD, GGP), plus `Ship Week` at PWD, plus one product
whose option is named after the product (`Hass Avocado Tree`).

Distinct size labels: spring-hill 42 (messiest by far), planting-tree 26,
nature-hills 17, PWD 4, GGP 2.

**7 labels do not map cleanly onto `_normalize_size`**, two of them losing a
form qualifier: spring-hill `4-5 FT TREE FORM` -> `4-5ft`, nature-hills
`#3 Container - Tree Form` -> `3gal`. Others fall through to the Step-9 slug
fallback: `2.5" POT`, `6" STARTER POT`, `3-4' BOGO`, `0.65 Gallon`, and
planting-tree `6 Inch` vs `6 Inch Pot` which puts one physical size in two
columns.

### Migration order, by value over risk

1. **nature-hills** — 79 products / 147 cells, largest clean win. 146 of 147
   already agree, no truncation, no rate limiting at 97 calls, cleanest
   vocabulary. Also the only way to fix the tree-form defect above.
2. **great-garden-plants** — same change. 7 products, flawless agreement;
   use it as the pilot that proves the code path.
3. **proven-winners-direct** — small, but the only retailer where we publish
   wrong prices today. Diagnose the 6 cells FIRST; migrating would mask the
   cause rather than explain it.
4. **spring-hill** — works, but expensive: two option dimensions, 42 messy
   labels, quantity-bundle filtering, and the only real 10-variant truncation.
5. **planting-tree — last.** Largest cell count but the only retailer that has
   refused us, the only one with no `list_price`, and the one our existing
   data already matches best (316 of 319). Lowest benefit, highest risk.
   Requires solving the rate limit first.
