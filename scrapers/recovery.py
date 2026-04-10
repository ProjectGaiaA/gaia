"""
Recovery State Management — Detect and recover broken product URLs.

Manages recovery.json which tracks products with broken handles (404),
redirect candidates (301/302), and discovery candidates. The scraper
writes entries here; Opus reviews candidates; the scraper validates
confirmed candidates on startup before writing to handle_maps.json.

recovery.json is never overwritten wholesale — only individual entries
are added, updated, or removed. This prevents data loss if the scraper
crashes mid-write.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

RECOVERY_PATH = Path(__file__).parent.parent / "data" / "recovery.json"


@dataclass
class FetchResult:
    """Result of an HTTP fetch with status code and redirect info.

    Replaces the raw dict|None return of _get_json() so callers can
    distinguish 404 (handle changed) from 5xx (server hiccup) from
    redirect (handle renamed with a redirect in place).
    """

    data: dict | None
    status_code: int | None
    redirect_url: str | None


def load_recovery() -> dict:
    """Load recovery state from data/recovery.json.

    Returns a dict with an "entries" key mapping
    "{retailer_id}:{plant_id}" to entry dicts. Creates an empty
    structure if the file doesn't exist or is malformed.
    """
    if not RECOVERY_PATH.exists():
        return {"entries": {}}
    try:
        with open(RECOVERY_PATH, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or "entries" not in state:
            return {"entries": {}}
        return state
    except (json.JSONDecodeError, IOError):
        logger.warning("recovery.json is malformed — starting fresh")
        return {"entries": {}}


def save_recovery(state: dict) -> None:
    """Write recovery state to data/recovery.json."""
    RECOVERY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RECOVERY_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _entry_key(retailer_id: str, plant_id: str) -> str:
    return f"{retailer_id}:{plant_id}"


def record_broken(retailer_id: str, plant_id: str, old_handle: str) -> None:
    """Record a broken handle (404) in recovery.json.

    If an entry already exists for this retailer+plant, only updates it
    if it's not already being tracked (avoids overwriting candidates or
    confirmed entries).
    """
    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    now = datetime.now(timezone.utc).isoformat()

    existing = state["entries"].get(key)
    if existing and existing.get("status") in (
        "redirect_candidate",
        "discovery_candidate",
        "confirmed",
    ):
        # Don't overwrite a candidate that's already in-flight
        return

    state["entries"][key] = {
        "retailer_id": retailer_id,
        "plant_id": plant_id,
        "old_handle": old_handle,
        "status": "broken",
        "candidate_handle": None,
        "redirect_url": None,
        "attempts": existing["attempts"] if existing else 0,
        "last_discovery_attempt": existing.get("last_discovery_attempt") if existing else None,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        "plant_common_name": None,
        "botanical_name": None,
        "candidate_title": None,
        "match_score": None,
        "old_sizes_prices": {},
        "candidate_sizes_prices": {},
        "reason": None,
    }
    save_recovery(state)
    logger.info(f"Recovery: recorded broken handle {retailer_id}/{plant_id} ({old_handle})")


def record_redirect_candidate(
    retailer_id: str,
    plant_id: str,
    old_handle: str,
    new_handle: str,
    redirect_url: str,
) -> None:
    """Record a redirect candidate (301/302) in recovery.json."""
    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    now = datetime.now(timezone.utc).isoformat()

    existing = state["entries"].get(key)

    state["entries"][key] = {
        "retailer_id": retailer_id,
        "plant_id": plant_id,
        "old_handle": old_handle,
        "status": "redirect_candidate",
        "candidate_handle": new_handle,
        "redirect_url": redirect_url,
        "attempts": 0,
        "last_discovery_attempt": None,
        "created_at": existing["created_at"] if existing else now,
        "updated_at": now,
        "plant_common_name": None,
        "botanical_name": None,
        "candidate_title": None,
        "match_score": None,
        "old_sizes_prices": {},
        "candidate_sizes_prices": {},
        "reason": None,
    }
    save_recovery(state)
    logger.info(
        f"Recovery: redirect candidate {retailer_id}/{plant_id} "
        f"{old_handle} -> {new_handle}"
    )


def get_confirmed_candidates() -> list[dict]:
    """Return all entries with status 'confirmed'."""
    state = load_recovery()
    return [
        entry
        for entry in state["entries"].values()
        if entry.get("status") == "confirmed"
    ]


def mark_applied(retailer_id: str, plant_id: str) -> None:
    """Remove a confirmed entry after its handle was written to handle_maps.json."""
    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    if key in state["entries"]:
        del state["entries"][key]
        save_recovery(state)
        logger.info(f"Recovery: applied and removed {key}")


def mark_confirmation_failed(retailer_id: str, plant_id: str) -> None:
    """Flag a confirmed candidate that still 404s when validated."""
    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    entry = state["entries"].get(key)
    if entry:
        entry["status"] = "confirmation_failed"
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        entry["reason"] = "Confirmed handle still returns 404"
        save_recovery(state)
        logger.warning(f"Recovery: confirmed candidate {key} still 404s — flagged")


def get_pending_candidates() -> list[dict]:
    """Return all entries with status 'redirect_candidate' or 'discovery_candidate'.

    These are candidates awaiting Opus review.
    """
    state = load_recovery()
    return [
        entry
        for entry in state["entries"].values()
        if entry.get("status") in ("redirect_candidate", "discovery_candidate")
    ]


def set_verdict(retailer_id: str, plant_id: str, verdict: str, reason: str) -> None:
    """Set an Opus review verdict on a recovery entry.

    Args:
        retailer_id: Retailer identifier.
        plant_id: Plant identifier.
        verdict: Must be "confirmed" or "rejected".
        reason: Brief explanation of the verdict.

    Raises:
        ValueError: If verdict is not "confirmed" or "rejected".
    """
    if verdict not in ("confirmed", "rejected"):
        raise ValueError(f"verdict must be 'confirmed' or 'rejected', got '{verdict}'")

    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    entry = state["entries"].get(key)
    if not entry:
        logger.warning(f"Recovery: set_verdict called for missing entry {key} — ignoring")
        return

    entry["status"] = verdict
    entry["reason"] = reason
    entry["updated_at"] = datetime.now(timezone.utc).isoformat()
    save_recovery(state)
    logger.info(f"Recovery: {key} verdict={verdict} reason={reason}")


def extract_handle_from_url(url: str) -> str | None:
    """Extract a Shopify product handle from a URL.

    Examples:
        https://shop.com/products/new-handle.json -> new-handle
        https://shop.com/products/new-handle -> new-handle
        /products/new-handle.json -> new-handle
    """
    # Strip query params and fragment
    path = url.split("?")[0].split("#")[0]
    # Find /products/HANDLE pattern
    parts = path.split("/products/")
    if len(parts) < 2:
        return None
    handle = parts[-1].strip("/")
    # Remove .json suffix
    if handle.endswith(".json"):
        handle = handle[:-5]
    return handle if handle else None


# ---------------------------------------------------------------------------
# Recovery orchestration — Task 4
# ---------------------------------------------------------------------------

COOLDOWN_HOURS = 20
MAX_ATTEMPTS = 7


def get_actionable_entries() -> list[dict]:
    """Return recovery entries that need discovery work.

    An entry is actionable when:
    - status is "broken"
    - attempts < MAX_ATTEMPTS (7)
    - last_discovery_attempt is None or > COOLDOWN_HOURS (20) ago
    """
    state = load_recovery()
    now = datetime.now(timezone.utc)
    actionable = []

    for entry in state["entries"].values():
        if entry.get("status") != "broken":
            continue
        if entry.get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        last = entry.get("last_discovery_attempt")
        if last:
            last_dt = datetime.fromisoformat(last)
            if now - last_dt < timedelta(hours=COOLDOWN_HOURS):
                continue
        actionable.append(entry)

    return actionable


def mark_unrecoverable(retailer_id: str, plant_id: str) -> None:
    """Mark an entry as unrecoverable after exceeding attempt limit."""
    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    entry = state["entries"].get(key)
    if entry:
        entry["status"] = "unrecoverable"
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        entry["reason"] = f"No candidate found after {MAX_ATTEMPTS} attempts"
        save_recovery(state)
        logger.warning(f"Recovery: {key} marked unrecoverable after {MAX_ATTEMPTS} attempts")


def record_discovery_candidate(
    retailer_id: str,
    plant_id: str,
    candidate_handle: str,
    candidate_title: str,
    match_score: float,
    plant_common_name: str,
    botanical_name: str,
    old_sizes_prices: dict,
    candidate_sizes_prices: dict,
) -> None:
    """Record a discovery candidate with full context in recovery.json."""
    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    now = datetime.now(timezone.utc).isoformat()

    existing = state["entries"].get(key, {})

    state["entries"][key] = {
        "retailer_id": retailer_id,
        "plant_id": plant_id,
        "old_handle": existing.get("old_handle", ""),
        "status": "discovery_candidate",
        "candidate_handle": candidate_handle,
        "redirect_url": None,
        "attempts": existing.get("attempts", 0) + 1,
        "last_discovery_attempt": now,
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "plant_common_name": plant_common_name,
        "botanical_name": botanical_name,
        "candidate_title": candidate_title,
        "match_score": match_score,
        "old_sizes_prices": old_sizes_prices,
        "candidate_sizes_prices": candidate_sizes_prices,
        "reason": None,
    }
    save_recovery(state)
    logger.info(
        f"Recovery: discovery candidate {retailer_id}/{plant_id} "
        f"-> {candidate_handle} (score={match_score:.2f})"
    )


def _increment_attempt(retailer_id: str, plant_id: str) -> None:
    """Increment attempts and update last_discovery_attempt for a broken entry."""
    state = load_recovery()
    key = _entry_key(retailer_id, plant_id)
    entry = state["entries"].get(key)
    if entry:
        entry["attempts"] = entry.get("attempts", 0) + 1
        entry["last_discovery_attempt"] = datetime.now(timezone.utc).isoformat()
        entry["updated_at"] = datetime.now(timezone.utc).isoformat()
        save_recovery(state)


def _extract_variant_prices(product: dict) -> dict:
    """Extract {variant_title: price} from a Shopify product dict."""
    prices = {}
    for variant in product.get("variants", []):
        title = variant.get("title", "")
        price_str = variant.get("price", "0")
        try:
            prices[title] = float(price_str)
        except (ValueError, TypeError):
            pass
    return prices


def run(
    time_budget_seconds: float,
    data_dir: Path | None = None,
) -> dict:
    """Run recovery discovery after the scrape completes.

    Reads recovery.json, filters to actionable broken handles, fetches
    retailer catalogs, and fuzzy-matches to find candidate replacements.

    Args:
        time_budget_seconds: Max seconds to spend on discovery.
        data_dir: Override for data directory (tests).

    Returns:
        Summary dict with counts of what happened.
    """
    # Lazy import — circular: recovery → discover_handles → shopify → recovery
    from scrapers.discover_handles import fetch_all_products, match_score

    if data_dir is None:
        data_dir = Path(__file__).parent.parent / "data"

    summary = {
        "entries_processed": 0,
        "candidates_found": 0,
        "entries_marked_unrecoverable": 0,
        "entries_skipped_cooldown": 0,
        "entries_skipped_non_shopify": 0,
    }

    # --- Mark entries at attempt limit as unrecoverable ---
    state = load_recovery()
    for entry in list(state["entries"].values()):
        if entry.get("status") == "broken" and entry.get("attempts", 0) >= MAX_ATTEMPTS:
            mark_unrecoverable(entry["retailer_id"], entry["plant_id"])
            summary["entries_marked_unrecoverable"] += 1

    # --- Get actionable entries ---
    actionable = get_actionable_entries()
    if not actionable:
        logger.info("Recovery: no actionable entries — skipping")
        return summary

    # --- Check time budget ---
    if time_budget_seconds <= 0:
        logger.info("Recovery: no time budget remaining — skipping")
        return summary

    # --- Load reference data ---
    plants_path = data_dir / "plants.json"
    retailers_path = data_dir / "retailers.json"
    manifest_path = data_dir / "last_manifest.json"

    try:
        with open(plants_path, encoding="utf-8") as f:
            plants = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        plants = []

    try:
        with open(retailers_path, encoding="utf-8") as f:
            retailers = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        retailers = []

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        manifest = {}

    plants_by_id = {p["id"]: p for p in plants}
    retailers_by_id = {r["id"]: r for r in retailers}
    manifest_prices = manifest.get("prices", {})

    # --- Filter to Shopify retailers only ---
    shopify_entries = []
    for entry in actionable:
        retailer = retailers_by_id.get(entry["retailer_id"])
        if not retailer or retailer.get("scraper_type") != "shopify":
            summary["entries_skipped_non_shopify"] += 1
            continue
        shopify_entries.append(entry)

    if not shopify_entries:
        logger.info("Recovery: no Shopify entries to process — skipping")
        return summary

    # --- Group by retailer for shared catalog fetches ---
    by_retailer: dict[str, list[dict]] = {}
    for entry in shopify_entries:
        rid = entry["retailer_id"]
        by_retailer.setdefault(rid, []).append(entry)

    # --- Time-budgeted discovery ---
    start_time = time.monotonic()
    per_entry_budget = time_budget_seconds / len(shopify_entries)
    catalog_cache: dict[str, list[dict]] = {}

    logger.info(
        f"Recovery: {len(shopify_entries)} entries across "
        f"{len(by_retailer)} retailer(s), budget={time_budget_seconds:.0f}s "
        f"({per_entry_budget:.0f}s/entry)"
    )

    for rid, entries in by_retailer.items():
        elapsed = time.monotonic() - start_time
        if elapsed >= time_budget_seconds:
            logger.info("Recovery: time budget exhausted — stopping")
            break

        retailer = retailers_by_id[rid]
        base_url = retailer["url"].rstrip("/")

        # Fetch catalog once per retailer
        if rid not in catalog_cache:
            logger.info(f"Recovery: fetching catalog for {rid}...")
            try:
                catalog_cache[rid] = fetch_all_products(base_url)
            except Exception as e:
                logger.error(f"Recovery: failed to fetch catalog for {rid}: {e}")
                catalog_cache[rid] = []

        catalog = catalog_cache[rid]

        for entry in entries:
            elapsed = time.monotonic() - start_time
            if elapsed >= time_budget_seconds:
                logger.info("Recovery: time budget exhausted — stopping")
                break

            plant_id = entry["plant_id"]
            retailer_id = entry["retailer_id"]

            plant = plants_by_id.get(plant_id)
            if not plant:
                logger.warning(f"Recovery: plant {plant_id} not in plants.json — skipping")
                _increment_attempt(retailer_id, plant_id)
                summary["entries_processed"] += 1
                continue

            common_name = plant.get("common_name", "")
            botanical_name = plant.get("botanical_name", "")

            # Find best match in catalog
            best_product = None
            best_score = 0.0

            for product in catalog:
                title = product.get("title", "")
                handle = product.get("handle", "")

                # Skip the broken handle itself
                if handle == entry.get("old_handle"):
                    continue

                score = match_score(common_name, title)
                botanical_score = match_score(botanical_name, title) * 0.8
                score = max(score, botanical_score)

                if score > best_score:
                    best_score = score
                    best_product = product

            # Get old prices from manifest
            price_key = f"{plant_id}:{retailer_id}"
            old_prices = manifest_prices.get(price_key, {})

            if best_product and best_score >= 0.6:
                candidate_prices = _extract_variant_prices(best_product)
                record_discovery_candidate(
                    retailer_id=retailer_id,
                    plant_id=plant_id,
                    candidate_handle=best_product["handle"],
                    candidate_title=best_product.get("title", ""),
                    match_score=round(best_score, 2),
                    plant_common_name=common_name,
                    botanical_name=botanical_name,
                    old_sizes_prices=old_prices,
                    candidate_sizes_prices=candidate_prices,
                )
                summary["candidates_found"] += 1
            else:
                _increment_attempt(retailer_id, plant_id)
                logger.info(
                    f"Recovery: no match for {retailer_id}/{plant_id} "
                    f"(best score: {best_score:.2f})"
                )

            summary["entries_processed"] += 1

    logger.info(
        f"Recovery complete: {summary['entries_processed']} processed, "
        f"{summary['candidates_found']} candidates, "
        f"{summary['entries_marked_unrecoverable']} unrecoverable"
    )
    return summary


# ---------------------------------------------------------------------------
# Weekly email helpers — Task 7
# ---------------------------------------------------------------------------


def get_reportable_entries() -> list[dict]:
    """Return recovery entries that need operator attention.

    Collects entries with status "unrecoverable" (7 failed attempts),
    "rejected" (Opus declined the candidate), or "confirmation_failed"
    (Opus confirmed but handle still 404s at validation). These are
    surfaced in the weekly email.
    """
    state = load_recovery()
    return [
        entry
        for entry in state["entries"].values()
        if entry.get("status") in ("unrecoverable", "rejected", "confirmation_failed")
    ]


def format_recovery_email(entries: list[dict]) -> str:
    """Format reportable recovery entries into a plain-text email body.

    Groups entries by status (unrecoverable first, then rejected) and
    lists each with plant name, retailer, what went wrong, and the
    candidate handle if one was found.
    """
    if not entries:
        return ""

    unrecoverable = [e for e in entries if e.get("status") == "unrecoverable"]
    rejected = [e for e in entries if e.get("status") == "rejected"]
    confirmation_failed = [e for e in entries if e.get("status") == "confirmation_failed"]

    lines = [
        "PlantPriceTracker — Weekly Recovery Report",
        "=" * 46,
        "",
        f"{len(entries)} product(s) need attention.",
        "",
    ]

    if unrecoverable:
        lines.append(f"UNRECOVERABLE ({len(unrecoverable)})")
        lines.append("-" * 40)
        lines.append("These products failed recovery after 7 attempts.")
        lines.append("")
        for e in unrecoverable:
            plant = e.get("plant_common_name") or e.get("plant_id") or "Unknown"
            retailer = e.get("retailer_id", "Unknown")
            old_handle = e.get("old_handle", "N/A")
            lines.append(f"  - {plant} @ {retailer}")
            lines.append(f"    Old handle: {old_handle}")
            lines.append(f"    Attempts: {e.get('attempts', '?')}")
            reason = e.get("reason", "")
            if reason:
                lines.append(f"    Reason: {reason}")
            lines.append("")

    if rejected:
        lines.append(f"REJECTED BY REVIEW ({len(rejected)})")
        lines.append("-" * 40)
        lines.append("These candidates were rejected during review.")
        lines.append("")
        for e in rejected:
            plant = e.get("plant_common_name") or e.get("plant_id") or "Unknown"
            retailer = e.get("retailer_id", "Unknown")
            old_handle = e.get("old_handle", "N/A")
            candidate = e.get("candidate_handle", "N/A")
            lines.append(f"  - {plant} @ {retailer}")
            lines.append(f"    Old handle: {old_handle}")
            lines.append(f"    Candidate: {candidate}")
            reason = e.get("reason", "")
            if reason:
                lines.append(f"    Reason: {reason}")
            lines.append("")

    if confirmation_failed:
        lines.append(f"CONFIRMATION FAILED ({len(confirmation_failed)})")
        lines.append("-" * 40)
        lines.append("Opus confirmed these candidates but they still 404 at validation.")
        lines.append("")
        for e in confirmation_failed:
            plant = e.get("plant_common_name") or e.get("plant_id") or "Unknown"
            retailer = e.get("retailer_id", "Unknown")
            old_handle = e.get("old_handle", "N/A")
            candidate = e.get("candidate_handle", "N/A")
            lines.append(f"  - {plant} @ {retailer}")
            lines.append(f"    Old handle: {old_handle}")
            lines.append(f"    Candidate: {candidate}")
            reason = e.get("reason", "")
            if reason:
                lines.append(f"    Reason: {reason}")
            lines.append("")

    lines.append("---")
    lines.append("Review these in data/recovery.json and update handles manually if needed.")

    return "\n".join(lines)
