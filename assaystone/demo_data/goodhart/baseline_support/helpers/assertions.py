"""Shared assertions for the test suite."""


def assert_close(actual, expected, tolerance=0.01):
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{actual} != {expected}")
