# Auditing prices, sizes and stock across the nurseries

**Audience: an automated agent picking this up cold.** You are looking after a
price-comparison site that scrapes 7 online nurseries twice a day and
publishes a static site. Your job is to find and fix places where the site
**states something it has not checked** — a price that is not that size's
price, or a "buy" link for something nobody can buy.

Written 2026-08-11, after fixing two live defect classes. Everything here is
measured, not assumed. Where something is unverified it says so.

---

## Start here

```bash
git pull --ff-only          # the OneDrive copy lags CI; skip this and you audit stale data
python -m pytest -q         # expect a clean suite
python -X utf8 build.py     # rebuild site/ ; NEVER hand-edit site/
```

Then run the four offline audits in §4. They need no network and will scope
the problem in a couple of minutes. Only go to live pages (§5) once you have
a specific claim to check.

**Before you believe any number you produce, read §2.** It is the mistake this
project has made most often, and it produces checks that pass forever while
telling you nothing.

---

## 1. The shape of every defect found so far

Two live defect classes, both reported by a human clicking around for five
minutes, both systemic:

| | Symptom | Root cause |
|---|---|---|
| **Price/size** | "3 gallon $21.95" when $21.95 is the 1-gallon | labels and prices paired **by position**, not by a shared key |
| **Stock** | listed size leads to "Notify me when available" | the site had **no stock data** and guessed |

They share a shape: a value was **inferred** where it should have been
**read**. When you find a new defect, ask what was inferred.

---

## 2. Rule zero — never let the thing under test produce its own baseline

This project has committed this **four times**:

- a data gate comparing against a manifest the scrapers had already overwritten
- `verify.py` re-scraping through the parser it was verifying
- a health file no reader could ever reach
- an auditor joining on a `variant_id` the scraper itself wrote

A check whose baseline comes from the component being checked proves
**determinism, never correctness.** It passes forever.

Ground truth must come from outside the parser:

- the live page read by a human, or
- a deliberately *different* implementation — BeautifulSoup DOM traversal and
  `json.loads`, not the production regexes

Record it to a committed file. `fgt_ground_truth.json` is the worked example:
37 size rows, each independently cross-checked against that page's own
schema.org Offer block.

**Corollary: a check that finds nothing may have checked nothing.** A
cross-page audit here once reported `checked=0 mismatches=0` — a clean result
caused by a wrong CSS selector. **Always print the denominator.**

---

## 3. Stock: what the site knows, and what it does not

### 3a. Where stock comes from (Shopify)

| endpoint | has `available`? | price format |
|---|---|---|
| `/products/{handle}.json` | **NO** | dollar strings `"34.95"` |
| `/products/{handle}.js` | **yes** | **CENTS** `3495` |

Two traps:

1. The `.json` endpoint has no stock field at all. The scraper used to fill
   the gap by guessing, including a rule that treated any variant titled
   "ships in spring" as in stock. Measured: spring-hill asserted availability
   and was wrong **48 times out of 52**. "Ships in Spring" describes *when an
   order ships*, not *whether one can be placed*.
2. `.js` prices are in cents. Swapping wholesale would multiply every price on
   the site by 100. **Take only the boolean from `.js`.**

`ShopifyScraper.fetch_availability()` (`scrapers/shopify.py:200`) does this
correctly: separate fetch, boolean only, `{}` on any failure. Fast Growing
Trees blocks both endpoints, so it derives stock from the page's own
schema.org Offers matched by price (`_availability_by_price`,
`scrapers/shopify.py:825`).

### 3b. Stock has THREE values, and unknown is not sold out

```
True   -> buyable
False  -> sold out, do not link it
None   -> UNKNOWN. We did not check. Show it, but do not assert.
```

Unknown is the majority. As of 2026-08-11, per-variant stock in the latest
stored data:

```
retailer                  rows  in_stock=False   per-variant available
fast-growing-trees          66              13   {'False': 60, 'True': 137}
great-garden-plants          6               0   {'None': 8}
nature-hills                78               0   {'None': 147}
planting-tree               75               0   {'None': 322}
proven-winners-direct       11               0   {'None': 21}
spring-hill                 38               0   {'None': 27, 'True': 52}
stark-bros                   8               0   {'True': 13}
```

**Any change that treats `None` as unavailable takes most of the catalogue
dark.** Test that path explicitly every time.

### 3c. That table is PRE-FIX — do not read it as the steady state

Those `None`s are stored data produced by the *old* scraper. The fix calls
`fetch_availability()` on both code paths, so Shopify retailers should start
reporting real booleans. Verified live for planting-tree (one request):

```
planting-tree /products/pink-lemonade-blueberry-bush.js
   43102233604    -> True     <- the variant our link points at
   5 other variants -> False
```

Our stored row for that plant shows **five buyable tiers**. After the next
scrape most of them become sold out. This is the mechanism behind the
user-reported "plantingtree.com has a bunch where it says notify me when
available".

**Open task for you:** the same live check has not been run for
`nature-hills`, `proven-winners-direct` or `great-garden-plants`. One `.js`
fetch each (spaced, see §5) will tell you whether the fix reaches them or
whether they need a different source. Do this before assuming stock coverage
is solved.

### 3d. Row-level and variant-level are different facts

Three distinct states, easy to conflate:

- **variant sold out** — this size is gone, others may be fine
- **row sold out** (`in_stock: false`) — the whole retailer entry is out
- **unconfirmed** — we have failed to reach this retailer for 3+ consecutive
  runs (`count_consecutive_run_misses`, `build.py:389`)

The third is *not* the same claim as the first two. Great Garden Plants rows
displayed "Currently Unavailable" **while still rendering live affiliate
links** to their prices. Those cells now say "Not confirmed", not "Sold out",
because we did not check — asserting sold-out there would be the same
overclaim in the other direction.

Beyond 30 days the row is dropped entirely (`entry_is_stale`, `build.py:542`).

### 3e. One rule, one implementation

`displayable_price()` (`build.py:515`) has a docstring recording that its
logic once existed in **four copies that drifted apart**. A fifth was added
during this session, in the Jinja template, as `available == false`. That is
not the same test as `available is False` — **Jinja's `==` makes `0` and
`0.0` equal to False.** The result was the desktop table calling a size sold
out while mobile still offered it.

The rule now: `build.py` computes flags once per size, the template reads
them. **Never re-derive a rule in a template.**

```
is_buyable       build.py:748   variant stock AND row stock AND not stale
row_sold_out     build.py:843   in_stock is False, precomputed for the CSS class
```

If you add a consumer of prices, read `is_buyable`. Do not write your own test.

### 3f. Claims and content are different questions

```
offer_count          buyable offers  -> "N Nurseries" title, schema offerCount
priced_offer_count   any real price  -> whether the page is worth indexing
```

These were one field. That meant a plant sold out everywhere lost its schema
block and dropped out of `sitemap.xml`, then reappeared when stock returned —
index flapping on a routine seasonal state. Keep them apart.

---

## 4. Offline audits — run these first

No network. Each returns a work-list, not a verdict.

**A. Cross-retailer outlier.** For each (plant, tier) with 3+ nurseries,
compare each price against the median of the *others*. A "3 gallon" costing a
third of everyone else's is probably not a 3 gallon.

**B. Two-nursery pairs.** Most tiers only have 2 nurseries, so no median
exists. Flag pairs ≥2.5x apart. You cannot tell which side is wrong, but it
is a lead. **The first version of this audit skipped these and therefore
could not see the azalea that started the whole investigation.** Do not skip
them.

**C. Within-retailer inversion.** A larger container priced below a smaller
one at the same nursery. Compare **container tiers only** — bare-root vs
potted inversions are real pricing, not defects.

**D. Snapshot diff.** Compare two committed snapshots of the same plants.
This is what exposed the positional bug — prices had slid onto *adjacent*
labels:

```
delaware-valley-white-azalea  OLD {1gal:21.95, 3gal:42.95}  NEW {3gal:21.95}
coral-bark-japanese-maple     OLD {3-4:84.95, 4-5:98.95, 5-6:120.95, 6-7:170.95}
                              NEW {3-4:84.95,            5-6:94.95,  6-7:120.95}
```

**A pure shift leaves the tier COUNT unchanged. Compare values, not counts.**

**E. Cross-page agreement.** Every price one page quotes about another must
equal that page's own `lowPrice`. 565 such quotes exist —
`.similar-price` (product→product) and `.related-price` (guide→product).
This catches the widget-vs-page divergence, which this codebase has now had
three times. Print the denominator.

**F. Stock-specific sweeps:**
- rows where `in_stock` is False but sizes still render a price link
- sizes where `available is False` that appear in `mobile_tiers`, carry
  `is_best`, or feed `same_tier_savings`
- retailers whose per-variant `available` is uniformly `None` (candidates for
  §3c)
- pages where schema says `InStock` but no size is buyable

---

## 5. Live checks — politeness is not optional

The affiliate relationships depend on not being banned.

- **10–15 s between requests to one host.** Cap the run; 12 pages was enough
  to establish ground truth for FGT.
- **Fetch each page once, cache the HTML to disk, iterate against the cache.**
  Never re-fetch a page you already have.
- **On 429 or 403, stop entirely.** Do not back off and continue.
- Go through `scrapers/polite.py` so robots.txt and the user-agent are
  honoured. `_scrape_product_html` calls `is_allowed_by_robots` first — if you
  mock the session but not that, every call returns `None` and you will
  misread it as a parser failure.
- Tests must **never** hit live sites. Mock at the requests/urllib boundary.

---

## 6. Failure modes to design against

**Fail loudly, or the fix rots.** The FGT parser is correct today but reverts
to positional pairing the moment the markup drifts — and FGT's format has
already changed once. Nothing would notice: `runner.py` scores health as
`products_found / products_expected`, so a **wrong-but-present** product still
counts as a hit and the manifest keeps reporting `healthy`.

> **A missing product trips an alarm. A wrong price trips nothing.**

So when a page clearly has a size selector but not one size can be read out
of it, publish nothing for that product. Measured on the cached pages,
mutating only aria-label typography: without the guard, 2 phantom rows were
published (`$143.95` and `$160.95` for offers that do not exist); with it, 0
phantom rows and 2 products withheld.

**Waking dormant code is a change.** Passing `raw_size` through to the
template switched on a "Ships in Spring" detector that had never run. It took
the first matching variant and rendered it as a whole-**row** badge:

```
Emerald Green Arborvitae, Spring Hill   badge: (Ships Spring)
   1-2ft    $19.99   "Ships Year-Round"   <- what most visitors buy
   bareroot $90.99   "Ships in Spring"    <- the only one the badge described
   12-18in  $19.99   "Ships in Fall"      <- five more like this
```

14 of 23 badges contradicted their own row, and the value depended on scraper
key order. If your fix makes dead code live, that code is now part of your
change.

**Row-level facts are per-variant facts' superior.** Anything that gates on a
size must also respect the row.

---

## 7. Verifying a fix

Passing tests are context, not evidence. LLM-written tests routinely pass
while the feature is broken.

1. **Prove the test fails without the fix.** Restore the pre-fix file with
   `git checkout <sha> -- <path>` and re-run. If it still passes, the test is
   worthless. This caught two worthless tests in one session — one asserting
   on a *condition* rather than the behaviour, and one where the fix was
   already committed so there was nothing to revert.
2. **Never `git stash` in these worktrees.** They share a repo with unrelated
   pre-existing stashes. A `pop` with nothing of yours to pop restores
   someone else's and leaves ~113 conflicted files.
3. **Measure before and after with real numbers**, against ground truth the
   parser did not produce. `26/37 → 37/37` is a result; "looks right" is not.
4. **Probe the worst case.** Marking all 183,775 variants sold out: build
   survived, 102/102 pages noindexed, 0 clickable prices, 0 sitemap URLs.
5. **Sweep the call sites** of anything whose data shape changed. The
   pre-enrichment loop was missed and produced `$23.99` in guides against
   `$24.95` on the plant's own page.
6. **A scraper fix without a display fix may be inert.** The proof that
   mattered most in this session: feeding *true* sold-out data through the
   unfixed display layer produced a **byte-identical page**. Always check the
   fix reaches the rendered output.

---

## 8. Known-remaining, roughly prioritised

1. **Stock coverage unverified for 3 retailers** — nature-hills,
   proven-winners-direct, great-garden-plants (§3c). Highest value: it is the
   difference between "stock is solved" and "stock is solved for 4 of 7".
2. **proven-winners-direct accuracy ~21%** — 23 of 126 scrape days change
   ≥50% of the catalogue at once, which is a sale banner being read as a
   price change rather than 60 plants repricing overnight.
3. **23 of 87 multi-retailer plants compare different cultivars** and make
   savings claims across them. Cultivar identity is unsolved.
4. **`verify.py` is a self-comparison** (§2) — retire it or re-base it on
   independent ground truth.
5. **Price-history chart plots min-across-tiers**; 54 of 262 series switch
   tier mid-line, so a "price drop" may be a size change.
6. **61 phantom `variant-*` rows** in stored data. Not visible today (they
   land in the hidden `default` tier) but they age off rather than being
   corrected.
7. **FGT ground truth covers 12 of 68 plants.** Mechanism confirmed; the
   other 56 are not individually verified.

---

## 9. The process that worked

Plan → independent red team on the plan → build → independent red team on the
result. Four adversarial passes ran; **every one found something real, and two
found defects introduced while fixing the previous round.** That is the
argument for the loop rather than a single review.

When you commission a review: give it the cached artefacts, forbid live
fetches, tell it §2 explicitly so it checks for that, and require command
output for every finding.

Then **verify what it tells you.** One pass overstated a finding (claimed 61
phantom rows render as "Best Available"; that string appears **0 times** in
the built site). Another reported a blocking defect that existed only because
it was reviewing one branch in isolation — the fix was on the branch it would
merge into. Neither was acting in bad faith; both were reasoning from partial
information, which is the normal condition. So is yours.
