"""测试共用的构造器与固定时间。"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from catalog import RightsHolder, Work
from licensing import (CHANNEL_ONLINE, CHANNEL_STORE, USAGE_REPRODUCE, USAGE_SELL,
                       License, RoyaltyTerm)
from proposal import ProposalItem, ProductProposal
from review import GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER
from service import (ROLE_ACADEMIC, ROLE_CURATOR, ROLE_LEGAL, ROLE_PARTNER,
                     ROLE_REGISTRAR, Actor, RightsChainService)

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
LICENSE_END = datetime(2026, 7, 31, tzinfo=timezone.utc)  # = at(211)
SALE_FROM = datetime(2026, 3, 1, tzinfo=timezone.utc)
SALE_UNTIL = datetime(2026, 6, 30, tzinfo=timezone.utc)
PARTNER_ORG = "partner-co"


def at(days=0, hours=0):
    return T0 + timedelta(days=days, hours=hours)


def actor(role, org="museum", actor_id=None):
    return Actor(actor_id or f"{role}-1", role, org)


def holder(holder_id="H-1", name="权利人"):
    return RightsHolder(holder_id, name, "艺术家")


def work(work_id="W-1", holders=("H-1",), acquired=True):
    return Work(work_id, f"作品{work_id}", "作者", frozenset(holders), acquired)


def license_(license_id="L-1", work_id="W-1", holder_id="H-1", **kw):
    defaults = dict(
        source_ref=f"合同-{license_id}", source_hash=f"hash-{license_id}",
        usages=frozenset({USAGE_REPRODUCE, USAGE_SELL}),
        territories=frozenset({"CN"}),
        channels=frozenset({CHANNEL_STORE, CHANNEL_ONLINE}),
        quantity_cap=1000,
        royalty=RoyaltyTerm("per_unit", Decimal("5"), "CNY"),
        valid_from=T0, valid_until=LICENSE_END, revision=1,
    )
    defaults.update(kw)
    return License(license_id, work_id, holder_id, **defaults)


def item(work_id="W-1", **kw):
    defaults = dict(
        usages=frozenset({USAGE_REPRODUCE, USAGE_SELL}),
        territories=frozenset({"CN"}),
        channels=frozenset({CHANNEL_ONLINE}),
        planned_quantity=500,
        sale_from=SALE_FROM, sale_until=SALE_UNTIL,
    )
    defaults.update(kw)
    return ProposalItem(work_id, **defaults)


def proposal(proposal_id="P-1", items=None, partner_org=PARTNER_ORG):
    return ProductProposal(
        proposal_id, "EX-1", "特展文创", partner_org,
        tuple(items if items is not None else [item()]), "curator-1", T0)


def boot(with_license=True, items=None, proposal_id="P-1"):
    """搭建基础图：H-1 / W-1（已入藏）/（可选）L-1 / 提案。返回服务实例。"""
    s = RightsChainService()
    registrar = actor(ROLE_REGISTRAR)
    s.register_holder(registrar, holder("H-1"), T0)
    s.register_work(registrar, work("W-1", ("H-1",)), T0)
    if with_license:
        s.register_license(registrar, license_("L-1", "W-1", "H-1"), T0)
    s.create_proposal(actor(ROLE_CURATOR), proposal(proposal_id, items), T0)
    return s


def drive_gates(s, proposal_id="P-1", file_ref="d/v1.ai", file_hash="h1", day=1):
    """送审设计并让学术、法务、合作方三方在当前版本上汇合。"""
    s.submit_design(actor(ROLE_CURATOR), proposal_id,
                    file_ref=file_ref, file_hash=file_hash, at=at(day))
    s.approve(actor(ROLE_ACADEMIC), proposal_id, GATE_ACADEMIC,
              comment="学术通过", at=at(day, 1))
    s.approve(actor(ROLE_LEGAL), proposal_id, GATE_LEGAL,
              comment="法务通过", at=at(day, 2))
    s.approve(actor(ROLE_PARTNER, PARTNER_ORG), proposal_id, GATE_PARTNER,
              comment="承诺按授权生产", at=at(day, 3))
