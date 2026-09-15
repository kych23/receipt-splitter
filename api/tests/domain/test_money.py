from fractions import Fraction

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.money import allocate_proportionally, split_evenly


@pytest.mark.parametrize(
    ("amount", "n", "offset", "expected"),
    [
        (1000, 3, 0, [334, 333, 333]),
        (1000, 3, 1, [333, 334, 333]),
        (0, 4, 2, [0, 0, 0, 0]),
    ],
)
def test_split_evenly_examples(amount: int, n: int, offset: int, expected: list[int]) -> None:
    assert split_evenly(amount, n, offset) == expected


@pytest.mark.parametrize(
    ("amount", "weights", "expected"),
    [
        (1, [1, 1, 1], [1, 0, 0]),
        (100, [1000, 3000], [25, 75]),
        (-300, [1000, 2000], [-100, -200]),
        (5, [0, 0], [3, 2]),
    ],
)
def test_allocate_proportionally_examples(
    amount: int, weights: list[int], expected: list[int]
) -> None:
    assert allocate_proportionally(amount, weights) == expected


@pytest.mark.parametrize(
    ("amount", "n", "offset"),
    [(5, 0, 0), (5, 2, -1), (-1, 2, 0)],
)
def test_split_evenly_rejects_invalid_arguments(amount: int, n: int, offset: int) -> None:
    with pytest.raises(ValueError):
        split_evenly(amount, n, offset)


@pytest.mark.parametrize("weights", [[1, -1], []])
def test_allocate_proportionally_rejects_invalid_weights(weights: list[int]) -> None:
    with pytest.raises(ValueError):
        allocate_proportionally(5, weights)


@given(
    amount=st.integers(min_value=0, max_value=100_000),
    n=st.integers(min_value=1, max_value=20),
    offset=st.integers(min_value=0, max_value=50),
)
def test_split_evenly_properties(amount: int, n: int, offset: int) -> None:
    parts = split_evenly(amount, n, offset)
    assert len(parts) == n
    assert sum(parts) == amount
    assert max(parts) - min(parts) <= 1


@given(
    amount=st.integers(min_value=-100_000, max_value=100_000),
    weights=st.lists(st.integers(min_value=0, max_value=100_000), min_size=1, max_size=10),
)
def test_allocate_proportionally_properties(amount: int, weights: list[int]) -> None:
    result = allocate_proportionally(amount, weights)
    assert len(result) == len(weights)
    assert sum(result) == amount
    total_weight = sum(weights)
    if total_weight > 0:
        for share, weight in zip(result, weights, strict=True):
            assert abs(share - Fraction(amount * weight, total_weight)) < 1
