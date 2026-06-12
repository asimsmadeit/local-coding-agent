import pytest

from csvstats import column_mean

CSV = """name,score,age
alice,90,30
bob,80,
carol,not-a-number,40

dave,70,50
"""


def test_basic_mean():
    assert column_mean(CSV, "score") == pytest.approx(80.0)


def test_skips_blank_and_bad_cells():
    assert column_mean(CSV, "age") == pytest.approx(40.0)


def test_missing_column():
    with pytest.raises(KeyError):
        column_mean(CSV, "height")


def test_no_numeric_values():
    with pytest.raises(ValueError):
        column_mean("name,notes\nalice,hi\n", "notes")
