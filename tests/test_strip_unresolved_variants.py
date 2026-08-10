"""Tests for scripts/strip_unresolved_variants.py.

The original inline version of this cleanup matched tier KEYS against
"variant-", which _normalize_size had already renamed to "default" — so
it stripped nothing, ever. The script matches raw_size instead.
"""

import json

from scripts.strip_unresolved_variants import strip_file


def _write_jsonl(path, entries):
    with open(path, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e) + "\n")


def _read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_strips_unresolved_variant_by_raw_size(tmp_path):
    """A tier whose raw_size is variant-{sku} is removed even though its
    key was normalized to 'default'."""
    path = tmp_path / "plant.jsonl"
    _write_jsonl(path, [{
        "retailer_id": "fgt",
        "timestamp": "2026-08-01T10:00:00+00:00",
        "sizes": {
            "1gal": {"price": 30.0, "raw_size": "1 Gallon"},
            "default": {"price": 775.95, "raw_size": "variant-44231189737634"},
        },
    }])
    stripped, modified = strip_file(str(path))
    assert stripped == 1 and modified
    sizes = _read_jsonl(path)[0]["sizes"]
    assert "default" not in sizes
    assert sizes["1gal"]["price"] == 30.0


def test_keeps_legitimate_default_title(tmp_path):
    """Shopify's single-variant 'Default Title' is a real resolved price
    and must NOT be stripped."""
    path = tmp_path / "plant.jsonl"
    entries = [{
        "retailer_id": "spring-hill",
        "timestamp": "2026-08-01T10:00:00+00:00",
        "sizes": {"default": {"price": 4.49, "raw_size": "Default Title"}},
    }]
    _write_jsonl(path, entries)
    stripped, modified = strip_file(str(path))
    assert stripped == 0 and not modified
    assert _read_jsonl(path) == entries


def test_untouched_file_not_rewritten(tmp_path):
    """A file with nothing to strip keeps its exact bytes."""
    path = tmp_path / "plant.jsonl"
    _write_jsonl(path, [{
        "retailer_id": "nh",
        "timestamp": "2026-08-01T10:00:00+00:00",
        "sizes": {"quart": {"price": 19.99, "raw_size": "1 Quart"}},
    }])
    before = path.read_bytes()
    stripped, modified = strip_file(str(path))
    assert stripped == 0 and not modified
    assert path.read_bytes() == before
