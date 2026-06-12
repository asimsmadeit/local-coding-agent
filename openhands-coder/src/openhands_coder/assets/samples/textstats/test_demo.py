import pytest

from textstats import most_common_word


def test_basic():
    assert most_common_word("the cat and the hat") == "the"


def test_punct_case():
    assert most_common_word("Dog! dog, bird. DOG bird") == "dog"


def test_empty():
    with pytest.raises(ValueError):
        most_common_word("  ")
