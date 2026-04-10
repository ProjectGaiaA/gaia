"""Cleanup helpers for deactivated retailers.

When a retailer is turned off, its historical price records and the last
promo snapshot linger in the data files. This module owns the list of
retailers whose data has already been purged and the helper that does the
purging. Run the purge helper whenever you flip a retailer to
``active: false`` in ``data/retailers.json``.

Usage from the command line::

    python -m scrapers.cleanup --retailer brighter-blooms

This will remove every price entry where ``retailer_id == brighter-blooms``
from every ``data/prices/*.jsonl`` file and drop the matching key from
``data/promos.json``.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
PRICES_DIR = DATA_DIR / "prices"
PROMOS_PATH = DATA_DIR / "promos.json"

# Retailers whose active: false flip has already been paired with a purge.
# If you add a retailer here, make sure you've actually run purge_retailer_data
# against it — otherwise stale rows will keep showing up in the site.
PURGED_DEACTIVATED_RETAILERS: list[str] = [
    "brighter-blooms",
    "brecks",
    "plant-addicts",
    "bloomscape",
]


def purge_retailer_data(
    retailer_id: str,
    prices_dir: Path | None = None,
    promos_path: Path | None = None,
) -> dict:
    """Remove all data for a deactivated retailer.

    Strips every JSONL row in ``prices_dir/*.jsonl`` whose ``retailer_id``
    field matches, and drops the matching key from the promos JSON file.

    Returns a summary dict with ``price_rows_removed``, ``files_modified``,
    and ``promo_entry_removed``. Safe to run repeatedly — a second pass on
    already-cleaned data is a no-op.
    """
    prices_dir = prices_dir or PRICES_DIR
    promos_path = promos_path or PROMOS_PATH

    price_rows_removed = 0
    files_modified = 0

    for filepath in sorted(glob.glob(str(prices_dir / "*.jsonl"))):
        kept_lines: list[str] = []
        removed_here = 0
        with open(filepath, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.rstrip("\n").rstrip("\r")
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    # Preserve malformed lines rather than silently eating them
                    kept_lines.append(line)
                    continue
                if entry.get("retailer_id") == retailer_id:
                    removed_here += 1
                else:
                    kept_lines.append(line)
        if removed_here:
            with open(filepath, "w", encoding="utf-8") as fh:
                if kept_lines:
                    fh.write("\n".join(kept_lines) + "\n")
                # else: file is left empty (caller decides whether to delete)
            files_modified += 1
            price_rows_removed += removed_here

    promo_entry_removed = False
    if promos_path.exists():
        try:
            with open(promos_path, "r", encoding="utf-8") as fh:
                promos = json.load(fh)
        except (json.JSONDecodeError, IOError):
            promos = None
        if isinstance(promos, dict) and retailer_id in promos:
            del promos[retailer_id]
            with open(promos_path, "w", encoding="utf-8") as fh:
                json.dump(promos, fh, indent=2, ensure_ascii=False)
            promo_entry_removed = True

    return {
        "retailer_id": retailer_id,
        "price_rows_removed": price_rows_removed,
        "files_modified": files_modified,
        "promo_entry_removed": promo_entry_removed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Purge data for a deactivated retailer")
    parser.add_argument(
        "--retailer",
        required=True,
        help="retailer_id to purge (must be active: false in retailers.json)",
    )
    args = parser.parse_args()

    # Safety check: only allow purging retailers marked inactive in retailers.json
    retailers_path = DATA_DIR / "retailers.json"
    with open(retailers_path, "r", encoding="utf-8") as fh:
        retailers = json.load(fh)
    match = next((r for r in retailers if r.get("id") == args.retailer), None)
    if match is None:
        print(f"ERROR: retailer '{args.retailer}' not found in retailers.json", file=sys.stderr)
        return 2
    if match.get("active", True):
        print(
            f"ERROR: retailer '{args.retailer}' is still active: true. "
            "Flip to active: false in retailers.json first.",
            file=sys.stderr,
        )
        return 2

    summary = purge_retailer_data(args.retailer)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
