"""Tests for scrapers/cleanup.py — deactivated-retailer data purge."""

import json

from scrapers.cleanup import purge_retailer_data, PURGED_DEACTIVATED_RETAILERS


def test_brighter_blooms_is_registered():
    """The brighter-blooms purge was paired with flipping it to active: false,
    so it must stay in the registered list as documentation for future runs."""
    assert "brighter-blooms" in PURGED_DEACTIVATED_RETAILERS


def test_purge_removes_matching_price_rows(tmp_path):
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    promos_path = tmp_path / "promos.json"

    # Two plant files — one has mixed retailer entries, one has only brighter-blooms
    (prices_dir / "limelight.jsonl").write_text(
        json.dumps({"retailer_id": "nature-hills", "price": 39.99}) + "\n"
        + json.dumps({"retailer_id": "brighter-blooms", "price": 44.99}) + "\n"
        + json.dumps({"retailer_id": "fast-growing-trees", "price": 42.99}) + "\n",
        encoding="utf-8",
    )
    (prices_dir / "bb-only.jsonl").write_text(
        json.dumps({"retailer_id": "brighter-blooms", "price": 29.99}) + "\n",
        encoding="utf-8",
    )
    (prices_dir / "untouched.jsonl").write_text(
        json.dumps({"retailer_id": "spring-hill", "price": 19.99}) + "\n",
        encoding="utf-8",
    )
    promos_path.write_text(
        json.dumps({
            "nature-hills": {"codes": []},
            "brighter-blooms": {"codes": ["STALE"]},
        }),
        encoding="utf-8",
    )

    summary = purge_retailer_data(
        "brighter-blooms", prices_dir=prices_dir, promos_path=promos_path
    )

    assert summary["price_rows_removed"] == 2
    assert summary["files_modified"] == 2
    assert summary["promo_entry_removed"] is True

    # Mixed file retains the non-brighter-blooms entries
    mixed = [
        json.loads(line)
        for line in (prices_dir / "limelight.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [e["retailer_id"] for e in mixed] == ["nature-hills", "fast-growing-trees"]

    # bb-only file is emptied but kept on disk
    assert (prices_dir / "bb-only.jsonl").read_text(encoding="utf-8") == ""

    # Untouched file is literally untouched
    assert "spring-hill" in (prices_dir / "untouched.jsonl").read_text(encoding="utf-8")

    # Promo entry removed but other retailers preserved
    promos = json.loads(promos_path.read_text(encoding="utf-8"))
    assert "brighter-blooms" not in promos
    assert "nature-hills" in promos


def test_purge_is_idempotent(tmp_path):
    """Running the purge twice on already-clean data is a no-op."""
    prices_dir = tmp_path / "prices"
    prices_dir.mkdir()
    (prices_dir / "plant.jsonl").write_text(
        json.dumps({"retailer_id": "nature-hills", "price": 39.99}) + "\n",
        encoding="utf-8",
    )
    promos_path = tmp_path / "promos.json"
    promos_path.write_text('{"nature-hills": {}}', encoding="utf-8")

    first = purge_retailer_data("brighter-blooms", prices_dir=prices_dir, promos_path=promos_path)
    second = purge_retailer_data("brighter-blooms", prices_dir=prices_dir, promos_path=promos_path)

    assert first["price_rows_removed"] == 0
    assert second["price_rows_removed"] == 0
    assert first["promo_entry_removed"] is False
    assert second["promo_entry_removed"] is False
