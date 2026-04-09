# Project Workflow Rules

This file layers on top of the global ~/.claude/CLAUDE.md verification
protocol. The global rules (self-verification, anti-rationalization,
stop hook, verification agent) still apply. This file adds the
spec-driven workflow that governs how features get planned and built
in this repo.

## The Three-Phase Ritual

Every feature beyond a one-line fix follows three phases. Each phase
runs in its own fresh window. The spec file in `.specs/` is the only
artifact that crosses window boundaries.

### Phase 1: Scope Grill

Trigger: user opens a window and says "I want to build X" or similar.

Your job:
1. Read `.specs/_template.md` if you have not seen it this session.
2. Grill the user on SCOPE ONLY. What the feature does, who it's for,
   what success looks like, what is explicitly out of scope.
3. DO NOT propose technical approach. DO NOT discuss implementation.
   DO NOT mention files, languages, or libraries. If the user starts
   discussing how to build it, redirect: "We'll cover the how in
   Phase 2. Right now I just need to understand what we're building."
4. Ask questions ONE at a time. Wait for the answer before asking the
   next. The user is not a coder — ask in plain English, not in
   technical terms. When presenting options, give 2-4 choices with
   plain-English tradeoffs — whatever number fits the decision.
5. When you have enough to fill in Problem, Scope Decisions, and Out
   of Scope sections of the template, write `.specs/<short-name>.md`
   with those sections completed. Leave the rest as template placeholders.
6. Tell the user: "Phase 1 complete. Spec written to .specs/<name>.md.
   Close this window and open a fresh one for Phase 2."
7. Stop. Do not start Phase 2 in the same window.

### Phase 2: Technical Grill

Trigger: user opens a fresh window and says "Read .specs/<name>.md
and run Phase 2."

Your job:
1. Read the spec file completely.
2. Grill the user on TECHNICAL APPROACH. Ask ONE question at a time.
   Wait for the answer before asking the next. The user is not a coder.
   This means:
   - Give concrete options (2-4, whatever fits the decision) with
     plain-English tradeoffs, not open-ended "how should we build
     this?" questions.
   - Bad: "What database should we use?"
   - Good: "Two options for storing this. Option A: a flat JSON file
     — simple, breaks if we get more than ~10k entries. Option B:
     SQLite — slightly more setup, scales to millions. Which fits
     better for what you described?"
3. When the approach is decided, append the Technical Approach, Files
   Likely Touched, Task List, Acceptance Criteria, and Manual
   Verification Steps sections to the spec file.
4. Task list rules: each task must be bounded enough that a fresh
   execution window can complete it without context exhaustion. If a
   task feels like it needs more than ~30 messages of work, split it.
   Mark dependencies between tasks explicitly.
5. Tell the user: "Phase 2 complete. Spec is fully written. Close this
   window and open fresh windows for execution, one per task."
6. Stop. Do not start Phase 3 in the same window.

### Phase 3: Execute One Task

Trigger: user opens a fresh window and says "Read .specs/<name>.md
and implement Task N."

Your job:
1. Read the spec file completely.
2. Confirm Task N's dependencies are satisfied (check the Execution Log
   section). If a dependency isn't done, stop and tell the user.
3. Implement Task N using TDD (red-green-refactor, vertical slices, one
   test at a time). Use the global tdd skill if installed.
4. Stay inside the task scope. If you notice something else that needs
   fixing, do not fix it — note it and tell the user at the end. Scope
   creep across tasks defeats the purpose of the bounded window.
5. Run the project's build and test commands when done.
6. Run `/verify` (the verification agent) and wait for its verdict.
7. After verification passes, explain in plain English to the user:
   - What you built (one paragraph, no code)
   - What could go wrong with it (failure modes, edge cases not covered)
   - What the user should manually test to convince themselves it works
8. Append a one-line entry to the spec's Execution Log section.
9. Tell the user: "Task N complete. Close this window and open a fresh
   one for the next task, or for the final verification pass."

### Final Verification Pass

Trigger: user opens a fresh window after all tasks are merged and says
"Read .specs/<name>.md and run final verification."

Your job:
1. Read the spec file completely.
2. Run build, lint, and full test suite across the integrated changes.
3. Run `/verify` against the merged diff (use git diff against the
   merge base, not just the last commit).
4. Walk through every item in Acceptance Criteria. For each, show the
   command or test that proves it's met. If any item cannot be verified
   automatically, tell the user explicitly which ones need manual checks.
5. Walk through Manual Verification Steps and remind the user to do them.
6. Update the spec status checkboxes.

## Hard Rules

- **Never combine phases in one window.** The cognitive offload only
  works if planning conversations end and the spec file becomes the
  sole source of truth. If the user tries to combine phases, refuse
  and remind them why.
- **Never proceed without the spec file.** If a user asks you to build
  something and there's no spec, your first response is "let's do
  Phase 1 — what are we building?" One-line fixes are the only exception.
- **Never edit the spec file during Phase 3.** The spec is locked once
  Phase 2 ends. The only exception is appending to the Execution Log.
  If execution reveals the spec was wrong, stop and tell the user —
  they decide whether to fix the spec or change the task.
- **Never silently expand scope.** If you find yourself wanting to fix
  something outside the current task, write it down and surface it.
  Do not fix it.
- **Always end Phase 3 tasks with a plain-English explanation.** The
  user is comfortable seeing code details but also needs a plain-English
  summary. Lead with what it does in simple terms, then include
  technical details. Verification passing is necessary but not
  sufficient — the user needs to understand what was built well enough
  to manually sanity-check it.
- **Always write a handoff prompt before ending a session with follow-up
  work.** If a session leaves any work undone — next task, deferred bug,
  final verification, anything that will need a fresh window — write the
  exact prompt the user should paste into the next window. Include file
  paths, line numbers, spec file references, and the context the next
  session needs. The user should never have to reconstruct state from memory.

## Project-Specific Rules

- Test command: `pytest`
- Build command: `python -X utf8 build.py`
- Lint command: `ruff check`
- Scraper boundary rule: never hit live nursery sites in tests — mock all HTTP at the requests/urllib boundary
- Data sensitivity: never paste plant price data, affiliate URLs, or retailer configs into web tools or external services
- Static site output: `site/` directory is generated — never edit files in `site/` directly, always edit templates or build.py
