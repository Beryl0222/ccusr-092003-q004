import unittest
from dataclasses import FrozenInstanceError

from errors import (ApprovalIncomplete, PermissionDenied, StateError,
                    ValidationError)
from review import GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER
from service import ROLE_ACADEMIC, ROLE_ADMIN, ROLE_CURATOR, ROLE_LEGAL
from support import actor, at, boot, drive_gates, item, proposal


class DesignVersionTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()

    def test_each_submission_creates_new_version(self):
        curator = actor(ROLE_CURATOR)
        v1 = self.s.submit_design(curator, "P-1", file_ref="d/v1.ai", file_hash="h1", at=at(1))
        v2 = self.s.submit_design(curator, "P-1", file_ref="d/v1.ai", file_hash="h1", at=at(2))
        self.assertEqual((v1.seq, v2.seq), (1, 2))

    def test_approve_requires_design_and_rejects_duplicate(self):
        with self.assertRaises(StateError):
            self.s.approve(actor(ROLE_ACADEMIC), "P-1", GATE_ACADEMIC, at=at(1))
        self.s.submit_design(actor(ROLE_CURATOR), "P-1",
                             file_ref="d/v1", file_hash="h1", at=at(1))
        self.s.approve(actor(ROLE_ACADEMIC), "P-1", GATE_ACADEMIC, at=at(2))
        with self.assertRaises(StateError):
            self.s.approve(actor(ROLE_ACADEMIC), "P-1", GATE_ACADEMIC, at=at(3))


class FreezeTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()

    def test_freeze_after_convergence_snapshots_everything(self):
        drive_gates(self.s)
        release = self.s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        self.assertEqual(release.version_seq, 1)
        self.assertEqual(release.license_ids, ("L-1",))
        self.assertEqual(release.license_revisions, (("L-1", 1),))
        self.assertEqual(len(release.approvals), 3)
        self.assertIsNone(release.override_id)

    def test_freeze_blocked_when_gates_missing(self):
        self.s.submit_design(actor(ROLE_CURATOR), "P-1",
                             file_ref="d/v1", file_hash="h1", at=at(1))
        with self.assertRaises(ApprovalIncomplete):
            self.s.freeze(actor(ROLE_CURATOR), "P-1", at(2))

    def test_freeze_blocked_without_design(self):
        with self.assertRaises(StateError):
            self.s.freeze(actor(ROLE_CURATOR), "P-1", at(1))

    def test_release_is_immutable_snapshot(self):
        drive_gates(self.s)
        release = self.s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        with self.assertRaises(FrozenInstanceError):
            release.frozen_by = "someone-else"

    def test_quantity_cap_enforced_across_freezes(self):
        drive_gates(self.s)
        self.s.freeze(actor(ROLE_CURATOR), "P-1", at(10))  # 占用 500 / 1000
        curator = actor(ROLE_CURATOR)
        self.s.create_proposal(curator, proposal("P-2", [item(planned_quantity=600)]), at(11))
        checks = self.s.evaluate_proposal(curator, "P-2")
        self.assertFalse(checks[0].ok)
        self.assertTrue(any("数量" in f for f in checks[0].failures))
        self.s.create_proposal(curator, proposal("P-3", [item(planned_quantity=400)]), at(11))
        self.assertTrue(self.s.evaluate_proposal(curator, "P-3")[0].ok)

    def test_quantity_accumulates_within_one_proposal(self):
        s = boot(items=[item(planned_quantity=600), item(planned_quantity=600)],
                 proposal_id="P-9")
        checks = s.evaluate_proposal(actor(ROLE_CURATOR), "P-9")
        self.assertTrue(checks[0].ok)
        self.assertFalse(checks[1].ok)
        self.assertTrue(any("数量" in f for f in checks[1].failures))


class OverrideTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()
        self.s.submit_design(actor(ROLE_CURATOR), "P-1",
                             file_ref="d/v1", file_hash="h1", at=at(1))

    def test_override_covers_missing_gates_within_timebox(self):
        self.s.approve(actor(ROLE_ACADEMIC), "P-1", GATE_ACADEMIC, at=at(2))
        override = self.s.issue_override(
            actor(ROLE_ADMIN), "P-1", gates={GATE_LEGAL, GATE_PARTNER},
            valid_until=at(5), responsibility="馆长批示：展前特批，责任由馆办承担", at=at(2))
        release = self.s.freeze(actor(ROLE_CURATOR), "P-1", at(3),
                                override_id=override.override_id)
        self.assertEqual(release.override_id, override.override_id)

    def test_expired_override_does_not_count(self):
        override = self.s.issue_override(
            actor(ROLE_ADMIN), "P-1", gates={GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER},
            valid_until=at(5), responsibility="特批", at=at(2))
        with self.assertRaises(ApprovalIncomplete):
            self.s.freeze(actor(ROLE_CURATOR), "P-1", at(6),
                          override_id=override.override_id)

    def test_override_requires_responsibility_and_future_expiry(self):
        with self.assertRaises(ValidationError):
            self.s.issue_override(actor(ROLE_ADMIN), "P-1", gates={GATE_LEGAL},
                                  valid_until=at(5), responsibility=" ", at=at(2))
        with self.assertRaises(ValidationError):
            self.s.issue_override(actor(ROLE_ADMIN), "P-1", gates={GATE_LEGAL},
                                  valid_until=at(1), responsibility="x", at=at(2))

    def test_override_only_by_admin(self):
        with self.assertRaises(PermissionDenied):
            self.s.issue_override(actor(ROLE_CURATOR), "P-1", gates={GATE_LEGAL},
                                  valid_until=at(5), responsibility="x", at=at(2))


if __name__ == "__main__":
    unittest.main()
