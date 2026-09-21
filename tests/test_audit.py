import unittest
from dataclasses import replace

from service import ROLE_ADMIN, ROLE_CURATOR, ROLE_FINANCE, ROLE_REGISTRAR, ROLE_SUPPLY
from support import actor, at, boot, drive_gates


class AuditChainTest(unittest.TestCase):
    def test_full_flow_leaves_verifiable_trail(self):
        s = boot()
        drive_gates(s)
        release = s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        s.record_sale(actor(ROLE_SUPPLY), release.release_id, channel="电商",
                      territory="CN", units=10, gross="2000",
                      period="2026-04", at=at(100))
        s.reconcile(actor(ROLE_FINANCE), "L-1", period="2026-04", at=at(110))
        s.withdraw_license(actor(ROLE_REGISTRAR), "L-1", at(120), reason="展期结束")
        self.assertTrue(s.audit.verify())
        actions = [entry.action for entry in s.audit_entries(actor(ROLE_ADMIN))]
        for expected in ("holder_registered", "work_registered", "license_registered",
                         "proposal_created", "design_submitted", "gate_approved",
                         "release_frozen", "sale_recorded", "royalty_reconciled",
                         "license_withdrawn", "release_stopped", "task_created"):
            self.assertIn(expected, actions)

    def test_tampering_breaks_chain(self):
        s = boot()
        entries = list(s.audit.entries)
        entries[0] = replace(entries[0], detail="事后篡改")
        s.audit._entries = entries  # 模拟存储层被改动
        self.assertFalse(s.audit.verify())


if __name__ == "__main__":
    unittest.main()
