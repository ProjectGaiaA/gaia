# ROLLBACK RUNBOOK — plantpricetracker.com

**For: Brandon. Read this when the site is wrong and you need it not-wrong.**

Nothing in here can make things worse if you follow it in order. Take the two
minutes to read Section 0 first — it explains *why* the obvious fix sometimes
does nothing, and that is the trap that wastes the most time.

---

## 0. Thirty seconds of orientation (read this even in a panic)

Three facts. Everything else in this document follows from them.

**Fact 1 — Vercel does not build anything. It serves the `site/` folder from
GitHub, exactly as-is.**
There is no build step on Vercel's side. Whatever HTML files are sitting in the
`site/` folder on the `main` branch is *literally* what visitors get. (Verified:
there is no `vercel.json`, `package.json`, or build config at the repo root; the
only `vercel.json` is *inside* `site/`, which means Vercel's "root directory" is
set to `site/` and it just copies files.)

> **The trap this creates:** if the bad thing was a code change (`build.py`, a
> file in `templates/`), reverting *only that code* changes **nothing** on the
> live site. The broken HTML is still sitting in `site/`. You must either revert
> the commit that changed `site/` too, or rebuild and commit `site/`. Section 2
> handles this for you — just don't improvise around it.

**Fact 2 — a robot commits to `main` twice a day, and it commits `site/` too.**
The `Daily Scrape` workflow runs at 7:00 AM ET and 5:30 PM ET. It scrapes, runs
`build.py`, and commits `data/` **and** `site/` with a message like
`Daily price update 2026-08-11_23:03`. Then Vercel auto-deploys.
(Verified: `.github/workflows/scrape.yml`; the most recent bot commit `a09a9f07`
touched 126 files under `site/` and 105 under `data/`.)

> **The trap this creates:** the bot may have pushed since the bad deploy. Your
> local copy is behind. **Always `git pull` before you revert.** Also: the bot
> will happily re-publish bad code on its next run — see Section 5.

**Fact 3 — pages are cached for 24 hours, and CSS/JS for 7 days.**
`site/vercel.json` sets `Cache-Control: public, max-age=86400,
stale-while-revalidate=3600` on `*.html`, and `max-age=604800` on `/assets/*`.
In English: once a visitor's browser has loaded a page, it will keep showing
that page from its own memory for up to 24 hours without ever asking the server
again. Your fix is invisible to that visitor until then.

> **The trap this creates:** you roll back, you reload the page, it still looks
> broken, you panic and roll back again. **You were looking at your own browser
> cache, not the site.** Section 4 is how to look at the real thing.

---

## 1. Is it actually bad enough to roll back?

Run these three checks. **Every URL gets a `?v=` on the end** — for example
`https://www.plantpricetracker.com/plants/astilbe.html?v=2`. Bump the number
each time (`?v=3`, `?v=4`…).

> **Why the `?v=`:** to a cache, `page.html` and `page.html?v=2` are two
> different pages, so `?v=2` has never been cached and must be fetched fresh
> from the server. Without it you are grading your own browser's 24-hour-old
> copy, and it will lie to you in both directions.

The canonical site is **https://www.plantpricetracker.com** (with the `www.`).

### Check 1 — Do the pages load at all?

Open these three, each with a fresh `?v=` number:

```
https://www.plantpricetracker.com/?v=2
https://www.plantpricetracker.com/plants/astilbe.html?v=2
https://www.plantpricetracker.com/category/index.html?v=2
```

- **Blank page, 404, "DEPLOYMENT_NOT_FOUND", or a raw error** → **ROLL BACK.**
  This is the unambiguous case.
- Pages load but look unstyled (plain black text on white, no layout) → the CSS
  is broken. **ROLL BACK**, and note that CSS is the 7-day cache, so Section 4's
  patience note applies double.

### Check 2 — Are the prices wrong or missing? (the one that matters most)

Open two or three product pages with `?v=`, e.g.:

```
https://www.plantpricetracker.com/plants/astilbe.html?v=2
https://www.plantpricetracker.com/plants/autumn-blaze-maple.html?v=2
```

Look for:

- `$0.00`, `$0`, blank price cells, or a price with no size next to it
- a "save N%" figure that is obviously nonsense (negative, or over ~90%)
- **every** retailer row gone from a plant that normally lists several

One weird row on one plant is not a rollback. **Prices showing as $0, or an
entire retailer's rows vanishing site-wide, is a rollback.** The site's whole
promise is "these numbers are true"; a wrong number is worse than an old number.

### Check 3 — Did the deploy even happen, and did the robot break?

1. Go to **https://github.com/ProjectGaiaA/gaia/actions** → click
   **Daily Scrape** in the left sidebar.
2. Look at the top run. A **red X** means the run had a problem. Click into it
   and read the red **error annotations** at the top of the summary page — they
   are written in plain English on purpose (e.g. *"Publish: NOTHING was
   published this cycle"*, *"Scraper failed for: …"*).
3. Note the plain-English rule the workflow already follows: it **blocks
   publishing** only when the output would be bad, and merely **alarms** when
   something needs attention but the output is fine. So a red X does **not**
   automatically mean the live site is broken — check 1 and 2 decide that.

**Decision:**

| What you found | Do this |
|---|---|
| Site down / unstyled / $0 prices / retailer wiped out | **Roll back.** Section 2 (or Section 3 if you need it fixed *this minute*) |
| Red X in Actions, but the site looks correct | **Do not roll back.** Read the annotation, fix forward later |
| Prices are simply a day or two old | **Do nothing.** Section 6 |

---

## 2. OPTION A — `git revert` (the real fix; do this one)

This undoes the bad change by adding a *new* commit that reverses it. Nothing is
deleted, history stays intact, and it is safe to do while the robot is running.

### 2.0 Open a terminal in the repo

Open **Git Bash** (or PowerShell) and paste:

```bash
cd "C:/Users/BrandonHall/OneDrive - YA/Documents/CC/project_gaia"
git status
```

If `git status` says anything other than `nothing to commit, working tree
clean`, **stop and stash your own edits first** so they don't get tangled up:

```bash
git stash push -u -m "my in-progress work, parked during a rollback"
```

(You get it back later with `git stash pop`. If you have no idea what that
message means, you had no in-progress work and can ignore this.)

### 2.1 Get onto `main` and get current (never skip this)

The bot commits twice a day and your local copy lags — the project notes
explicitly warn that this OneDrive copy reports stale data if you don't pull.

```bash
git checkout main
git pull --ff-only origin main
```

- If `git pull --ff-only` **fails**, it means you have local commits on `main`
  that aren't on GitHub. Do **not** force anything. Run
  `git log --oneline origin/main..main` to see what they are, and deal with that
  before continuing. (This is the one place to stop and get help rather than
  guess.)

### 2.2 Find the bad commit

```bash
git log --oneline -15
```

You'll see something like:

```
a09a9f07 Daily price update 2026-08-11_23:03      <- the robot
ac5cca8e Add the first real affiliate link         <- a human/agent change
5723d6b0 Declare lxml and pin all dependencies
```

The 8 characters at the start are the **commit ID**. Identify the one that
introduced the problem — usually the newest **non-robot** commit, or the newest
commit full stop if the robot itself published bad prices.

To see what a commit actually changed before you undo it:

```bash
git show --stat a09a9f07
```

### 2.3 CASE 1 — revert one ordinary commit (this is almost always you)

Replace `BADSHA` with the commit ID:

```bash
git revert --no-edit BADSHA
```

To undo several commits at once — **list the newest first**:

```bash
git revert --no-edit NEWESTSHA SECONDSHA OLDESTSHA
```

### 2.3b CASE 2 — the bad commit is a **merge** commit

A merge commit is one that joined a branch into `main` (its `git log` entry
shows two parents; `git show --stat` on it lists two `Merge:` hashes at the top).
Git refuses to revert one without being told *which side to keep*:

```bash
git revert --no-edit -m 1 BADMERGESHA
```

`-m 1` means **"keep `main` as it was, throw away what the branch brought in."**
That is what you want 99% of the time. (`-m 2` means the opposite and you will
almost never want it.)

> **Repo reality check:** as of this writing `main` has **zero** merge commits in
> its history — every change so far arrived as a plain commit or a rebase.
> So Case 2 probably does not apply to you *today*. It is written down because
> the planned `merge-test` → `main` merge would create the first one, and that
> is exactly when you would need it and not have it.

### 2.4 Handle the "the robot pushed while I was typing" case

This is the sequence that is safe even if the bot committed 30 seconds ago:

```bash
git pull --rebase origin main
git push origin main
```

- `--rebase` replays your revert on top of whatever the bot just added, instead
  of creating a tangle. The bot's own workflow uses this same approach.
- If the push is **rejected** again (the bot beat you twice), just run those two
  lines again. It is safe to repeat.
- If `git pull --rebase` stops with a **conflict**, it will almost certainly be
  inside `site/` — which is a generated folder nobody hand-edits. Get out
  cleanly and use the escape hatch:

```bash
git rebase --abort
```

Then jump to **Section 3 (Vercel dashboard rollback)** to make the site correct
right now, and come back to the git side when you are not under pressure.

### 2.5 THE STEP PEOPLE FORGET — make sure `site/` actually changed

Remember Fact 1: Vercel serves `site/` verbatim. If the commit you reverted
contained `site/` files (robot commits always do; a merged code change usually
does), you are done — skip to Section 4.

If you reverted a commit that touched **only** code (`build.py`, `templates/`,
`scrapers/`), the bad HTML is still live. Regenerate and publish it:

```bash
python -X utf8 build.py
git status --short site/
```

- If that prints **nothing**, `site/` was already correct. Done.
- If it prints a list of files, publish them:

```bash
git add site/
git commit -m "Rebuild site after rollback"
git push origin main
```

### 2.6 Watch the deploy land

Go to **https://vercel.com** → your project (`gaia-pearl`) → **Deployments**.
A new deployment should appear within about a minute of your push and go to
**Ready** in another minute or two. Then go to **Section 4** and verify.

---

## 3. OPTION B — Vercel dashboard rollback (fastest, buys you time)

**Use this when the site is visibly broken and you want it fixed in 60 seconds**,
or when git is fighting you. Then do Option A afterwards.

> **This does NOT fix the repository.** `main` still contains the bad code. The
> next scheduled scrape (7:00 AM / 5:30 PM ET) will build, commit, and
> **re-deploy the bad version**, undoing what you just did. Option B buys you
> hours. Option A is the fix. If you can't get to Option A before the next
> scheduled run, **also do Section 5** to stop the robot.

**[unverified — the following steps are from Vercel's standard dashboard UI and
have not been walked through on this account; confirm on first use and correct
this document if the wording differs.]**

1. Go to **https://vercel.com** and log in (the account that owns the
   `gaia-pearl` project).
2. Click the project — the one serving **plantpricetracker.com**.
3. Click the **Deployments** tab. You get a list, newest at the top, each with a
   commit message like `Daily price update 2026-08-11_23:03`.
4. Find the last deployment you believe was **good** — use the commit message
   and timestamp; it will be one *below* the bad one.
5. Click the **⋯** (three dots) at the right-hand end of that deployment's row.
6. Choose **"Promote to Production"** (on some plans this is labelled **"Instant
   Rollback"**, or you open the deployment and use the **Rollback** button on
   its page). Confirm in the dialog.
7. Wait for the **Production** label to move onto that deployment in the list.
   This takes seconds — nothing is rebuilt, Vercel just re-points the domain at
   files it already has.
8. Verify with **Section 4**.

If you cannot find the option: open the good deployment itself (click its row) —
the same action lives in the **⋯** menu at the top-right of the deployment
detail page.

---

## 4. The cache problem — how to know your rollback actually worked

**The rule: check with a `?v=` URL, in a private/incognito window.**

Fresh `?v=` numbers each attempt:

```
https://www.plantpricetracker.com/?v=7
https://www.plantpricetracker.com/plants/astilbe.html?v=7
```

Plus **Ctrl+Shift+N** (Chrome/Edge) or **Ctrl+Shift+P** (Firefox) for a private
window — belt and braces, since that window has no cache of its own.

**What to look for:** the *specific* thing that was wrong in Section 1. Not "the
page looks fine" — the actual broken price, the actual missing retailer, the
actual unstyled page. Name it before you check it, then check that one thing.

**What you should expect, honestly:**

| Who | When they see the fix |
|---|---|
| You, with `?v=` in a private window | Immediately (as soon as the deploy is Ready) |
| A brand-new visitor who has never been to the site | Immediately |
| A returning visitor whose browser cached the page | **Up to 24 hours** (`max-age=86400`) |
| A returning visitor, if the broken thing was CSS or JS | **Up to 7 days** (`max-age=604800` on `/assets/*`) |

There is **nothing you can do** about that last group short of a code change
(renaming the asset files, or lowering the cache times in `site/vercel.json` —
which the improvement plan already flags as overdue for a site that refreshes
twice a day). Do not keep rolling back because a returning visitor still reports
the old version. Verify with `?v=`, and trust it.

**One nuance, [inferred from `site/vercel.json`, not verified live]:** the 24-hour
rule is written as `"source": "/(.*\\.html)"`, which matches paths *ending in*
`.html`. The bare homepage URL `/` does not end in `.html`, so the homepage may
well refresh much faster than the product pages. If the homepage looks fixed but
`/plants/…​.html` doesn't, that is expected — and another reason to use `?v=`.

---

## 5. BREAK GLASS — stop the robot from re-publishing

**Do this whenever you are using Option B, or whenever you need the site to hold
still while you figure things out.** The scraper runs at 7:00 AM and 5:30 PM ET
and each run rebuilds and re-deploys from whatever is on `main`. If `main` is
bad, the robot will keep putting the bad thing back.

### To stop it

1. Go to **https://github.com/ProjectGaiaA/gaia/actions**
2. In the left sidebar, click the workflow named **Daily Scrape**.
3. Top-right of that page, click the **⋯** (three dots) button.
4. Click **Disable workflow**.
5. GitHub shows a banner reading roughly *"This workflow has been disabled
   manually"* — that is your confirmation. Scheduled runs stop immediately.

**Cost of doing this:** prices stop updating. That is *fine* — a day-old correct
price is a better product than a fresh wrong one. Just don't forget step 6.

### To start it again

6. Same page → the button now reads **Enable workflow**. Click it.
   Then either wait for the next scheduled run, or force one now:
   **Run workflow** button → branch `main` → **Run workflow**.
   (The workflow supports manual triggering — `workflow_dispatch` is enabled.)

> **Set a reminder when you disable it.** A permanently disabled scraper is a
> silently rotting site, which is the exact failure mode this whole project is
> built to avoid. The workflow also queues rather than cancels
> (`cancel-in-progress: false`), so re-enabling mid-run is safe.

---

## 6. When to do NOTHING

**Stale-but-true beats fresh-but-false.** Rolling back is for *wrong*, not for
*old*.

Do **not** roll back when:

- **"The prices are a day old."** Rolling back replaces today's data with
  *yesterday's* data. You would be making the staleness worse, not better. If a
  scrape run failed, the correct move is to look at the Actions error and fix
  the scraper — or just wait for the next scheduled run, which is at most 12
  hours away.
- **The Actions run is red but the site looks right.** The workflow deliberately
  alarms without blocking for problems that don't affect output (test failures,
  quarantined rows, one dead retailer). Read the annotation. Fix forward.
- **One retailer's rows are missing from some plants.** That is usually that
  retailer's site changing or blocking, not your deploy. Reverting your code
  will not bring their data back.
- **You aren't sure what's wrong.** A rollback of an unknown problem
  frequently swaps one broken state for a different broken state, and now you
  have two mysteries. Do Section 1's three checks and name the defect first.
- **The thing you'd revert is more than a couple of days old.** The robot has
  committed 4+ times since; a revert that far back is a merge fight, not a
  rollback. Fix forward instead.

If in doubt: **Section 5** (stop the robot) is almost never the wrong move. It
freezes the situation without changing anything, and buys you unlimited time to
think. Prefer it to a hasty revert.

---

## Appendix — the facts this runbook rests on

Verified directly against the repository (worktree `gaia-merge`, 2026-08-12):

| Fact | Where it's proven |
|---|---|
| No `deploy.yml`; Vercel's own Git integration deploys on push to `main` | commit `841f767e` "Remove deploy.yml — failed all 44 runs" |
| Scrape runs 11:00 and 21:30 UTC (7:00 AM / 5:30 PM ET), plus manual dispatch | `.github/workflows/scrape.yml` lines 3–8 |
| Bot commits `data/` **and** `site/` as "Daily price update …" | `scrape.yml` "Commit updated price data" step; commit `a09a9f07` = 126 `site/` files + 105 `data/` files |
| Bot pushes with `git pull --rebase` and retries 3× on conflict | `scrape.yml` lines 219–229 |
| HTML cached 24h, assets 7 days, assets are **not** fingerprinted | `site/vercel.json`; `site/assets/css/style.css` (no hash in filename) |
| Vercel does no build — serves `site/` verbatim | no root `vercel.json`/`package.json`; `vercel.json` lives inside `site/` |
| `main` currently has **zero** merge commits | `git rev-list --merges --count origin/main` → `0` |
| Canonical domain is `https://www.plantpricetracker.com` | `site/sitemap.xml` |
| Local clone lives at `C:\Users\BrandonHall\OneDrive - YA\Documents\CC\project_gaia` | worktree `.git` pointer |
| The OneDrive clone lags CI — always pull first | `.claude/CLAUDE.md`, "Ops notes" |

Not verified — treat with appropriate suspicion and correct this file on first
real use:

- **Every step in Section 3** (Vercel dashboard). Taken from Vercel's standard
  UI; the exact menu labels ("Promote to Production" vs "Instant Rollback") vary
  by plan and by dashboard version. Nothing here was clicked to confirm it.
- **Section 5's exact menu wording** in the GitHub Actions UI. The workflow
  *is* schedule-driven and manually dispatchable (verified in `scrape.yml`); the
  click path to disable it is from GitHub's standard UI and was not exercised.
- The claim that the homepage `/` escapes the 24-hour cache rule — inferred from
  the `"/(.*\\.html)"` pattern in `site/vercel.json`, not measured against a
  live response header.
- Whether Vercel purges its own edge cache on a new deployment. **Browser**
  caching for 24h/7 days is certain from the headers; the CDN's behaviour is
  not. Either way the practical advice is identical: verify with `?v=`.

---

## APPENDIX B — deploy-specific exception for the 2026-08-12 deploy (`c289867f`)

The general rule in §2.3b ("`-m 1` keeps main as it was — what you want 99%
of the time") is **WRONG for this specific commit**, because this merge was
built in the opposite direction: it was constructed on the feature side and
fast-forwarded onto main, so parent 1 is the FEATURE branch and parent 2 is
the old main. Reverting with `-m 1` here would keep the new code and throw
away the bot's price-data commits — the opposite of a rollback.

**To roll back the 2026-08-12 deploy specifically:**

```bash
git pull --rebase
git revert -m 2 c289867f --no-edit
python -X utf8 build.py
git add -A site/ && git commit -m "Rebuild site after rollback"
git push
```

(The rebuild step matters: Vercel serves the committed site/ folder verbatim,
so reverting code without rebuilding changes nothing visitors see.)

This exception was caught by the agent that built the merge, before deploy.
Future merges should be constructed main-side so §2.3b's general rule holds.
