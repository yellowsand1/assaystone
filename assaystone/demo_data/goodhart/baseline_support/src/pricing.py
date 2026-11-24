"""Order pricing for the support-integrity fixture."""


def total(unit_price: float, quantity: int) -> float:
    return round(unit_price * quantity, 2)
