import unittest

from errors import PermissionDenied
from interfaces import InternalInterface, PartnerInterface
from review import GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER
from service import (ROLE_ACADEMIC, ROLE_ADMIN, ROLE_CURATOR, ROLE_LEGAL,
                     ROLE_PARTNER)
from support import PARTNER_ORG, T0, actor, at, boot, proposal


class InterfaceConstructionTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()

    def test_internal_interface_requires_museum_org(self):
        with self.assertRaises(PermissionDenied):
            InternalInterface(self.s, actor(ROLE_CURATOR, org="outsider"))

    def test_partner_interface_requires_partner_role(self):
        with self.assertRaises(PermissionDenied):
            PartnerInterface(self.s, actor(ROLE_CURATOR))


class PartnerIsolationTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()
        self.s.create_proposal(actor(ROLE_CURATOR),
                               proposal("P-2", partner_org="other-co"), T0)
        self.partner = PartnerInterface(self.s, actor(ROLE_PARTNER, PARTNER_ORG))

    def test_partner_sees_only_own_proposals(self):
        self.assertEqual([p.proposal_id for p in self.partner.proposals()], ["P-1"])
        with self.assertRaises(PermissionDenied):
            self.partner.proposal_status("P-2")
        with self.assertRaises(PermissionDenied):
            self.partner.rights_status("P-2")

    def test_partner_submit_design_and_commit(self):
        version = self.partner.submit_design("P-1", file_ref="d/v1",
                                             file_hash="h1", at=at(1))
        self.assertEqual(version.seq, 1)
        self.partner.commit("P-1", comment="承诺按授权生产", at=at(2))
        status = self.partner.proposal_status("P-1")
        self.assertNotIn(GATE_PARTNER, status["missing_gates"])
        self.assertIn(GATE_ACADEMIC, status["missing_gates"])

    def test_partner_cannot_reach_internal_capabilities(self):
        for capability in ("freeze", "issue_override", "register_license",
                           "withdraw_license", "reconcile", "audit_trail",
                           "scan_expiry", "record_sale"):
            self.assertFalse(hasattr(self.partner, capability), capability)
        # 即使绕过门面直接调服务层，角色校验依然拦截
        with self.assertRaises(PermissionDenied):
            self.s.freeze(actor(ROLE_PARTNER, PARTNER_ORG), "P-1", at(1))
        with self.assertRaises(PermissionDenied):
            self.s.audit_entries(actor(ROLE_PARTNER, PARTNER_ORG))

    def test_partner_commit_on_other_orgs_proposal_rejected(self):
        self.s.submit_design(actor(ROLE_CURATOR), "P-2",
                             file_ref="d", file_hash="h", at=at(1))
        with self.assertRaises(PermissionDenied):
            self.s.approve(actor(ROLE_PARTNER, PARTNER_ORG), "P-2",
                           GATE_PARTNER, at=at(2))


class InternalRoleTest(unittest.TestCase):
    def setUp(self):
        self.s = boot()
        self.s.submit_design(actor(ROLE_CURATOR), "P-1",
                             file_ref="d/v1", file_hash="h1", at=at(1))

    def test_each_gate_requires_its_own_role(self):
        with self.assertRaises(PermissionDenied):
            self.s.approve(actor(ROLE_ACADEMIC), "P-1", GATE_LEGAL, at=at(2))
        with self.assertRaises(PermissionDenied):
            self.s.approve(actor(ROLE_LEGAL), "P-1", GATE_ACADEMIC, at=at(2))
        # 管理角色也不能代替学术/法务确认
        with self.assertRaises(PermissionDenied):
            self.s.approve(actor(ROLE_ADMIN), "P-1", GATE_ACADEMIC, at=at(2))

    def test_internal_interface_end_to_end(self):
        curator = InternalInterface(self.s, actor(ROLE_CURATOR))
        academic = InternalInterface(self.s, actor(ROLE_ACADEMIC))
        legal = InternalInterface(self.s, actor(ROLE_LEGAL))
        partner = PartnerInterface(self.s, actor(ROLE_PARTNER, PARTNER_ORG))
        academic.approve("P-1", GATE_ACADEMIC, comment="通过", at=at(2))
        legal.approve("P-1", GATE_LEGAL, comment="通过", at=at(2))
        partner.commit("P-1", comment="承诺", at=at(2))
        release = curator.freeze("P-1", at(3))
        self.assertEqual(release.version_seq, 1)
        self.assertTrue(curator.audit_trail())


if __name__ == "__main__":
    unittest.main()
