import unittest

from catalog import Catalog
from errors import NotFound, StateError, ValidationError
from licensing import (KIND_AMENDED, KIND_REGISTERED, KIND_WITHDRAWN,
                       STATUS_ACTIVE, STATUS_WITHDRAWN, USAGE_REPRODUCE,
                       LicenseLedger)
from support import T0, holder, license_, work


class LicenseLedgerTest(unittest.TestCase):
    def setUp(self):
        self.catalog = Catalog()
        self.catalog.register_holder(holder("H-1"))
        self.catalog.register_work(work("W-1", ("H-1",)))
        self.ledger = LicenseLedger(self.catalog)

    def register(self, lic=None):
        return self.ledger.register(lic or license_(), actor_id="registrar-1", at=T0)

    def test_register_records_event_and_current_state(self):
        self.register()
        self.assertEqual(self.ledger.current("L-1").revision, 1)
        self.assertEqual(self.ledger.status("L-1"), STATUS_ACTIVE)
        kinds = [event.kind for event in self.ledger.history("L-1")]
        self.assertEqual(kinds, [KIND_REGISTERED])

    def test_register_requires_verifiable_source(self):
        with self.assertRaises(ValidationError):
            self.register(license_(source_ref=""))
        with self.assertRaises(ValidationError):
            self.register(license_(source_hash=""))

    def test_register_rejects_holder_not_of_work(self):
        self.catalog.register_holder(holder("H-9", "无关第三方"))
        with self.assertRaises(ValidationError):
            self.register(license_(holder_id="H-9"))

    def test_register_rejects_unknown_work(self):
        with self.assertRaises(NotFound):
            self.register(license_(work_id="W-9"))

    def test_register_rejects_invalid_window_and_revision(self):
        with self.assertRaises(ValidationError):
            self.register(license_(valid_until=T0))  # valid_until <= valid_from
        with self.assertRaises(ValidationError):
            self.register(license_(revision=2))

    def test_second_active_license_for_same_holder_rejected(self):
        self.register()
        with self.assertRaises(ValidationError):
            self.register(license_(license_id="L-2"))

    def test_commercial_sale_requires_royalty_term(self):
        with self.assertRaises(ValidationError):
            self.register(license_(royalty=None))
        # 不含商业销售的授权可以没有版税条款
        self.register(license_(usages=frozenset({USAGE_REPRODUCE}), royalty=None))
        self.assertEqual(self.ledger.status("L-1"), STATUS_ACTIVE)

    def test_amend_keeps_history_and_bumps_revision(self):
        self.register()
        self.ledger.amend(license_(revision=2, quantity_cap=2000),
                          actor_id="registrar-1", at=T0, reason="追加数量")
        self.assertEqual(self.ledger.current("L-1").quantity_cap, 2000)
        kinds = [event.kind for event in self.ledger.history("L-1")]
        self.assertEqual(kinds, [KIND_REGISTERED, KIND_AMENDED])
        # 历史版本仍可追溯
        self.assertEqual(self.ledger.history("L-1")[0].license.quantity_cap, 1000)

    def test_amend_requires_reason_and_next_revision(self):
        self.register()
        with self.assertRaises(ValidationError):
            self.ledger.amend(license_(revision=2), actor_id="r", at=T0, reason=" ")
        with self.assertRaises(ValidationError):
            self.ledger.amend(license_(revision=3), actor_id="r", at=T0, reason="跳版")

    def test_withdraw_keeps_facts_and_blocks_further_changes(self):
        self.register()
        self.ledger.withdraw("L-1", actor_id="registrar-1", at=T0, reason="展期提前结束")
        self.assertEqual(self.ledger.status("L-1"), STATUS_WITHDRAWN)
        self.assertIsNone(self.ledger.active_for("W-1", "H-1"))
        kinds = [event.kind for event in self.ledger.history("L-1")]
        self.assertEqual(kinds, [KIND_REGISTERED, KIND_WITHDRAWN])
        with self.assertRaises(StateError):
            self.ledger.amend(license_(revision=2), actor_id="r", at=T0, reason="x")
        with self.assertRaises(StateError):
            self.ledger.withdraw("L-1", actor_id="r", at=T0, reason="x")

    def test_withdraw_requires_reason(self):
        self.register()
        with self.assertRaises(ValidationError):
            self.ledger.withdraw("L-1", actor_id="r", at=T0, reason="")

    def test_reregister_allowed_after_withdraw(self):
        self.register()
        self.ledger.withdraw("L-1", actor_id="r", at=T0, reason="合作终止")
        self.register(license_(license_id="L-2"))
        self.assertEqual(self.ledger.active_for("W-1", "H-1").license_id, "L-2")


if __name__ == "__main__":
    unittest.main()
