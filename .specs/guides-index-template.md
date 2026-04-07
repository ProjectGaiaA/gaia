# Spec: Convert guides/index.html to Jinja2 Template

**Status**: Executing
**Commander decision**: Direct execute (scope clear, same pattern as disclosure/privacy)

## Problem

`guides/index.html` is the LAST page built with a raw f-string (build.py lines 1247-1296).
It is missing:
- `google-site-verification` meta tag (present in base.html)
- Consistent nav/footer (hardcoded, drifts from base.html)
- `og:url` meta tag via base.html
- `About` link in nav and footer (hardcoded version is stale)

## Scope Decisions

- Create `templates/guides_index.html` extending `base.html`
- Replace the f-string block in `build.py` with `env.get_template("guides_index.html").render(...)`
- Pass `guides` list and `canonical_url` to the template
- Guide card snippet logic moves to the template (Jinja2 loop)

## Out of Scope

- Guide index page redesign
- Schema markup for guides index
- Any changes to individual guide pages

## Technical Approach

Same pattern as disclosure.html / privacy.html conversion:
1. Template extends base.html, overrides `title`, `description`, `content` blocks
2. build.py passes `guides` list (title + slug + snippet) and `canonical_url`
3. Template loops over guides to render cards

## Files Touched

- `templates/guides_index.html` (new)
- `build.py` (replace lines 1227-1299)
- `tests/test_build_pages.py` (add assertions for base.html integration)

## Acceptance Criteria

- [x] `guides/index.html` extends base.html
- [x] `google-site-verification` meta tag present in output
- [x] Nav and footer match base.html (About link, etc.)
- [x] All guide links still work
- [x] `canonical` and `og:url` tags present
- [x] All existing tests pass
- [x] New tests pass

## Execution Log

- Task 1: TDD implementation — completed in this window
