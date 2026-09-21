"""复核案例：多权利人、部分授权、展期提前结束、审批中替换设计，
以及核心不变量——未经许可的方案必须始终停在生产之前。
"""
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from errors import ApprovalIncomplete, RightsNotSatisfied, StateError
from impact import TASK_INVENTORY, TASK_ROYALTY, TASK_STOP_SALE
from licensing import CHANNEL_DISTRIB, USAGE_ADAPT
from review import GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER
from service import (ROLE_ACADEMIC, ROLE_ADMIN, ROLE_CURATOR, ROLE_FINANCE,
                     ROLE_LEGAL, ROLE_PARTNER, ROLE_REGISTRAR, ROLE_SUPPLY,
                     RightsChainService)
from support import (PARTNER_ORG, T0, actor, at, boot, drive_gates, holder,
                     item, license_, proposal, work)


class MultiHolderCaseTest(unittest.TestCase):
    """多权利人：每个权利主体的授权都齐备，权利链才完整。"""

    def test_every_holder_must_grant(self):
        s = RightsChainService()
        registrar = actor(ROLE_REGISTRAR)
        s.register_holder(registrar, holder("H-2", "艺术家"), T0)
        s.register_holder(registrar, holder("H-3", "家属"), T0)
        s.register_work(registrar, work("W-2", ("H-2", "H-3")), T0)
        s.register_license(registrar, license_("L-2", "W-2", "H-2"), T0)
        s.create_proposal(actor(ROLE_CURATOR), proposal("P-1", [item("W-2")]), T0)

        checks = s.evaluate_proposal(actor(ROLE_CURATOR), "P-1")
        self.assertFalse(checks[0].ok)
        self.assertTrue(any("H-3" in f for f in checks[0].failures))

        s.register_license(registrar, license_("L-3", "W-2", "H-3"), T0)
        checks = s.evaluate_proposal(actor(ROLE_CURATOR), "P-1")
        self.assertTrue(checks[0].ok)
        self.assertEqual(set(checks[0].license_ids), {"L-2", "L-3"})


class PartialAuthorizationCaseTest(unittest.TestCase):
    """部分授权：用途、地域、渠道、数量、有效期任一不满足都要明确拦截。"""

    def setUp(self):
        self.s = boot()  # L-1: 复制+商业销售 / CN / 门店+电商 / 上限 1000 / 至 2026-07-31
        self.curator = actor(ROLE_CURATOR)

    def check_fails(self, bad_item, keyword):
        self.s.create_proposal(self.curator, proposal("P-x", [bad_item]), T0)
        checks = self.s.evaluate_proposal(self.curator, "P-x")
        self.assertFalse(checks[0].ok)
        self.assertTrue(any(keyword in f for f in checks[0].failures),
                        (keyword, checks[0].failures))

    def test_uncovered_usage(self):
        self.check_fails(item(usages=frozenset({USAGE_ADAPT})), "用途")

    def test_uncovered_territory(self):
        self.check_fails(item(territories=frozenset({"JP"})), "地域")

    def test_uncovered_channel(self):
        self.check_fails(item(channels=frozenset({CHANNEL_DISTRIB})), "渠道")

    def test_quantity_over_cap(self):
        self.check_fails(item(planned_quantity=1500), "数量")

    def test_sale_window_beyond_license(self):
        late = item(sale_until=datetime(2026, 12, 31, tzinfo=timezone.utc))
        self.check_fails(late, "有效期")

    def test_acquired_work_without_license_is_not_authorized(self):
        s = boot(with_license=False)  # 已入藏，但没有任何授权
        checks = s.evaluate_proposal(actor(ROLE_CURATOR), "P-1")
        self.assertFalse(checks[0].ok)
        self.assertTrue(any("入藏不等于授权" in f for f in checks[0].failures))


class UnlicensedNeverReachesProductionTest(unittest.TestCase):
    """核心不变量：审批再齐、放行再急，权利不满足就永远停在生产之前。"""

    def test_full_approval_and_override_cannot_waive_rights(self):
        s = boot(with_license=False)
        drive_gates(s)  # 学术、法务、合作方全部汇合
        override = s.issue_override(
            actor(ROLE_ADMIN), "P-1",
            gates={GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER},
            valid_until=at(30), responsibility="馆长特批", at=at(2))
        with self.assertRaises(RightsNotSatisfied):
            s.freeze(actor(ROLE_CURATOR), "P-1", at(3),
                     override_id=override.override_id)
        self.assertEqual(s.releases(actor(ROLE_ADMIN)), ())
        # 拦截本身也留有审计痕迹
        rejected = s.audit.of(action="freeze_rejected", entity="proposal:P-1")
        self.assertTrue(rejected)


class ExhibitionEndsEarlyCaseTest(unittest.TestCase):
    """展期提前结束：授权终止触发停售、库存处置与待结版税，事实链完整。"""

    def test_full_disposal_flow(self):
        s = boot()
        drive_gates(s)
        release = s.freeze(actor(ROLE_CURATOR), "P-1", at(10))
        s.record_sale(actor(ROLE_SUPPLY), release.release_id, channel="电商",
                      territory="CN", units=120, gross="24000",
                      period="2026-04", at=at(100))

        # 展期提前结束，授权方终止授权
        s.withdraw_license(actor(ROLE_REGISTRAR), "L-1", at(120),
                           reason="展期提前结束，授权终止")

        open_tasks = s.tasks(actor(ROLE_ADMIN), open_only=True)
        self.assertEqual({t.kind for t in open_tasks},
                         {TASK_STOP_SALE, TASK_INVENTORY, TASK_ROYALTY})
        # 门店与电商立即停止销售
        with self.assertRaises(StateError):
            s.record_sale(actor(ROLE_SUPPLY), release.release_id, channel="电商",
                          territory="CN", units=1, gross="200",
                          period="2026-05", at=at(121))

        # 版税对账并结清
        stmt = s.reconcile(actor(ROLE_FINANCE), "L-1", period="2026-04", at=at(122))
        self.assertEqual(stmt.due, Decimal("600"))  # 120 件 × 5 CNY
        by_kind = {t.kind: t for t in open_tasks}
        s.complete_task(actor(ROLE_FINANCE), by_kind[TASK_ROYALTY].task_id,
                        note=f"已结版税 {stmt.due} {stmt.currency}", at=at(123))
        s.complete_task(actor(ROLE_SUPPLY), by_kind[TASK_STOP_SALE].task_id,
                        note="门店与电商页面已下架", at=at(123))
        s.complete_task(actor(ROLE_SUPPLY), by_kind[TASK_INVENTORY].task_id,
                        note="剩余库存转为非卖品封存", at=at(124))
        self.assertEqual(s.tasks(actor(ROLE_ADMIN), open_only=True), ())

        # 事实链完整：登记→冻结→销售→撤回→处置→结算，全部可核验
        self.assertTrue(s.audit.verify())
        kinds = [e.kind for e in s.ledger.history("L-1")]
        self.assertEqual(kinds, ["registered", "withdrawn"])
        frozen = s.releases(actor(ROLE_ADMIN))[0]
        self.assertEqual(frozen.license_ids, ("L-1",))


class DesignReplacedMidApprovalCaseTest(unittest.TestCase):
    """审批中替换设计：旧版本上的审批不计入新版本，须重新汇合。"""

    def test_new_version_resets_convergence(self):
        s = boot()
        curator = actor(ROLE_CURATOR)
        s.submit_design(curator, "P-1", file_ref="d/v1", file_hash="h1", at=at(1))
        s.approve(actor(ROLE_ACADEMIC), "P-1", GATE_ACADEMIC, at=at(2))
        s.approve(actor(ROLE_LEGAL), "P-1", GATE_LEGAL, at=at(2))

        # 合作方送审新设计：V1 上的学术/法务确认不再计入
        s.submit_design(actor(ROLE_PARTNER, PARTNER_ORG), "P-1",
                        file_ref="d/v2", file_hash="h2", note="替换图案", at=at(3))
        with self.assertRaises(ApprovalIncomplete):
            s.freeze(curator, "P-1", at(4))

        # 三方在新版本上重新汇合后才可冻结
        s.approve(actor(ROLE_ACADEMIC), "P-1", GATE_ACADEMIC, at=at(5))
        s.approve(actor(ROLE_LEGAL), "P-1", GATE_LEGAL, at=at(5))
        s.approve(actor(ROLE_PARTNER, PARTNER_ORG), "P-1", GATE_PARTNER, at=at(5))
        release = s.freeze(curator, "P-1", at(6))
        self.assertEqual(release.version_seq, 2)
        self.assertEqual(release.design.file_hash, "h2")


if __name__ == "__main__":
    unittest.main()
