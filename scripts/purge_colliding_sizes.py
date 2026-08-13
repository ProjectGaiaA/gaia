"""One-shot repair of price rows whose size tier key their raw_size no longer supports.

WHY THIS EXISTS
---------------
`data/prices/*.jsonl` is append-only, and every row stores the size tier the
scraper computed AT THE TIME IT WAS WRITTEN. Fixing `_normalize_size` therefore
fixes nothing a visitor can see: `build.py` renders the LATEST row per
(plant, retailer), and that row still carries the old key. The live defect —
planting-tree's Nellie Stevens Holly advertising a SOLD-OUT "2 Quart" at $13.95
in the `quart` column while the retailer sold "1 Quart" at $21.95 — survives the
scraper fix until the row is repaired or the next scrape overwrites it, and a
retailer that drops a product never overwrites anything.

WHAT IT DOES
------------
For every row of every shopify-scraped retailer, it recomputes the tier from the
row's own `raw_size` and moves the cell if the answer differs. Nothing is
invented: the price, the stock flag and the raw label are carried across
unchanged. Only the KEY — the claim about what the price is a price OF — changes.

Rows from custom scrapers (Stark Bros) are left alone; they have their own
normaliser and `_normalize_size` would mis-key them.

If a move lands on a tier the same row already occupies, the two cells are
resolved exactly as `scrapers.shopify._record_size` resolves a live collision:
identical price and stock means one product listed twice and the duplicate is
dropped; anything else means two products claiming one tier, and NEITHER is
kept, because publishing an arbitrary winner is the defect this repairs.

Idempotent: a second run reports 0 changes. Prints every count with its
denominator.

    python -X utf8 -m scripts.purge_colliding_sizes --dry-run
    python -X utf8 -m scripts.purge_colliding_sizes --apply
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapers.shopify import ShopifyScraper  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRICES_DIR = os.path.join(REPO, "data", "prices")
RETAILERS = os.path.join(REPO, "data", "retailers.json")


def shopify_retailer_ids(path=RETAILERS):
    with open(path, "r", encoding="utf-8") as f:
        return {r["id"] for r in json.load(f) if r.get("scraper_type") == "shopify"}


def repair_row(row, normalize, shopify_ids):
    """Return (new_sizes, moved, dropped) for one JSONL row. Pure."""
    sizes = row.get("sizes")
    if row.get("retailer_id") not in shopify_ids or not isinstance(sizes, dict):
        return sizes, 0, 0

    out, quarantined = {}, set()
    moved = dropped = 0
    for tier, cell in sizes.items():
        if not isinstance(cell, dict) or cell.get("raw_size") is None:
            target = tier
        else:
            target = normalize(cell["raw_size"])
        if target != tier:
            moved += 1
        if target in quarantined:
            dropped += 1
            continue
        held = out.get(target)
        if held is None:
            out[target] = cell
            continue
        if (held.get("price"), held.get("available")) == (
            cell.get("price"), cell.get("available")
        ):
            dropped += 1          # same product listed twice
            continue
        del out[target]
        quarantined.add(target)
        dropped += 2              # neither survives
    return out, moved, dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="write the repaired files")
    ap.add_argument("--dry-run", action="store_true", help="report only (default)")
    args = ap.parse_args(argv)

    normalize = ShopifyScraper("purge", "http://localhost")._normalize_size
    shopify_ids = shopify_retailer_ids()

    files = sorted(f for f in os.listdir(PRICES_DIR) if f.endswith(".jsonl"))
    tot_rows = tot_cells = moved = dropped = 0
    touched_files = []
    for fn in files:
        path = os.path.join(PRICES_DIR, fn)
        with open(path, "r", encoding="utf-8") as f:
            lines = [ln.rstrip("\n") for ln in f]
        out_lines, file_moved, file_dropped = [], 0, 0
        for line in lines:
            if not line.strip():
                out_lines.append(line)
                continue
            row = json.loads(line)
            tot_rows += 1
            tot_cells += len(row.get("sizes") or {})
            new_sizes, m, d = repair_row(row, normalize, shopify_ids)
            file_moved += m
            file_dropped += d
            if m or d:
                row["sizes"] = new_sizes
                out_lines.append(json.dumps(row, ensure_ascii=False))
            else:
                out_lines.append(line)
        moved += file_moved
        dropped += file_dropped
        if file_moved or file_dropped:
            touched_files.append((fn, file_moved, file_dropped))
            if args.apply:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write("\n".join(out_lines) + "\n")

    print(f"price files scanned:        {len(files)}")
    print(f"rows scanned:               {tot_rows}")
    print(f"size cells scanned:         {tot_cells}")
    print(f"cells re-keyed:             {moved} / {tot_cells}")
    print(f"cells dropped as colliding: {dropped} / {tot_cells}")
    print(f"files touched:              {len(touched_files)} / {len(files)}")
    for fn, m, d in touched_files:
        print(f"  {fn}: {m} re-keyed, {d} dropped")
    print("APPLIED" if args.apply else "DRY RUN — nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
