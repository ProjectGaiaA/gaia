# Agent protocol — how to work on this repo, and how to log it

**Read this before touching anything.** It is short on purpose. The long
version of *what* to look for is `PRICE_AND_STOCK_AUDIT.md`; the plan is
`GAIA_FINAL_PLAN.md`. This file is *how to behave* and *how to record it*.

Everything here was paid for by a real defect on 2026-08-12, in a single
session where four separate defects were introduced **by fixing other
defects**, and three of them were caught by review rather than by the author.

---

## 1. The rules (GAIA_FINAL_PLAN.md R1–R10, in one line each)

| | Rule | Because |
|---|---|---|
| R1 | Re-gate after fixes — green means the red team passed **on the commit that ships** | every defect that session arrived in fix-after-review code |
| R2 | Removing/weakening any check requires (a) the replacement demonstrated FIRING, (b) a test that fails when it is disabled | a guard was removed citing a control that could not fire |
| R3 | Every "X is covered by Y" claim is a line item the gate verifies with a command | the two worst defects were false sentences, not wrong code |
| R4 | Test the artifact, not the workspace | a commit shipped a reverted file while local tests were green |
| R5 | A health metric must not be satisfiable by the failure mode | 68 unreadable products scored 100% healthy |
| R6 | Publishing a fact must never silence a signal | recording "sold out" muted the drift alarm |
| R7 | Re-derive the safe default when reusing a predicate for a new decision | fail-closed for *hiding a price* is fail-open for *silencing an alarm* |
| R8 | Mutation-test the tests | 2 mutants survived all 474 tests |
| R9 | Calibrate against history before enabling a dormant check | avoids trading silence for a wedged pipeline |
| R10 | Print the denominator | a check that finds nothing may have checked nothing |

**If you can only remember two: R2 and R10.**

---

## 2. Hard constraints

- **Never push to `main`.** Deploys are Brandon's, via a command he runs.
  Your job ends at "ready to ship + evidence".
- **Never `git stash` in this repo.** There are unrelated pre-existing stash
  entries; popping one produced a 113-file conflict mess.
- **Never restore a file with `cp` after `git checkout <sha> -- <path>`.**
  That checkout **stages** the old version. Restore with
  `git checkout <current-sha> -- <path>` and confirm `git diff --cached` is
  empty before committing. This is how a reverted `runner.py` shipped green.
- **Never hand-edit `site/`.** It is generated. Change templates or
  `build.py`, then `python -X utf8 build.py`.
- **Never hit a retailer site outside `scrapers/polite.py`.** 10–15 s between
  requests, cap the run, cache pages to disk, stop on 429/403. Getting banned
  ends the affiliate relationship.
- **Tests never touch the network.** Mock at the requests/urllib boundary.
- **No spending, no account creation, no affiliate applications.**

## 3. Kill switches

1. A file named `STOP` in the repo root — check for it at the top of every
   loop round and halt if present.
2. Two consecutive rounds with an identical criteria scoreboard = stop and
   report. Repeating is not progress.
3. Iteration cap: 8 rounds per phase, then stop with an account of what was
   tried.

---

## 4. How to log

Two artifacts. Keep both current; they are the only things that survive you.

### 4a. `LOOP_STATUS.md` (scratchpad) — the live state

Rewrite the top section every round. It must always answer: what phase, what
round, what is green, what is red, what is running, what is blocked on
Brandon. Format:

```
## <PHASE> — ROUND <n> of 8
Pre-flight: STOP file absent | present
- <task>: DONE (model, tokens, commit sha) — one line of what changed
- <task>: RUNNING
- <task>: BLOCKED on <what>

## Criteria scoreboard (last measured)
<criterion>   <number> / <denominator>   PASS|FAIL
...

## Notable / corrections
<anything that contradicts an earlier claim — especially your own>
```

### 4b. Commit messages — the durable record

A commit message here is a **finding report**, not a changelog. Required:

1. **What was wrong**, with the measurement that proves it — numbers and
   denominators, not adjectives.
2. **Why it was wrong** — the mechanism, so the next reader can recognise the
   class.
3. **What changed**, and **what you proved about it**: the before/after
   measurement, and how you know the test is load-bearing (which commit you
   restored, what failed).
4. **What you did NOT fix**, and any trade you made, stated plainly.
5. Test count and lint status.

If a review found the defect, say so. If you introduced it while fixing
something else, say that too — that pattern is the single most useful signal
in this repo's history.

### 4c. When you are wrong

State it in one line, correct it, move on. Do not bury a correction in a
later paragraph, and do not restate a claim you have already had to walk
back. Examples from the record, all of which cost time precisely because they
were asserted confidently first:

- "halving all prices is now blocked" — it was not
- "displayable_price is called in exactly one place" — three call sites
- "the azalea proves the FGT fix" — the old parser produced the same numbers
- "11 of 68 FGT, healthy" — 13 of 68, degraded

---

## 5. Definition of done for any change

```
[ ] the change does what its commit message says (verify, do not assume)
[ ] tests pass AND the new test fails against the pre-fix code (prove it)
[ ] mutants: break the change 3+ ways, confirm the suite kills each
[ ] ruff clean
[ ] python -X utf8 build.py, then `git status --short site/` is EMPTY
[ ] every count reported carries its denominator
[ ] git status clean, git diff --cached empty, HEAD contains your change
[ ] independent red team passed ON THIS COMMIT
```

The last two are the ones people skip. They are the ones that bit hardest.

---

## 6. Open defects — fix these

Tracked in the session task list; restated here because task lists do not
survive.

| # | Severity | Defect |
|---|---|---|
| F1 | HIGH | `no_sizes_readable` is set on only the FGT HTML path (`shopify.py:725`). The Shopify-JSON path has no `if sizes:` guard, so 6 retailers can publish empty rows unflagged and score 100% healthy. Sanity gate misses it too: `fresh_rows` stays high so check #4 cannot fire, `fresh_price_points` is 0 so the collapse check is skipped. Not a regression — same on `main`. |
| F3 | MEDIUM | The gate's movement check joins on `(plant, retailer, tier)`. A regression that also drifts tier labels collapses the denominator to 0 and the gate exits 0 silently. Needs a coverage floor: `fresh_price_points` high while `prices_compared` is ~0 is itself systemic. |
| F4 | MED/LOW | FGT ships at 75% → permanently `degraded`. Session health check reports FAIL every time, and a real FGT breakage becomes indistinguishable from the baseline. Resolve the 13 unreadable products, or separate "gone" from "unreadable" in the metric. Do not just widen the threshold. |
| C1 | MEDIUM | crape-myrtle: `_normalize_size` collapses form/quantity qualifiers (`2 quart Multi-stem $177.95` overwrote `1 quart $108.95`), and Single-stem variants are dropped entirely, overstating small-size prices. Evidence: `scratchpad/fgt_cm.html`. |

Known-unfixed, larger, in the plan: 23 plants comparing different cultivars;
proven-winners-direct promo flips; price-history chart mixing tiers; FGT
ground truth covering 12 of 68 plants.
