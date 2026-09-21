"""隔离接口：馆方员工与外部合作方分别通过不同门面参与流程。

内部接口面向馆方各角色（登记、策展、学术、法务、供应链、财务、管理），
具体动作仍由服务层按角色校验；合作方接口只暴露本机构参与提案的
查看、设计送审与合作方承诺，看不到其他机构的数据，也触不到登记、
冻结、放行、对账与审计等内部能力。
"""
from errors import PermissionDenied
from review import GATE_PARTNER
from service import MUSEUM_ORG, ROLE_PARTNER, RightsChainService


class InternalInterface:
    """馆方员工入口。"""

    def __init__(self, service: RightsChainService, actor):
        if actor.org != MUSEUM_ORG:
            raise PermissionDenied("内部接口仅面向馆方员工")
        self._service = service
        self._actor = actor

    # 登记
    def register_holder(self, holder, at):
        return self._service.register_holder(self._actor, holder, at)

    def register_work(self, work, at):
        return self._service.register_work(self._actor, work, at)

    def register_license(self, license, at, reason=""):
        return self._service.register_license(self._actor, license, at, reason)

    def amend_license(self, license, at, *, reason):
        return self._service.amend_license(self._actor, license, at, reason=reason)

    def withdraw_license(self, license_id, at, *, reason):
        return self._service.withdraw_license(self._actor, license_id, at, reason=reason)

    # 提案与审批
    def create_proposal(self, proposal, at):
        return self._service.create_proposal(self._actor, proposal, at)

    def evaluate(self, proposal_id):
        return self._service.evaluate_proposal(self._actor, proposal_id)

    def submit_design(self, proposal_id, *, file_ref, file_hash, note="", at):
        return self._service.submit_design(
            self._actor, proposal_id, file_ref=file_ref, file_hash=file_hash,
            note=note, at=at)

    def approve(self, proposal_id, gate, *, comment="", at):
        return self._service.approve(self._actor, proposal_id, gate,
                                     comment=comment, at=at)

    def issue_override(self, proposal_id, *, gates, valid_until, responsibility, at):
        return self._service.issue_override(
            self._actor, proposal_id, gates=gates, valid_until=valid_until,
            responsibility=responsibility, at=at)

    def freeze(self, proposal_id, at, *, override_id=None):
        return self._service.freeze(self._actor, proposal_id, at, override_id=override_id)

    # 影响处置与到期
    def scan_expiry(self, now, *, remind_within_days=30):
        return self._service.scan_expiry(self._actor, now,
                                         remind_within_days=remind_within_days)

    def complete_task(self, task_id, *, note, at):
        return self._service.complete_task(self._actor, task_id, note=note, at=at)

    def tasks(self, *, open_only=False):
        return self._service.tasks(self._actor, open_only=open_only)

    # 销售与版税
    def record_sale(self, release_id, *, channel, territory, units, gross, period, at):
        return self._service.record_sale(
            self._actor, release_id, channel=channel, territory=territory,
            units=units, gross=gross, period=period, at=at)

    def reconcile(self, license_id, *, period, at):
        return self._service.reconcile(self._actor, license_id, period=period, at=at)

    # 读取
    def proposal_status(self, proposal_id):
        return self._service.proposal_status(self._actor, proposal_id)

    def releases(self):
        return self._service.releases(self._actor)

    def release_state(self, release_id):
        return self._service.release_state(self._actor, release_id)

    def audit_trail(self):
        return self._service.audit_entries(self._actor)


class PartnerInterface:
    """外部合作方入口：仅能看到并操作本机构参与的提案。"""

    def __init__(self, service: RightsChainService, actor):
        if actor.role != ROLE_PARTNER:
            raise PermissionDenied("合作方接口仅面向外部合作方账号")
        self._service = service
        self._actor = actor

    def proposals(self):
        return self._service.proposals_for_partner(self._actor)

    def proposal_status(self, proposal_id):
        return self._service.proposal_status(self._actor, proposal_id)

    def rights_status(self, proposal_id):
        return self._service.evaluate_proposal(self._actor, proposal_id)

    def submit_design(self, proposal_id, *, file_ref, file_hash, note="", at):
        return self._service.submit_design(
            self._actor, proposal_id, file_ref=file_ref, file_hash=file_hash,
            note=note, at=at)

    def commit(self, proposal_id, *, comment="", at):
        return self._service.approve(self._actor, proposal_id, GATE_PARTNER,
                                     comment=comment, at=at)
