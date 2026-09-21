import unittest
from decimal import Decimal

from errors import PermissionDenied, ValidationError
from impact import TASK_ROYALTY
from licensing import RoyaltyTerm
from service import (ROLE_ADMIN, ROLE_CURATOR, ROLE_FINANCE, ROLE_REGISTRAR,
                     ROLE_SUPPLY)
from support import actor, at, boot, drive_gates, license_


class SaleRecordingTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()
        drive_gates(self.s)
        self.release = self.s.freeze(actor(ROLE_CURATOR), "P-1", at(10))

    def test_oversell_beyond_frozen_quantity_rejected(self):
        self.s.record_sale(actor(ROLE_SUPPLY), self.release.release_id,
                           channel="电商", territory="CN", units=500, gross="100000",
                           period="2026-04", at=at(100))
        with self.assertRaises(ValidationError):
            self.s.record_sale(actor(ROLE_SUPPLY), self.release.release_id,
                               channel="电商", territory="CN", units=1, gross="200",
                               period="2026-04", at=at(101))

    def test_sale_units_must_be_positive(self):
        with self.assertRaises(ValidationError):
            self.s.record_sale(actor(ROLE_SUPPLY), self.release.release_id,
                               channel="电商", territory="CN", units=0, gross="0",
                               period="2026-04", at=at(100))


class RoyaltyReconcileTest(unittest.TestCase):
    def test_per_unit_royalty(self):
        s = boot()
        drive_gates(s)
        release = s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        supply = actor(ROLE_SUPPLY)
        s.record_sale(supply, release.release_id, channel="电商", territory="CN",
                      units=100, gross="20000", period="2026-04", at=at(100))
        s.record_sale(supply, release.release_id, channel="馆内门店", territory="CN",
                      units=50, gross="9500", period="2026-04", at=at(110))
        stmt = s.reconcile(actor(ROLE_FINANCE), "L-1", period="2026-04", at=at(120))
        self.assertEqual(stmt.units, 150)
        self.assertEqual(stmt.gross, Decimal("29500"))
        self.assertEqual(stmt.due, Decimal("750"))  # 150 件 × 5 CNY
        self.assertEqual(stmt.currency, "CNY")

    def test_percent_royalty(self):
        s = boot()
        drive_gates(s)
        s.amend_license(actor(ROLE_REGISTRAR),
                        license_(revision=2,
                                 royalty=RoyaltyTerm("percent", Decimal("8"), "CNY")),
                        at(5), reason="改为销售分成")
        release = s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        s.record_sale(actor(ROLE_SUPPLY), release.release_id, channel="电商",
                      territory="CN", units=10, gross="10000",
                      period="2026-04", at=at(100))
        stmt = s.reconcile(actor(ROLE_FINANCE), "L-1", period="2026-04", at=at(120))
        self.assertEqual(stmt.due, Decimal("800"))  # 10000 × 8%

    def test_reconcile_is_audited(self):
        s = boot()
        drive_gates(s)
        s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        s.reconcile(actor(ROLE_FINANCE), "L-1", period="2026-04", at=at(120))
        entries = s.audit.of(action="royalty_reconciled", entity="license:L-1")
        self.assertEqual(len(entries), 1)
        self.assertIn("应结版税", entries[0].detail)


class RoyaltySettlementTaskTest(unittest.TestCase):
    def test_royalty_task_completed_by_finance_only(self):
        s = boot()
        drive_gates(s)
        s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        s.withdraw_license(actor(ROLE_REGISTRAR), "L-1", at(20), reason="合作结束")
        task = [t for t in s.tasks(actor(ROLE_ADMIN)) if t.kind == TASK_ROYALTY][0]
        with self.assertRaises(PermissionDenied):
            s.complete_task(actor(ROLE_SUPPLY), task.task_id, note="越权", at=at(21))
        done = s.complete_task(actor(ROLE_FINANCE), task.task_id,
                               note="已结算 750 CNY", at=at(21))
        self.assertEqual(done.status, "done")
        with self.assertRaises(Exception):
            s.complete_task(actor(ROLE_FINANCE), task.task_id, note="重复", at=at(22))


if __name__ == "__main__":
    unittest.main()
