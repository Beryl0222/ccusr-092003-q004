import unittest

from errors import StateError
from impact import TASK_INVENTORY, TASK_ROYALTY, TASK_STOP_SALE
from review import GATE_LEGAL
from service import RELEASE_STOPPED, ROLE_ADMIN, ROLE_CURATOR, ROLE_REGISTRAR, ROLE_SUPPLY
from support import actor, at, boot, drive_gates, license_


class WithdrawImpactTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()
        drive_gates(self.s)
        self.release = self.s.freeze(actor(ROLE_CURATOR), "P-1", at(10))

    def test_withdraw_triggers_stop_inventory_royalty_tasks(self):
        self.s.withdraw_license(actor(ROLE_REGISTRAR), "L-1", at(20),
                                reason="展期提前结束")
        state = self.s.release_state(actor(ROLE_CURATOR), self.release.release_id)
        self.assertEqual(state, RELEASE_STOPPED)
        kinds = {t.kind for t in self.s.tasks(actor(ROLE_ADMIN), open_only=True)}
        self.assertEqual(kinds, {TASK_STOP_SALE, TASK_INVENTORY, TASK_ROYALTY})
        for task in self.s.tasks(actor(ROLE_ADMIN)):
            self.assertEqual(task.release_id, self.release.release_id)
            self.assertEqual(task.license_id, "L-1")

    def test_sale_recording_rejected_after_stop(self):
        self.s.withdraw_license(actor(ROLE_REGISTRAR), "L-1", at(20), reason="撤回")
        with self.assertRaises(StateError):
            self.s.record_sale(actor(ROLE_SUPPLY), self.release.release_id,
                               channel="电商", territory="CN", units=1, gross="10",
                               period="2026-04", at=at(21))

    def test_frozen_facts_are_not_rewritten(self):
        self.s.withdraw_license(actor(ROLE_REGISTRAR), "L-1", at(20), reason="撤回")
        release = self.s.releases(actor(ROLE_ADMIN))[0]
        self.assertEqual(release.license_ids, ("L-1",))  # 冻结快照不变
        kinds = [e.kind for e in self.s.ledger.history("L-1")]
        self.assertEqual(kinds, ["registered", "withdrawn"])  # 事件链完整
        actions = [e.action for e in self.s.audit_entries(actor(ROLE_ADMIN))]
        self.assertIn("license_withdrawn", actions)
        self.assertIn("release_stopped", actions)
        self.assertTrue(self.s.audit.verify())


class AmendImpactTest(unittest.TestCase):
    def test_narrowing_amendment_stops_release(self):
        s = boot()
        drive_gates(s)
        release = s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        narrowed = license_(revision=2, channels=frozenset({"馆内门店"}))  # 去掉电商
        s.amend_license(actor(ROLE_REGISTRAR), narrowed, at(20), reason="授权方收缩渠道")
        self.assertEqual(s.release_state(actor(ROLE_CURATOR), release.release_id),
                         RELEASE_STOPPED)
        self.assertTrue(any(t.kind == TASK_STOP_SALE
                            for t in s.tasks(actor(ROLE_ADMIN))))

    def test_widening_amendment_keeps_release_on_sale(self):
        s = boot()
        drive_gates(s)
        release = s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        s.amend_license(actor(ROLE_REGISTRAR), license_(revision=2, quantity_cap=5000),
                        at(20), reason="追加数量")
        self.assertEqual(s.release_state(actor(ROLE_CURATOR), release.release_id),
                         "on_sale")
        self.assertEqual(s.tasks(actor(ROLE_ADMIN)), ())


class ExpiryScanTest(unittest.TestCase):
    def test_reminder_then_expiry_then_tasks_all_audited_once(self):
        s = boot()
        drive_gates(s)
        release = s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        registrar = actor(ROLE_REGISTRAR)
        # 到期前 21 天：提醒一次，重复扫描不重复提醒
        self.assertEqual(s.scan_expiry(registrar, at(190), remind_within_days=30),
                         {"reminded": 1, "expired": 0})
        self.assertEqual(s.scan_expiry(registrar, at(191))["reminded"], 0)
        # 到期：授权到期事件 + 停售/库存/版税任务
        self.assertEqual(s.scan_expiry(registrar, at(211))["expired"], 1)
        self.assertEqual(s.release_state(actor(ROLE_CURATOR), release.release_id),
                         RELEASE_STOPPED)
        self.assertEqual(len(s.tasks(actor(ROLE_ADMIN))), 3)
        # 再次扫描幂等
        s.scan_expiry(registrar, at(212))
        self.assertEqual(len(s.tasks(actor(ROLE_ADMIN))), 3)
        actions = [e.action for e in s.audit_entries(actor(ROLE_ADMIN))]
        self.assertIn("license_expiring", actions)
        self.assertIn("license_expired", actions)

    def test_override_expiry_is_audited(self):
        s = boot()
        s.submit_design(actor(ROLE_CURATOR), "P-1", file_ref="d", file_hash="h", at=at(1))
        s.issue_override(actor(ROLE_ADMIN), "P-1", gates={GATE_LEGAL},
                         valid_until=at(5), responsibility="特批", at=at(2))
        s.scan_expiry(actor(ROLE_REGISTRAR), at(6))
        actions = [e.action for e in s.audit_entries(actor(ROLE_ADMIN))]
        self.assertIn("override_expired", actions)


if __name__ == "__main__":
    unittest.main()
