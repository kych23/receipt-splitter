"""Integer-cent money helpers. No floats or Decimal: every result sums exactly to its input."""


def split_evenly(amount_cents: int, n: int, start_offset: int) -> list[int]:
    """Split a non-negative amount into ``n`` parts that differ by at most 1 cent.

    The ``amount_cents % n`` leftover cents go to indices ``(start_offset + j) % n`` for
    ``j in range(amount_cents % n)``, so callers can rotate who receives the extra pennies.
    """
    if amount_cents < 0:
        raise ValueError(f"amount_cents must be >= 0, got {amount_cents}")
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    if start_offset < 0:
        raise ValueError(f"start_offset must be >= 0, got {start_offset}")

    base, leftover = divmod(amount_cents, n)
    parts = [base] * n
    for j in range(leftover):
        parts[(start_offset + j) % n] += 1
    return parts


def allocate_proportionally(amount_cents: int, weights: list[int]) -> list[int]:
    """Allocate ``amount_cents`` in proportion to ``weights`` using largest-remainder rounding.

    Each share is within 1 cent of its exact proportional value and the shares sum exactly to
    ``amount_cents``. Remainder ties go to the lower index. Negative amounts are allocated by
    magnitude and negated. If every weight is zero the amount is split evenly.
    """
    if not weights:
        raise ValueError("weights must be non-empty")
    if any(weight < 0 for weight in weights):
        raise ValueError("weights must all be >= 0")

    if amount_cents < 0:
        return [-share for share in allocate_proportionally(-amount_cents, weights)]

    total_weight = sum(weights)
    if total_weight == 0:
        return split_evenly(amount_cents, len(weights), 0)

    floors: list[int] = []
    remainders: list[int] = []
    for weight in weights:
        floor, remainder = divmod(amount_cents * weight, total_weight)
        floors.append(floor)
        remainders.append(remainder)

    leftover = amount_cents - sum(floors)
    by_largest_remainder = sorted(range(len(weights)), key=lambda i: (-remainders[i], i))
    for index in by_largest_remainder[:leftover]:
        floors[index] += 1
    return floors
