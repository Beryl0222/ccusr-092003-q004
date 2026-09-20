import unittest
from datetime import datetime, timezone

from domain import Grant, validate_grant


class GrantContractTest(unittest.TestCase):
    def test_scope_and_half_open_window(self):
        grant = Grant("g-1", "w-1", "h-1", frozenset({"复制"}), datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc), 1)
        validate_grant(grant)
        self.assertTrue(grant.covers("复制", datetime(2026, 6, 1, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
