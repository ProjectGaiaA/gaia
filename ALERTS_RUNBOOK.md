# Failure Alerts Runbook

Closes open item **B-2**: until this landed, the only signal that a scrape
cycle went wrong was the workflow's red/green dot on a page nobody opens.

**Destination mailbox: `projectgaiaa@proton.me`.**

Everything in this file that a machine could do is already done and merged.
What is left is **one-time work only the repo owner can do**, because it needs
a login this repo does not have. Sections 3 and 4 are that work.

---

## 1. What is wired, and what it can and cannot do

Two workflows now carry an alert path. They are independent on purpose:

| Workflow | Fires when | Covers |
|---|---|---|
| `.github/workflows/scrape.yml` | a cycle **ran and went red** | scraper deaths, quarantined rows, test failures, spot-check mismatches, audit alarms, a non-reproducible build, a failed publish |
| `.github/workflows/heartbeat.yml` | no commit touched `data/prices/` for 30h | a cycle that **never ran at all** — the case `scrape.yml` structurally cannot report |

Each has **two delivery paths**:

* **Path A — SMTP email.** Needs four repository secrets. Off until section 3
  is done. Carries the full alarm summary.
* **Path B — GitHub's own notification email.** Needs no secrets. Live today,
  but goes to whatever address the *GitHub account* is configured to notify.
  Section 4 points it at the Proton mailbox. Carries only "a run failed".

### Hard guarantees (each pinned by a test, not by this sentence)

`tests/test_failure_alert_email.py`:

1. **No alert step can block a publish.** All of them sit after
   `Commit updated price data`.
2. **No alert step can redden a run.** Every one carries
   `continue-on-error: true`, and every shell body ends `exit 0`. A dead SMTP
   host, an expired token or a typo'd secret cannot manufacture an alarm.
3. **No alert email is sent on a green run.** A message in that mailbox always
   means something is wrong.
4. **Missing secrets are a `::warning::`, never a failure** — and the warning
   is emitted on *every* run, including green ones, so an unconfigured mail
   path is visible before the night it is needed.
5. **The body carries the alarm summary**, not just "it failed": run URL,
   which retailers died, which flags tripped (`TESTS_FAILED`, `QUARANTINED`,
   `REBUILD_DIVERGED`, `REBUILD_CHECK_FAILED`, `AUDITS_ALARMED`,
   `VERIFY_FAILED`), whether anything published, and
   `degraded_retailers` + per-retailer found/expected from
   `data/last_manifest.json`.

### What is NOT guaranteed — read this before trusting the mailbox

* **Nothing here has ever delivered a real message.** The SMTP hop cannot be
  tested offline; proving delivery needs a live server and a mailbox. Every
  step *up to* the handoff is tested. The handoff is not. Section 5 is how you
  prove it yourself in about two minutes.
* **Silence is not health.** If the secrets are wrong, or Proton is down, or
  the repo's Actions minutes lapse, you get nothing — by design, since the
  alternative is a mail outage turning every run red. The workflow's own
  red/green status stays the source of truth.
* **A job timeout may not send.** `scrape.yml` has `timeout-minutes: 180`.
  Whether `if: always()` / `if: failure()` steps run after a job-level timeout
  is behaviour I did not verify; if they do not, Path B is the backstop for
  that case.
* **The heartbeat runs inside the thing it monitors.** If GitHub Actions
  itself is down or scheduled workflows get disabled, neither path fires. The
  long-standing note at the top of `heartbeat.yml` still stands:
  healthchecks.io remains the stronger answer.

---

## 2. Choosing between Path A and Path B

**Do section 4 (Path B) regardless.** It is free, needs no plan, and is the
fallback when Path A's credentials rot.

Path A is worth the setup because Path B's email says only that a run failed —
you still have to open the run to learn anything. Path A's message carries the
whole summary and is readable from a phone.

Path A needs an SMTP account that can send. **Which one is up to you**, and it
does not have to be Proton — the mailbox that *receives* is
`projectgaiaa@proton.me` either way. Pick one of:

| Option | Cost | Notes |
|---|---|---|
| **A1. Proton SMTP token** | **Paid plan only** | Mail Plus / Unlimited / Business. Proton Free has **no** SMTP submission. Proton Bridge is not a free workaround either — it is also paid-only, and it is a desktop app that cannot run in CI. There is no free Proton sending route. |
| **A2. Gmail app password** | Free | Needs 2-Step Verification on a Google account. Sends *from* Gmail, delivers *to* Proton. |
| **A3. Transactional relay** | Free tier | Brevo, Mailgun, SendGrid, etc. Most now require domain or sender verification. |

If you are on Proton Free and do not want to pay, **A2 is the pragmatic
choice** and costs nothing. Section 3 gives the values for all three.

---

## 3. Path A setup — OWNER ONLY

### 3a. Get SMTP credentials

Do **one** of the following.

#### A1 — Proton (paid plans only)

1. Sign in at <https://mail.proton.me> as `projectgaiaa@proton.me`.
2. Open **Settings → All settings**, then the **Proton Mail → IMAP/SMTP**
   page. *(Menu wording has moved between Proton releases — the page you want
   is the one titled around "IMAP/SMTP" containing an "SMTP submission"
   section. If you cannot find it, that is itself the signal that the account
   is on the Free plan, where the feature is not offered.)*
3. Under **SMTP submission**, choose **Generate token**.
4. Name it something like `github-actions-alerts` and select
   `projectgaiaa@proton.me` as the sending address.
5. **Copy the token now** — Proton shows it exactly once.

Values for section 3b:

```
SMTP_SERVER   = smtp.protonmail.ch
SMTP_PORT     = 587
SMTP_USERNAME = projectgaiaa@proton.me
SMTP_PASSWORD = <the generated token, NOT the account password>
```

#### A2 — Gmail app password (free)

1. The Google account must have **2-Step Verification** on
   (<https://myaccount.google.com/security>).
2. Go to <https://myaccount.google.com/apppasswords>, create one named
   `plantpricetracker-alerts`, and copy the 16-character password.

```
SMTP_SERVER   = smtp.gmail.com
SMTP_PORT     = 587
SMTP_USERNAME = <your-gmail-address>
SMTP_PASSWORD = <the 16-character app password, spaces removed>
```

#### A3 — Transactional relay

Use whatever host/port/username/password the provider issues. Port **587**
(STARTTLS) is what `dawidd6/action-send-mail@v3` is configured for here; if
your provider only offers 465, set `SMTP_PORT = 465` — the action selects TLS
by port.

### 3b. Add the secrets to the repository

<https://github.com/ProjectGaiaA/gaia/settings/secrets/actions> →
**New repository secret**, once per row.

| Secret name | Required | Value |
|---|---|---|
| `SMTP_SERVER` | yes | from 3a |
| `SMTP_PORT` | yes | from 3a |
| `SMTP_USERNAME` | yes | from 3a |
| `SMTP_PASSWORD` | yes | from 3a — the token/app password |
| `SMTP_FROM` | no | overrides the From address. **Leave unset** unless you know the account may send as it. |
| `ALERT_EMAIL_TO` | no | overrides the recipient. Leave unset to use `projectgaiaa@proton.me`. |

Names are exact and case-sensitive. All four required secrets must be present;
three out of four is reported as unconfigured and sends nothing (there is a
test for that).

> **Why `SMTP_FROM` should stay unset.** It now falls back to
> `SMTP_USERNAME`, i.e. the authenticated account. It previously fell back to
> `PlantPriceTracker <noreply@plantpricetracker.com>` — an address this
> project cannot authenticate as. Proton and most providers reject a `From`
> the account is not authorised to send as, so **every send would have failed
> with a 550 while all four secrets looked correctly set.** That default is
> now removed from both workflows.

These same four secrets are also read by `weekly-recovery-email.yml`, which
still sends to `brandon.william.hall@gmail.com`. Setting them switches that
workflow on too. That is out of scope here but worth knowing.

### 3c. Confirm the warning stops

Next scrape run (11:00 / 21:30 UTC), or trigger one manually. Open the run and
look at **Check whether alert email is configured**. It should print
`SMTP secrets are present` instead of the `::warning::`. That proves the
secrets are *set*. It does **not** prove they *work* — section 5 does.

---

## 4. Path B setup — OWNER ONLY, no secrets, do this regardless

**Goal:** GitHub's own "your workflow run failed" email arrives at
`projectgaiaa@proton.me`.

> **Confidence, stated honestly.** The mechanism below is well-established:
> GitHub emails workflow-failure notifications, they go to the *account's*
> notification address, and additional addresses must be verified first. I am
> **less certain of the exact current UI labels** — GitHub moves and renames
> these settings. Treat the paths as "the page that does X", not as literal
> strings to match. All three pages are reachable from
> <https://github.com/settings/profile>.

### 4a. Verify the Proton address on the GitHub account

1. <https://github.com/settings/emails> → **Add email address** →
   `projectgaiaa@proton.me`.
2. GitHub sends a confirmation link there. Open the Proton mailbox and click
   it. **The address does nothing until it is verified.**

### 4b. Point notifications at it

3. <https://github.com/settings/notifications>.
4. Find the **default notification email** selector and set it to
   `projectgaiaa@proton.me`.
   *If `ProjectGaiaA` is a GitHub **organization** rather than a personal
   account, use **Custom routing** on the same page instead, and route the
   `ProjectGaiaA` organization to the Proton address. Custom routing wins over
   the default for repos in that org.*
5. On the same page find the **Actions** section (labelled around
   "GitHub Actions" / "Workflow runs"). Ensure **Email** is ticked and the
   filter is set to notify on **failed workflows** (the usual choices are
   "Only notify for failed workflows" vs "Send notifications for all workflow
   runs"). "Failed only" is what you want — all-runs is 730 emails a year.

### 4c. The scheduled-workflow gotcha

For **scheduled** (cron) workflows, GitHub attributes the run to a *user*, not
to the repo, and sends the failure notification to that user — the account
that created the workflow, or the account that most recently edited the `cron:`
schedule in the workflow file.

Practical consequences:

* Path B only reaches you if **your** account is that user. If someone else
  last edited a `cron:` line, their inbox gets the alert and yours does not.
* Steps 4a/4b configure *your* account. If alerts stop arriving after someone
  else touches a schedule, this is why.
* Path A has no such quirk — it sends to a fixed recipient regardless of who
  triggered the run. Another reason to do section 3 as well.

I am **confident** about this attribution rule; it is long-standing documented
GitHub behaviour. I am **less confident** of the precise wording GitHub uses
to describe it today.

### 4d. Alternative to 4a if you would rather not add the address

Set up forwarding from whatever address the GitHub account already notifies to
`projectgaiaa@proton.me`. Same result, one fewer address on the GitHub
account, one more hop to fail silently. Verifying the address (4a) is the more
robust option.

---

## 5. Prove it actually delivers — do this once, after section 3

No test in this repo can prove a message arrives. This is how you prove it,
and it takes about two minutes.

1. Go to
   <https://github.com/ProjectGaiaA/gaia/actions/workflows/heartbeat.yml>.
2. **Run workflow** → tick **`force_alert`** → **Run workflow**.
   That input exists for exactly this purpose: it drives the full alert path
   without waiting for the pipeline to actually break.
3. Expected outcome:
   * the run goes **red** — correct, that is the secret-free alarm;
   * `Send alert email` shows **success**;
   * `Raise the alarm` prints `Email path: message accepted by the SMTP server.`
   * **an email arrives at `projectgaiaa@proton.me`**, subject
     `[PlantPriceTracker] PIPELINE DOWN — no price data for Nh`.
4. **Check the Proton spam folder.** First delivery from a new sender very
   often lands there. Mark it "not spam" and add the sender to contacts, or
   every future alarm is silent.
5. If `Send alert email` shows **failure**, read its log:
   * `535` / authentication failed → wrong `SMTP_PASSWORD` (used the account
     password instead of the generated token?) or wrong `SMTP_USERNAME`.
   * `550` / not authorised / sender rejected → the `From` is not an address
     the account may send as. Unset `SMTP_FROM`.
   * connection timeout → wrong `SMTP_SERVER` or `SMTP_PORT`.
   * On Proton, "SMTP submission is not available" → the account is on the
     Free plan. Switch to option A2.
6. Note the date you did this. These credentials rot silently: an app password
   revoked or a plan lapsing produces no signal except a failed send inside an
   already-red run. Re-run this test after any plan or password change.

Also worth doing once: confirm **Path B** independently, by checking whether
GitHub's own notification for that same red heartbeat run reached the Proton
mailbox. If Path A works and Path B does not, section 4 is not finished.

---

## 6. Reading an alert when one arrives

The email body is generated by `scripts/compose_failure_alert.py` and is
ordered by what you need first:

* **WHAT ALARMED** — numbered list, most actionable first.
* **DID ANYTHING PUBLISH?** — the question that decides urgency.
  `YES` means the alarms need attention but the site is current. `NO` means
  prices are ageing; two consecutive `NO` cycles trip the heartbeat.
* **PIPELINE HEALTH** — `degraded_retailers` plus per-retailer
  found/expected. `runner.py` scores health as `products_found /
  products_expected`, so that ratio is the actionable number.
* **WHERE TO LOOK** — run URL, artifacts, the local repro command.

If the body says *"none of the known alarm flags were set"*, the job died
outside the alarm path — a timeout, a runner or network failure, a dependency
install, or the checkout. Open the run and read the first red step.

---

## 7. Optional hardening

* **Pin the mail action to a commit SHA.** All three workflows use
  `dawidd6/action-send-mail@v3`, a mutable tag, and the step is handed live
  SMTP credentials. Pinning to a SHA removes the "upstream tag gets moved"
  supply-chain risk. Left as-is here only for consistency with the two
  pre-existing workflows; changing it is a one-line edit in each.
* **Add an external dead-man's switch.** healthchecks.io or equivalent, pinged
  on success by `scrape.yml`, with silence as the alarm. It is the only option
  that fires when GitHub itself is the thing that failed — see the long note at
  the top of `heartbeat.yml`.
* **Redirect without editing a workflow.** Set the `ALERT_EMAIL_TO` secret.

---

## 8. Files

| File | Role |
|---|---|
| `.github/workflows/scrape.yml` | alert path for a cycle that ran and went red (4 steps after `Raise alarms`) |
| `.github/workflows/heartbeat.yml` | alert path for a cycle that never ran |
| `scripts/compose_failure_alert.py` | builds the alert body; the only testable part of Path A |
| `tests/test_failure_alert_email.py` | pins the five guarantees in section 1 |
| `ALERTS_RUNBOOK.md` | this file |
