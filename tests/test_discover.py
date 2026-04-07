"""Tests for handle discovery fuzzy matching (scrapers/discover_handles.py)."""

from scrapers.discover_handles import match_score, normalize_for_matching


# --- Normalization ---


def test_normalize_removes_common_suffixes():
    assert "limelight hydrangea" == normalize_for_matching("Limelight Hydrangea Tree")
    assert "bloodgood japanese maple" == normalize_for_matching("Bloodgood Japanese Maple Shrub")


def test_normalize_removes_trademark_symbols():
    result = normalize_for_matching("Knock Out® Rose Bush")
    assert "®" not in result


def test_normalize_removes_botanical_parenthetical():
    result = normalize_for_matching("Limelight Hydrangea (Hydrangea paniculata)")
    assert "paniculata" not in result


def test_normalize_strips_proven_winners_prefix():
    result = normalize_for_matching("Proven Winners® Limelight Prime")
    assert "proven winners" not in result
    assert "limelight prime" in result


# --- Match scoring ---


def test_exact_match_after_normalization():
    """Exact name match (after normalization) should score 1.0."""
    score = match_score("Limelight Hydrangea", "Limelight Hydrangea Tree")
    assert score == 1.0


def test_partial_word_overlap():
    """Partial word overlap should score proportionally."""
    score = match_score("Honeycrisp Apple", "Honeycrisp Apple Tree for Sale")
    assert 0.5 < score <= 1.0


def test_no_match_scores_low():
    """Completely unrelated names should score near 0."""
    score = match_score("Limelight Hydrangea", "Red Knockout Rose")
    assert score < 0.5


def test_empty_strings_score_zero():
    assert match_score("", "Something") == 0.0
    assert match_score("Something", "") == 0.0
