# GAIA FINAL PLAN — correctness first, then autonomy

Version 1.0, 2026-08-12. Supersedes AUTONOMY_PLAN.md, which an independent
red team reviewed and marked NEEDS-REVISION (12 findings). Every finding is
folded in below; the largest was that the draft deferred LIVE FALSE
STATEMENTS (cross-cultivar savings claims, PWD promo prices, chart tier
mixing) to a late phase, against the owner's stated priority. Those move to
Part 1.

Owner: Brandon. Solo, non-developer, wants hands-off operation. His stated
priority order: (1) site correct — prices, sizes, availability; (2) autonomy
with minimal day-to-day input.

---

## HOW THE WORK RUNS — the loop operating agreement

Every phase below is executed as a LOOP:

```
work a batch -> run the phase's EXIT CRITERIA (commands, pass/fail)
            -> independent red team attacks the result
            -> all green: phase complete, write phase report, STOP for Brandon
            -> anything red: fix and repeat
```

**Mode:** in-session autopilot (/loop). Brandon starts a phase with one
pasted message; the loop self-fires until done/stuck/blocked.

**Model:** all loop build agents pinned to **Opus, high effort — never
Fable** (Brandon's explicit instruction). Session starter text includes
`/model claude-opus-5`. Red-team gate agents may run on the session default.

**Kill switches (enforced, not aspirational):**
1. `STOP` file in the repo root — every loop round checks for it FIRST and
   halts if present. Brandon can also interrupt the session at any time.
2. No-progress rule: two consecutive rounds with an identical exit-criteria
   scoreboard force stop-and-report. "Trying again" is not progress.
3. Iteration cap: 8 rounds per phase. Cap hit = stop with a written account
   of what was tried and why it failed.
4. Do-not-touch list, absolute: no push to `main` (deploys happen ONLY via a
   command block Brandon clicks Run on); no HTTP to retailer sites outside
   scrapers/polite.py discipline; no spending; no account creation; no
   affiliate applications.
5. Deploy gate: phase completion NEVER implies deployment. The loop ends at
   "ready to ship + evidence"; Brandon approves every deploy.

**Status file:** `LOOP_STATUS.md` in the scratchpad — phase, round, criteria
scoreboard, last change. Brandon checks in when he wants; no alerts pushed.

---

## ENGINEERING RULES — added 2026-08-12 after two UNSAFE verdicts

Every defect this session was introduced BY FIXING SOMETHING ELSE, after a
review had already passed. The plan gated phases; defects arrive between
gates. These rules exist because each was paid for.

**R1. Re-gate after fixes.** A phase is not green when the red team passes.
It is green when the red team passes ON THE COMMIT THAT SHIPS. Any fix made
in response to a finding re-triggers the gate. Fix-after-review is the
highest-risk code in the project — written fast, under pressure, by someone
who just demonstrated they were wrong — and it was getting the least review.

**R2. Guard-removal rule.** Removing or weakening ANY check requires, in the
same change:
  (a) the replacement control demonstrated FIRING on the exact scenario the
      removed guard handled — a command and its non-zero exit, not prose;
  (b) a test that fails if the replacement is disabled.
Twice today a guard was removed with the justification "X covers this." Both
times X did not. The sanity gate cited as cover was structurally incapable of
firing — it compared the run against itself, 735 prices, 735 exactly equal.

**R3. Claims register.** Every commit-message assertion of the form "X is
covered by Y" is a line item the gate must verify with a command. The two
worst defects of the session were false sentences, not wrong code, and code
review does not read sentences.

**R4. Test the artifact, not the workspace.** A green local run is not
evidence about a commit. `git checkout <sha> -- <path>` — used to prove a
test is load-bearing — ALSO STAGES the old file; restoring with `cp` fixes
disk and leaves the index poisoned. That shipped a silently reverted
runner.py while pytest reported 474 green against the fixed file on disk.
Before any commit following a checkout-based probe: `git diff --cached`, and
confirm CI is green on the pushed SHA.

**R5. Metrics must not be satisfiable by the failure mode.** Ask of every
health number: what is the worst outcome that still scores well?
`products_found` counted products the scraper could not read one price from,
so a retailer with zero readable prices on 68 pages scored 100% healthy.

**R6. Publishing a fact must never silence a signal.** Recording "sold out"
and raising the drift alarm are independent; collapsing them turned a loud
failure quiet. If an action suppresses an alarm, that suppression is the
change under review, not a side effect of it.

**R7. Re-derive the safe default when reusing a predicate.** `_is_orderable`
was written to gate SHOWING a price, where failing closed merely hides
something. Reused to decide PUBLISH-AND-SILENCE, failing closed invents a
fact. Same function, inverted consequences.

**R8. Mutation-test the tests.** Break the implementation N ways and confirm
the suite kills each. Two mutants survived all 474 tests. This is a stronger
signal than coverage and costs minutes.

**R9. Calibrate before enabling a dormant check.** Turning on a check that
has never fired trades silence for a possible wedge. Replay real history
first: 128 cycles, worst genuine movement 4.5% against a 30% threshold.

**R10. Print the denominator.** A check that finds nothing may have checked
nothing — a cross-page audit once reported `checked=0 mismatches=0` from a
wrong selector, and a mutation run reported "2 passed" for every mutant
because the harness silently no-op'd.

**Phase report (end of every phase):** tokens per spawned agent (from
harness task accounting), model used per agent, rounds to green, rework
ratio (findings by red teams / total findings), wall-clock. Main-session
token totals come from /cost, which Brandon can run himself; agent-level
numbers are exact.

---

# PART 1 — MAKE THE SITE CORRECT

## Phase C0 — ship the verified fixes (days)

The availability + FGT size/price work is built and has survived five
adversarial passes. Get it live without breaking anything.

Tasks:
1. Complete the FGT re-scrape with the corrected anomaly guard (in flight).
2. Merge `merge-test` into `main` with an explicit strategy (red team F10:
   main moves 2x/day under us and is already ahead):
   - take main's `data/` for both-appended JSONL files (union of appends)
   - do NOT hand-resolve `site/` conflicts — regenerate site/ from merged
     data with `python -X utf8 build.py`
   - land between scheduled scrape runs
3. Purge the 61 phantom `variant-*` rows (trivial, was misfiled as later).
4. Brandon clicks Run on the push. Then spot-check live pages
   **with cache-busting query strings** (F9: HTML is CDN-cached 24h;
   an un-busted check can pass or fail spuriously).
5. Write a one-page ROLLBACK RUNBOOK (F9): exact `git revert` command block
   for Brandon + where the Vercel dashboard rollback lives. Nobody has
   written down how to undo a bad deploy; that is not acceptable before
   deploying gets easier.

EXIT CRITERIA (all must pass):
```
python -m pytest -q                     -> 0 failed
ruff check                              -> clean
python -X utf8 build.py && git status --short site/   -> empty (committed site == fresh build)
python size_audit + crosscheck2.py      -> 0 cross-page mismatches, denominator printed and > 500
grep phantom variant- rows in latest data -> 0
live spot-check (cache-busted), 5 pages: sold-out sizes unlinked; pink-lemonade 1gal $45.95 class of checks against data
independent red team on the merged deploy candidate -> PASS
```
Owner involvement: one Run click for the deploy; read the phase report.

## Phase C1 — stop the false statements (days)

Red team F1: these are not "credibility polish", they are the site asserting
things that are not true, today. The MODELS to fix them properly are hard;
SUPPRESSING the claims is cheap. Suppress now, model later (maybe never —
suppression may simply be correct).

Tasks:
1. The 23 multi-retailer plants comparing different cultivars: stop the
   cross-retailer savings claim on those pages (keep the per-retailer price
   listings; kill the "save N%" line and same-tier hero eligibility).
2. proven-winners-direct promo flips (~21% accuracy): exclude PWD from
   best-price highlights and savings claims until its promo handling is
   rebuilt. Its prices still display, labelled as of last check.
3. Price-history chart: stop plotting min-across-tiers where the series
   switches tier (54/262 series); plot per-tier or annotate the switch.
4. Re-run the offline audit suite; verify no NEW false claim classes.

EXIT CRITERIA:
```
scripted check: 0 of the 23 cultivar-mismatch plants renders a cross-retailer savings claim
scripted check: 0 best-price highlights attributed to proven-winners-direct
scripted check: 0 price-history series mixes tiers without annotation (denominator printed)
python -m pytest -q -> 0 failed; build clean; site/ diff reviewed
independent red team, prompt: "find any remaining statement on any page that the data cannot support" -> PASS
```
Owner involvement: one Run click; read the report.

**After C1 the site makes no claim it has not checked. That is Brandon's
"most important thing" delivered, and everything after this is keeping it
true without him.**

---

# PART 2 — MAKE IT RUN ITSELF

## Phase A0 — nightly offline audits in CI (this week; highest value/hour)

Red team F5: the draft plan's claim that only a live verifier catches
unpredicted defects was FALSE — the snapshot diff caught the FGT positional
bug offline, free, unbannable. Wire the proven audits into scrape.yml as
nightly alarm steps: cross-retailer outlier, two-nursery pairs,
within-retailer inversion, snapshot value diff, cross-page agreement,
stock-consistency sweeps. Each prints its denominator (a check that finds
nothing may have checked nothing).

EXIT CRITERIA:
```
scrape.yml runs all audits nightly; a seeded synthetic defect in a test branch trips each audit (prove each alarm fires)
audit failure writes a visible artifact + nonzero step outcome; data/ commit still happens (never wedge data on an audit failure)
denominators asserted > 0 in every audit output
independent red team -> PASS
```

## Phase A1 — alerting that provably reaches Brandon (before the verifier)

Red team F6: the repo's only email path has plausibly never fired
(recovery.json doesn't exist), and nobody knows if the SMTP secrets work.
Alerting comes BEFORE the verifier: every later safeguard is worthless if
its failure is silent.

Tasks: test alert through the existing SMTP action with confirmed receipt
(spam folder checked); dead-man's switch (healthchecks.io — 10 min of
Brandon's time; FALLBACK if he never does it: scheduled workflow checks last
commit age on main and emails via existing SMTP); live-site freshness probe
(build timestamp in footer vs now — catches Vercel silently not deploying, a
gap nothing else covers); quarterly test-the-alarm drill, scheduled.

EXIT CRITERIA:
```
Brandon confirms receipt of a real test email (his word, in session)
dead-man's switch OR fallback proven by a deliberately skipped run alerting
freshness probe alerts on a simulated stale deploy
alert policy encoded: interrupt = pipeline down / gate blocked / retailer at zero; digest = everything else
independent red team -> PASS
```
Owner involvement: healthchecks.io signup (10 min, once) + "yes the email
arrived".

## Phase A2 — the independent verifier (1–2 weeks)

The replacement for self-comparing verify.py. Per red team F4/F12:
- **Stratified**: ~2 products per retailer per day (not 15 uniform — a
  great-garden-plants redesign would otherwise take ~a week to detect).
- **Per-retailer mismatch rates**, alarm on consecutive per-retailer
  mismatches, never a single global rate.
- **Two modes**: candidate-build mode (reads freshly built site/ in the
  workflow, gates publishing) and published-site mode (reads the live site,
  catches deploy/CDN divergence). The draft conflated these.
- **Explicitly covers stark-bros** (today's verify.py structurally skips the
  one non-Shopify retailer).
- **Per-FIELD independence** (F12): for FGT, price ground truth via
  DOM-parsed aria-labels is independent, but production FGT stock ALREADY
  reads schema.org — a verifier reading schema.org would verify FGT stock
  against itself. The verifier must derive stock from a different signal
  than production per retailer, or mark that field unverifiable.
- **Independence wiring test**: a test that FAILS if the verifier imports
  from scrapers/shopify.py. This codebase has converted independent checks
  into self-comparisons four times.
- Politeness: 10-15s spacing, hard cap, cache to disk, stop on 429/403.

EXIT CRITERIA:
```
verifier runs in CI both modes; seeded wrong price on a test branch is caught in candidate mode
per-retailer coverage: every active retailer sampled >= 2x/day; stark-bros included
wiring test fails when verifier imports the production scraper (demonstrated, then restored)
FGT stock marked verified-independently or unverifiable — never self-confirmed
zero 429/403 across a full week of operation
independent red team -> PASS
```

## Phase A3 — the publishing gate (after a calibration Brandon can trust)

Red team F2/F3: the draft gate was unspecified at every point this pipeline
has wedged before, and would have calibrated its threshold on a baseline
containing known-bad PWD data ("normalizing the disease").

Tasks: rebuild PWD promo handling FIRST (promoted from the old Phase 3 —
prerequisite for honest calibration); then a calibration week with
per-retailer distributions (threshold provisional until the first real promo
event); then the gate with these semantics:
- verify the CANDIDATE build in-workflow, before push
- split the commit: `data/` ALWAYS lands; only `site/` is conditional (the
  documented CRIT-2 wedge was a gate that starved itself of data)
- verifier absent or denominator < minimum -> FAIL OPEN with loud alert
  (a banned verifier must not wedge publishing for a hands-off owner)
- auto-expiring block: after K consecutive blocked cycles, degrade to
  publish-with-alert; never block-forever unattended
- gate result + verifier rates written INTO last_manifest.json so the
  manifest stops reporting wrong-but-present as healthy (F12)
- heartbeat-v2 branch: DROPPED (recommendation adopted — 8 confirmed
  defects, purpose superseded by A0–A3; an unreliable monitor manufactures
  confidence)

EXIT CRITERIA:
```
seeded bad candidate build -> site/ commit blocked, data/ commit lands, alert fires
verifier-absent simulation -> publish proceeds + alert (fail-open proven)
K consecutive blocks simulation -> degradation path proven
last_manifest.json carries verifier rates; health check protocol reads them
PWD mismatch rate at or below the fleet median before thresholds frozen
independent red team -> PASS
```

## Phase A4 — bounded self-correction + rot-proofing (1–2 weeks)

Everything here acts automatically, so every action has a human boundary
(today's lesson: guards that act on their own froze a wrong price for
months).

- **Disappearance classification** (owner directive 2026-08-12): every
  product missing from a scrape gets CLASSIFIED, never left to age off.
  The decision tree, proven on the 13 FGT failures:
  1. Page fetch says all Offers non-orderable -> SOLD OUT, recorded
     automatically as an out-of-stock row (built, f5b8d89e).
  2. Otherwise check the retailer's sitemap (one cached fetch per run):
     old handle present -> live-but-unreadable, drift alarm.
     Old handle absent, close name match exists -> RENAMED candidate,
     goes to the digest. A match to a different FORM (shrub vs tree
     form, e.g. sunny-knockout-rose-tree) is a different product and
     must NEVER auto-remap.
     No match -> DELETED; digest entry; stale rows purged after Brandon
     confirms (or after 2 consecutive confirmations of absence).
- **Auto-heal** (F7 — this is design work, not a switch-flip: the Opus
  review hook has zero callers, validation only proves a URL resolves, and
  FGT can't validate via .json at all): auto-DISCOVER candidates via the
  sitemap classification above; auto-APPLY only when old/new variant price
  sets match within tolerance; everything else goes to the weekly digest
  for Brandon's one-click.
- **Retailer failure** (F8): quarantine-and-probe, never purge. Stop
  displaying, keep data, keep probing, auto-reactivate on recovery.
  Deletion only ever by Brandon.
- **Canary** (F12): every run, not monthly; pinned on STRUCTURE (N sizes
  parse, price in band), not on a price that goes stale at the first
  legitimate repricing.
- **Anomaly queue**: price_anomaly-flagged rows -> weekly digest; auto-clear
  when a second independent scrape confirms the new value.
- **Rot-proofing** (F11): affiliate-link health check in the weekly digest
  (the site can be perfectly correct and earn nothing — nothing watches the
  revenue today); annual domain/Vercel reminders; quarterly dependency
  refresh; CI shallow checkout note (pack is already 137 MiB at 2
  commits/day); HTML cache max-age reduced from 86400 to something sane for
  a twice-daily-fresh site.
- **The monthly agent review** (F11): scheduled, automated commissioning
  with PRICE_AND_STOCK_AUDIT.md as its brief, result delivered into the
  digest. It cannot depend on anyone remembering to run it.

EXIT CRITERIA:
```
auto-heal: a seeded renamed handle is discovered; in-tolerance case auto-applies; out-of-tolerance lands in digest, never applied
quarantine: simulated 3-run retailer failure hides it from pages, data intact, reactivation on recovery proven
canary trips on a seeded structural break; survives a seeded legitimate price change
digest generates on schedule containing: anomalies, quarantines, affiliate-link status, verifier trend
monthly review fires from schedule without human action (first run witnessed)
independent red team on the full automation surface -> PASS
```

---

## STEADY STATE (what "hands off" means when A4 closes)

- 2x daily: scrape -> audits -> candidate verify -> gate -> publish or
  refuse-with-alert. Deterministic, no agent.
- Weekly: digest email — anomalies, quarantines, affiliate health, verifier
  trend. Brandon reads it or doesn't.
- Monthly: scheduled agent review, findings into the digest.
- Brandon is interrupted ONLY for: pipeline down, gate blocked repeatedly,
  a retailer at zero, or a digest item he chooses to click.
- Remaining human jobs: approving deploys of CODE changes (data publishes
  are automatic once the gate exists), affiliate program admin, and the
  annual domain/Vercel renewals.

## Owner inputs still required (complete list)
1. C0/C1: two Run clicks (deploys) + reading two phase reports.
2. A1: healthchecks.io signup (10 min, once) + confirming one test email.
3. A3: nothing — heartbeat decision resolved by recommendation (dropped).
4. Cultivar model: resolved — claims suppressed in C1; building the model
   is optional future work, not a blocker for anything.

## What the red team could not fault (kept as-is)
Phase-1-before-Phase-2 as a principle; the verifier-independence erosion
warning + wiring test; alert hygiene (interrupt vs digest); the politeness
guard rails; success-only dead-man pings; the "auto-heal is inert" claim
(verified mechanically: runner.py:708 vs scrape.yml's per-retailer calls).
