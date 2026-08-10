"""Strip price tiers whose size could not be resolved to a real size.

When the SKU-to-size map fails, shopify.py records the tier with a
raw_size of "variant-{sku}"; _normalize_size then collapses the tier KEY
to "default". The original version of this cleanup (inline in scrape.yml)
matched the tier key against "variant-" — which no longer exists by this
point — so it stripped nothing, ever, while 61 unresolved entries
accumulated. The marker survives in raw_size, so that is what we match.

Rows like Shopify's legitimate single-variant "Default Title" are NOT
stripped: they resolved to a real price for the product's only form.

Usage: python scripts/strip_unresolved_variants.py [--prices-dir DIR]
Prints a summary; exits 0 always (stripping nothing is a valid outcome).
"""

import argparse
import glob
import json
import os


def strip_file(path):
    """Strip unresolved-variant tiers from one JSONL file.

    Returns (stripped_tier_count, modified). Rewrites the file only when
    something was stripped.
    """
    lines = []
    stripped = 0
    modified = False
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            entry = json.loads(line)
            sizes = entry.get("sizes", {})
            clean = {
                key: val
                for key, val in sizes.items()
                if not (
                    isinstance(val, dict)
                    and str(val.get("raw_size", "")).startswith("variant-")
                )
            }
            if len(clean) < len(sizes):
                stripped += len(sizes) - len(clean)
                entry["sizes"] = clean
                modified = True
            lines.append(json.dumps(entry, ensure_ascii=False))
    if modified:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    return stripped, modified


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prices-dir", default="data/prices")
    args = parser.parse_args()

    total = 0
    files_changed = 0
    for path in sorted(glob.glob(os.path.join(args.prices_dir, "*.jsonl"))):
        stripped, modified = strip_file(path)
        total += stripped
        if modified:
            files_changed += 1
    print(f"Stripped {total} unresolved-variant tiers across {files_changed} files")


if __name__ == "__main__":
    main()
