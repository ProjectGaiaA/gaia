"""Regenerate the frozen corpus snapshot that
tests/test_audit_regional_render.py pins its census numbers against.

NOT RUN BY PYTEST. This reads the live data/ tree and rewrites this directory;
running it is a deliberate act that produces a reviewable diff, which is the
whole point of freezing the snapshot in the first place. Run it from the repo
root when the reference is re-captured, then update the pinned numbers in
tests/test_audit_regional_render.py to match the new MANIFEST.json.

WHY THE SNAPSHOT IS REDUCED RATHER THAN A STRAIGHT COPY
------------------------------------------------------
data/prices/ is ~40 MB. The audit reads only a row's retailer_id, timestamp
and per-tier price/was_price, and the vocabulary predicate reads only
raw_size, so the snapshot keeps those and drops the rest:

  * fast-growing-trees rows for the nine plants the reference covers, in the
    real corpus shape (2,378 rows, ~0.8 MB), so run() drives them through the
    same loader as production data. Scoping to those nine is safe only while
    no FGT row outside them carries a vocabulary hit, so that is ASSERTED at
    build time rather than assumed.
  * planting-tree rows collapsed to a label census: the ordered raw_size tuple
    with a multiplicity count, 78 distinct tuples standing in for 19,688 rows.
    The predicate reads nothing else, so the counts stay exact.
"""

import collections
import glob
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.getcwd())

from scrapers.shopify import (  # noqa: E402
    _REGIONAL_SIZE_VOCAB_RE,
    _has_regional_size_vocabulary,
)

OUT = os.path.join("tests", "fixtures", "regional_audit")
REFERENCE = os.path.join("data", "regional_reference", "fast-growing-trees.json")
RAW_CAPTURE = os.path.join(
    "data", "regional_reference", "fast-growing-trees.raw-capture.json"
)

# The only cell keys anything downstream reads: the audit's priced_tiers()
# takes price and was_price, the vocabulary predicate takes raw_size, and
# available is kept because it is cheap and reviewers expect to see it.
KEEP_CELL = ("price", "was_price", "raw_size", "available")


def _labels(row):
    return [
        (cell or {}).get("raw_size") or ""
        for cell in (row.get("sizes") or {}).values()
        if isinstance(cell, dict)
    ]


def _iter_rows(retailer_id):
    """(plant, row) for every committed row of one retailer."""
    for path in sorted(glob.glob(os.path.join("data", "prices", "*.jsonl"))):
        plant = os.path.basename(path)[:-6]
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("retailer_id") == retailer_id:
                    yield plant, row


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def check_scoping_is_lossless(plants):
    """The snapshot keeps FGT rows only for the reference's own plants.

    That leaves the vocabulary/audit union census unchanged ONLY IF no FGT row
    outside those plants carries a regional size-vocabulary hit. Assert it
    rather than believe it: if the retailer starts serving regional renders on
    a tenth product, this build fails instead of quietly shrinking a number
    the test suite pins.
    """
    outside = collections.Counter()
    for plant, row in _iter_rows("fast-growing-trees"):
        if plant not in plants and _has_regional_size_vocabulary(_labels(row)):
            outside[plant] += 1
    if outside:
        raise SystemExit(
            "FGT vocabulary hits outside the reference plant set: "
            f"{dict(outside)}. Widen the snapshot scope and re-derive the "
            "union census in tests/test_audit_regional_render.py."
        )
    print("guard OK: no FGT vocabulary hit outside the reference plants")


def build_fgt_corpus(plants):
    """The FGT history for the reference's plants, in real corpus shape."""
    out_dir = os.path.join(OUT, "corpus", "prices")
    os.makedirs(out_dir, exist_ok=True)
    for stale in glob.glob(os.path.join(out_dir, "*.jsonl")):
        os.remove(stale)

    lines = collections.defaultdict(list)
    for plant, row in _iter_rows("fast-growing-trees"):
        if plant not in plants:
            continue
        sizes = {}
        for tier, cell in (row.get("sizes") or {}).items():
            if isinstance(cell, dict):
                sizes[tier] = {k: cell[k] for k in KEEP_CELL if k in cell}
            else:
                sizes[tier] = cell
        lines[plant].append(json.dumps(
            {
                "retailer_id": row["retailer_id"],
                "timestamp": row.get("timestamp"),
                "sizes": sizes,
            },
            separators=(",", ":"),
            sort_keys=True,
        ))

    for plant in sorted(plants):
        rows = lines.get(plant, [])
        _write(os.path.join(out_dir, f"{plant}.jsonl"), "".join(r + "\n" for r in rows))
        print(f"  {plant:32} {len(rows):5} rows")
    return sum(len(v) for v in lines.values())


def build_planting_tree_labels():
    """Every planting-tree row reduced to its label tuple plus a count.

    Also returns the derived figures scrapers/shopify.py quotes in prose, so
    MANIFEST.json can carry the authoritative copy that comment points at. The
    comment is a dated census and will drift; these are the frozen numbers.
    """
    per = collections.defaultdict(collections.Counter)
    for plant, row in _iter_rows("planting-tree"):
        per[plant][tuple(_labels(row))] += 1
    census = {
        plant: [[list(labels), n] for labels, n in sorted(counts.items())]
        for plant, counts in sorted(per.items())
    }
    _write(
        os.path.join(OUT, "planting_tree_size_labels.json"),
        json.dumps(census, indent=1, sort_keys=True) + "\n",
    )

    rows = sum(n for entries in census.values() for _, n in entries)
    tuples = sum(len(entries) for entries in census.values())
    matching_rows = matching_cells = 0
    matching_plants = set()
    for plant, entries in census.items():
        for labels, n in entries:
            cells = sum(1 for lb in labels if _REGIONAL_SIZE_VOCAB_RE.search(lb))
            matching_cells += cells * n
            if cells:
                matching_rows += n
                matching_plants.add(plant)
    print(
        f"planting-tree plants: {len(census)} rows: {rows} tuples: {tuples} "
        f"matching_rows: {matching_rows} matching_cells: {matching_cells}"
    )
    return {
        "plants": len(census),
        "rows": rows,
        "distinct_label_tuples": tuples,
        "matching_rows": matching_rows,
        "matching_cells": matching_cells,
        "matching_plants": sorted(matching_plants),
    }


def main():
    if not os.path.isdir(os.path.join("data", "prices")):
        raise SystemExit("run this from the repo root")

    with open(REFERENCE, encoding="utf-8") as fh:
        reference = json.load(fh)
    plants = set(reference["plants"])

    check_scoping_is_lossless(plants)
    fgt_rows = build_fgt_corpus(plants)
    print(f"FGT snapshot rows: {fgt_rows}")
    pt = build_planting_tree_labels()

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True,
    ).stdout.strip()
    with open(RAW_CAPTURE, "rb") as fh:
        normalized = fh.read().replace(b"\r\n", b"\n")

    manifest = {
        "as_of_commit": commit,
        "reference_captured_at": reference["provenance"]["captured_at"],
        "reference_raw_capture_sha256_normalized": hashlib.sha256(
            normalized
        ).hexdigest(),
        "fgt_corpus": {
            "plants": sorted(plants),
            "rows": fgt_rows,
            "scope": (
                "every fast-growing-trees row in data/prices/<plant>.jsonl for "
                "the plants the reference covers"
            ),
            "reduction": (
                "each size cell keeps only " + ", ".join(KEEP_CELL)
                + "; all other row keys dropped"
            ),
            "scoping_guard": (
                "verified at build time that no FGT row OUTSIDE these plants "
                "carries a regional size-vocabulary hit, so the union census "
                "is unchanged by the scoping"
            ),
        },
        "planting_tree_size_labels": {
            "plants": pt["plants"],
            "rows": pt["rows"],
            "distinct_label_tuples": pt["distinct_label_tuples"],
            "matching_rows": pt["matching_rows"],
            "matching_cells": pt["matching_cells"],
            "matching_plants": pt["matching_plants"],
            "scope": (
                "every planting-tree row in data/prices/, reduced to its "
                "ordered raw_size label tuple with a multiplicity count"
            ),
            "reduction": (
                f"{pt['distinct_label_tuples']} distinct label tuples stand "
                f"in for all {pt['rows']} rows; _has_regional_size_vocabulary "
                "reads only these labels, so the counts are exact"
            ),
            "authoritative_for": (
                "the dated census quoted in the _REGIONAL_RENDER_RETAILERS "
                "comment in scrapers/shopify.py. That comment drifts as the "
                "bot appends; these figures are frozen at as_of_commit and "
                "are the ones to believe."
            ),
        },
        "regenerate": (
            "python tests/fixtures/regional_audit/build_snapshot.py "
            "(run from the repo root; reads live data/, rewrites this "
            "directory)"
        ),
    }
    _write(
        os.path.join(OUT, "MANIFEST.json"), json.dumps(manifest, indent=2) + "\n",
    )
    print(f"manifest at {commit}")


if __name__ == "__main__":
    main()
