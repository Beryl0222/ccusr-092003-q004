"""文创权利链与开发协作服务的编排层。

硬性不变量：
1. 权利条件未逐项满足的提案永远不能冻结投产，紧急放行也不能豁免；
2. 已发生事实（授权事件、冻结版本、审计记录）只追加、不改写；
   授权变更、撤回、到期触发的是停售、库存处置、待结版税任务；
3. 内部员工与外部合作方分接口参与，按角色与机构双重校验。

所有写操作都以显式传入的时间入账，便于审计与复核。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal

from audit import AuditLog
from catalog import Catalog, RightsHolder, Work
from errors import (ApprovalIncomplete, NotFound, PermissionDenied,
                    RightsNotSatisfied, StateError, ValidationError)
from evaluation import evaluate_item
from impact import (TASK_DONE, TASK_INVENTORY, TASK_OPEN, TASK_ROYALTY,
                    TASK_STOP_SALE, ImpactTask)
from licensing import ROYALTY_PER_UNIT, License, LicenseLedger
from override import EmergencyOverride
from proposal import ProductProposal, RightsCheck
from review import (GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER, ApprovalBoard,
                    ProductionRelease)

MUSEUM_ORG = "museum"

ROLE_REGISTRAR = "registrar"   # 权利登记
ROLE_CURATOR = "curator"       # 策展
ROLE_ACADEMIC = "academic"     # 学术审核
ROLE_LEGAL = "legal"           # 法务确认
ROLE_PARTNER = "partner"       # 外部合作方
ROLE_SUPPLY = "supply"         # 供应链
ROLE_FINANCE = "finance"       # 财务/版税结算
ROLE_ADMIN = "admin"           # 馆方管理（紧急放行责任人）

_GATE_ROLES = {
    GATE_ACADEMIC: ROLE_ACADEMIC,
    GATE_LEGAL: ROLE_LEGAL,
    GATE_PARTNER: ROLE_PARTNER,
}

_TASK_ROLES = {
    TASK_STOP_SALE: {ROLE_SUPPLY, ROLE_CURATOR, ROLE_ADMIN},
    TASK_INVENTORY: {ROLE_SUPPLY, ROLE_CURATOR, ROLE_ADMIN},
    TASK_ROYALTY: {ROLE_FINANCE, ROLE_ADMIN},
}

RELEASE_ON_SALE = "on_sale"
RELEASE_STOPPED = "stopped"

_SYSTEM_ACTOR = "system"  # 权利影响等自动后果的入账主体


@dataclass(frozen=True)
class Actor:
    actor_id: str
    role: str
    org: str = MUSEUM_ORG


@dataclass(frozen=True)
class SaleRecord:
    release_id: str
    channel: str
    territory: str
    units: int
    gross: Decimal
    period: str
    at: datetime
    actor_id: str


@dataclass(frozen=True)
class RoyaltyStatement:
    license_id: str
    period: str
    units: int
    gross: Decimal
    due: Decimal
    currency: str


class RightsChainService:
    def __init__(self) -> None:
        self.catalog = Catalog()
        self.ledger = LicenseLedger(self.catalog)
        self.audit = AuditLog()
        self._proposals: dict[str, ProductProposal] = {}
        self._boards: dict[str, ApprovalBoard] = {}
        self._releases: dict[str, ProductionRelease] = {}
        self._release_state: dict[str, str] = {}
        self._allocations: dict[str, int] = {}  # license_id -> 已冻结投产数量
        self._overrides: dict[str, EmergencyOverride] = {}
        self._tasks: dict[str, ImpactTask] = {}
        self._sales: list[SaleRecord] = []
        self._release_seq = 0
        self._task_seq = 0
        self._override_seq = 0
        self._expired_processed: set[str] = set()
        self._reminded: set[str] = set()
        self._overrides_expired: set[str] = set()

    # ------------------------------------------------------------------
    # 权限与查找
    # ------------------------------------------------------------------

    def _require(self, actor: Actor, roles: set[str], *, museum_only: bool = True) -> None:
        if actor.role not in roles:
            raise PermissionDenied(f"角色 {actor.role} 无权执行该操作")
        if museum_only and actor.org != MUSEUM_ORG:
            raise PermissionDenied("外部合作方不得执行馆方内部操作")

    def _proposal(self, proposal_id: str) -> ProductProposal:
        try:
            return self._proposals[proposal_id]
        except KeyError:
            raise NotFound(f"提案不存在: {proposal_id}") from None

    def _check_proposal_visible(self, actor: Actor, proposal: ProductProposal) -> None:
        if actor.org == MUSEUM_ORG:
            return
        if not (actor.role == ROLE_PARTNER and actor.org == proposal.partner_org):
            raise PermissionDenied("合作方仅可查看本机构参与的提案")

    # ------------------------------------------------------------------
    # 登记：作品、权利主体、授权
    # ------------------------------------------------------------------

    def register_holder(self, actor: Actor, holder: RightsHolder, at: datetime) -> None:
        self._require(actor, {ROLE_REGISTRAR, ROLE_ADMIN})
        self.catalog.register_holder(holder)
        self.audit.append(at=at, actor_id=actor.actor_id, action="holder_registered",
                          entity=f"holder:{holder.holder_id}", detail=holder.name)

    def register_work(self, actor: Actor, work: Work, at: datetime) -> None:
        self._require(actor, {ROLE_REGISTRAR, ROLE_ADMIN})
        self.catalog.register_work(work)
        self.audit.append(at=at, actor_id=actor.actor_id, action="work_registered",
                          entity=f"work:{work.work_id}",
                          detail=f"权利主体 {sorted(work.holder_ids)}，入藏={work.acquired}")

    def register_license(self, actor: Actor, license: License, at: datetime,
                         reason: str = "") -> None:
        self._require(actor, {ROLE_REGISTRAR, ROLE_ADMIN})
        self.ledger.register(license, actor_id=actor.actor_id, at=at, reason=reason)
        self.audit.append(at=at, actor_id=actor.actor_id, action="license_registered",
                          entity=f"license:{license.license_id}",
                          detail=(f"来源 {license.source_ref}#{license.source_hash}，"
                                  f"第 {license.revision} 版，有效期 "
                                  f"{license.valid_from:%Y-%m-%d}~{license.valid_until:%Y-%m-%d}"))

    def amend_license(self, actor: Actor, license: License, at: datetime, *,
                      reason: str) -> None:
        self._require(actor, {ROLE_REGISTRAR, ROLE_ADMIN})
        self.ledger.amend(license, actor_id=actor.actor_id, at=at, reason=reason)
        self.audit.append(at=at, actor_id=actor.actor_id, action="license_amended",
                          entity=f"license:{license.license_id}",
                          detail=f"第 {license.revision} 版: {reason}")
        self._impacts_after_change(license.license_id, at, f"授权变更（{reason}）")

    def withdraw_license(self, actor: Actor, license_id: str, at: datetime, *,
                         reason: str) -> None:
        self._require(actor, {ROLE_REGISTRAR, ROLE_ADMIN})
        self.ledger.withdraw(license_id, actor_id=actor.actor_id, at=at, reason=reason)
        self.audit.append(at=at, actor_id=actor.actor_id, action="license_withdrawn",
                          entity=f"license:{license_id}", detail=reason)
        self._impacts_after_change(license_id, at, f"授权撤回（{reason}）")

    # ------------------------------------------------------------------
    # 提案与逐项权利核验
    # ------------------------------------------------------------------

    def create_proposal(self, actor: Actor, proposal: ProductProposal,
                        at: datetime) -> None:
        self._require(actor, {ROLE_CURATOR, ROLE_ADMIN})
        if proposal.proposal_id in self._proposals:
            raise ValidationError(f"提案已存在: {proposal.proposal_id}")
        if not proposal.partner_org:
            raise ValidationError("提案必须指定合作方机构")
        if not proposal.items:
            raise ValidationError("提案至少引用一件作品")
        for item in proposal.items:
            self.catalog.work(item.work_id)  # 作品必须先登记
            if item.planned_quantity <= 0:
                raise ValidationError("计划数量必须为正数")
            if not item.usages or not item.territories or not item.channels:
                raise ValidationError("提案条目必须声明用途、地域与渠道")
            if item.sale_until <= item.sale_from:
                raise ValidationError("销售窗口无效")
        self._proposals[proposal.proposal_id] = proposal
        self._boards[proposal.proposal_id] = ApprovalBoard(proposal.proposal_id)
        self.audit.append(at=at, actor_id=actor.actor_id, action="proposal_created",
                          entity=f"proposal:{proposal.proposal_id}",
                          detail=f"展览 {proposal.exhibition_id}，"
                                 f"作品 {[item.work_id for item in proposal.items]}")

    def _evaluate(self, proposal: ProductProposal) -> tuple[RightsCheck, ...]:
        checks: list[RightsCheck] = []
        pending = dict(self._allocations)  # 提案内部多条目共用同一授权时累计占用
        for item in proposal.items:
            work = self.catalog.work(item.work_id)
            check = evaluate_item(item, work, self.ledger, pending)
            checks.append(check)
            if check.ok:
                for license_id in check.license_ids:
                    pending[license_id] = pending.get(license_id, 0) + item.planned_quantity
        return tuple(checks)

    def evaluate_proposal(self, actor: Actor, proposal_id: str) -> tuple[RightsCheck, ...]:
        proposal = self._proposal(proposal_id)
        self._check_proposal_visible(actor, proposal)
        return self._evaluate(proposal)

    # ------------------------------------------------------------------
    # 设计送审与三方审批汇合
    # ------------------------------------------------------------------

    def submit_design(self, actor: Actor, proposal_id: str, *, file_ref: str,
                      file_hash: str, note: str = "", at: datetime):
        proposal = self._proposal(proposal_id)
        if actor.role in (ROLE_CURATOR, ROLE_ADMIN):
            self._require(actor, {ROLE_CURATOR, ROLE_ADMIN})
        elif actor.role == ROLE_PARTNER:
            if actor.org != proposal.partner_org:
                raise PermissionDenied("仅本提案的指定合作方可送审设计")
        else:
            raise PermissionDenied(f"角色 {actor.role} 无权送审设计")
        version = self._boards[proposal_id].submit(
            file_ref=file_ref, file_hash=file_hash,
            submitted_by=actor.actor_id, at=at, note=note)
        self.audit.append(at=at, actor_id=actor.actor_id, action="design_submitted",
                          entity=f"proposal:{proposal_id}",
                          detail=f"版本 V{version.seq}，文件 {file_ref}#{file_hash}")
        return version

    def approve(self, actor: Actor, proposal_id: str, gate: str, *,
                comment: str = "", at: datetime):
        proposal = self._proposal(proposal_id)
        if gate not in _GATE_ROLES:
            raise ValidationError(f"未知审批环节: {gate}")
        expected = _GATE_ROLES[gate]
        if actor.role != expected:
            raise PermissionDenied(f"{gate} 须由角色 {expected} 确认")
        if expected == ROLE_PARTNER:
            if actor.org != proposal.partner_org:
                raise PermissionDenied("仅指定合作方可作出合作方承诺")
        elif actor.org != MUSEUM_ORG:
            raise PermissionDenied("外部合作方不得执行馆方内部审批")
        approval = self._boards[proposal_id].approve(
            gate=gate, actor_id=actor.actor_id, at=at, comment=comment)
        self.audit.append(at=at, actor_id=actor.actor_id, action="gate_approved",
                          entity=f"proposal:{proposal_id}",
                          detail=f"{gate} @ V{approval.version_seq}: {comment}")
        return approval

    def issue_override(self, actor: Actor, proposal_id: str, *,
                       gates, valid_until: datetime, responsibility: str,
                       at: datetime) -> EmergencyOverride:
        self._require(actor, {ROLE_ADMIN})
        self._proposal(proposal_id)
        if not responsibility.strip():
            raise ValidationError("紧急放行必须填写责任说明")
        if valid_until <= at:
            raise ValidationError("放行时效必须晚于当前时间")
        unknown = set(gates) - set(_GATE_ROLES)
        if unknown:
            raise ValidationError(f"紧急放行不能覆盖未知环节: {sorted(unknown)}")
        self._override_seq += 1
        override = EmergencyOverride(
            override_id=f"O-{self._override_seq}", proposal_id=proposal_id,
            gates=frozenset(gates), issued_by=actor.actor_id, issued_at=at,
            valid_until=valid_until, responsibility=responsibility)
        self._overrides[override.override_id] = override
        self.audit.append(at=at, actor_id=actor.actor_id, action="override_issued",
                          entity=f"override:{override.override_id}",
                          detail=(f"放行环节 {sorted(override.gates)}，"
                                  f"时效至 {valid_until:%Y-%m-%d %H:%M}，"
                                  f"责任说明: {responsibility}"))
        return override

    # ------------------------------------------------------------------
    # 冻结投产版本（权利条件是不可豁免的硬门槛）
    # ------------------------------------------------------------------

    def freeze(self, actor: Actor, proposal_id: str, at: datetime, *,
               override_id: str | None = None) -> ProductionRelease:
        self._require(actor, {ROLE_CURATOR, ROLE_ADMIN})
        proposal = self._proposal(proposal_id)
        board = self._boards[proposal_id]
        version = board.current
        if version is None:
            self.audit.append(at=at, actor_id=actor.actor_id, action="freeze_rejected",
                              entity=f"proposal:{proposal_id}", detail="尚未提交设计文件")
            raise StateError("尚未提交设计文件，无法冻结投产版本")
        checks = self._evaluate(proposal)
        if not all(check.ok for check in checks):
            failures = [f for check in checks for f in check.failures]
            self.audit.append(at=at, actor_id=actor.actor_id, action="freeze_rejected",
                              entity=f"proposal:{proposal_id}",
                              detail="权利条件未满足: " + "; ".join(failures))
            raise RightsNotSatisfied(checks)
        missing = board.missing_gates()
        override = None
        if missing:
            override = self._overrides.get(override_id) if override_id else None
            if (override is None or override.proposal_id != proposal_id
                    or not override.active(at) or not set(missing) <= set(override.gates)):
                self.audit.append(at=at, actor_id=actor.actor_id, action="freeze_rejected",
                                  entity=f"proposal:{proposal_id}",
                                  detail=f"审批未汇合，缺少: {'、'.join(sorted(missing))}")
                raise ApprovalIncomplete(f"审批未汇合，缺少: {sorted(missing)}")
            self.audit.append(at=at, actor_id=actor.actor_id, action="override_applied",
                              entity=f"override:{override.override_id}",
                              detail=(f"放行环节: {'、'.join(sorted(missing))}；"
                                      f"责任说明: {override.responsibility}"))
        for check in checks:
            for license_id in check.license_ids:
                self._allocations[license_id] = (
                    self._allocations.get(license_id, 0) + check.item.planned_quantity)
        self._release_seq += 1
        license_ids = tuple(dict.fromkeys(
            license_id for check in checks for license_id in check.license_ids))
        release = ProductionRelease(
            release_id=f"{proposal_id}-R{self._release_seq}",
            proposal_id=proposal_id,
            version_seq=version.seq,
            design=version,
            items=proposal.items,
            approvals=board.approvals_for(version.seq),
            license_ids=license_ids,
            license_revisions=tuple(
                (license_id, self.ledger.current(license_id).revision)
                for license_id in license_ids),
            frozen_at=at,
            frozen_by=actor.actor_id,
            override_id=override.override_id if override else None,
        )
        self._releases[release.release_id] = release
        self._release_state[release.release_id] = RELEASE_ON_SALE
        self.audit.append(at=at, actor_id=actor.actor_id, action="release_frozen",
                          entity=f"release:{release.release_id}",
                          detail=f"设计版本 V{version.seq}，依据授权 {release.license_revisions}")
        return release

    # ------------------------------------------------------------------
    # 权利影响：变更/撤回/到期 -> 停售、库存处置、待结版税
    # ------------------------------------------------------------------

    def _release_still_compliant(self, release: ProductionRelease,
                                 at: datetime) -> tuple[bool, list[str]]:
        problems: list[str] = []
        for item in release.items:
            work = self.catalog.work(item.work_id)
            # 已冻结投产的数量是既成事实，影响复核只看资格维度（不重复计数量），
            # 并要求授权在当前时点仍然有效（到期即不得继续销售）
            check = evaluate_item(item, work, self.ledger, {},
                                  check_quantity=False, as_of=at)
            problems.extend(check.failures)
        return (not problems, problems)

    def _impacts_after_change(self, license_id: str, at: datetime, reason: str) -> None:
        for release in list(self._releases.values()):
            if self._release_state[release.release_id] != RELEASE_ON_SALE:
                continue
            if license_id not in release.license_ids:
                continue
            compliant, problems = self._release_still_compliant(release, at)
            if compliant:
                continue
            self._release_state[release.release_id] = RELEASE_STOPPED
            self.audit.append(at=at, actor_id=_SYSTEM_ACTOR, action="release_stopped",
                              entity=f"release:{release.release_id}",
                              detail=f"{reason}；" + "；".join(problems))
            self._open_task(TASK_STOP_SALE, release, license_id, reason, at,
                            dedup_per_release=True)
            self._open_task(TASK_INVENTORY, release, license_id, reason, at,
                            dedup_per_release=True)
            self._open_task(TASK_ROYALTY, release, license_id, reason, at,
                            dedup_per_release=False)  # 版税按授权逐笔结算

    def _open_task(self, kind: str, release: ProductionRelease, license_id: str,
                   reason: str, at: datetime, *, dedup_per_release: bool) -> None:
        for task in self._tasks.values():
            if (task.release_id == release.release_id and task.kind == kind
                    and task.status == TASK_OPEN
                    and (dedup_per_release or task.license_id == license_id)):
                return
        self._task_seq += 1
        task = ImpactTask(task_id=f"T-{self._task_seq:04d}", kind=kind,
                          release_id=release.release_id, license_id=license_id,
                          reason=reason, created_at=at)
        self._tasks[task.task_id] = task
        self.audit.append(at=at, actor_id=_SYSTEM_ACTOR, action="task_created",
                          entity=f"task:{task.task_id}",
                          detail=f"{kind} | 产品 {release.release_id} | 授权 {license_id} | {reason}")

    def complete_task(self, actor: Actor, task_id: str, *, note: str,
                      at: datetime) -> ImpactTask:
        try:
            task = self._tasks[task_id]
        except KeyError:
            raise NotFound(f"任务不存在: {task_id}") from None
        self._require(actor, _TASK_ROLES[task.kind])
        if task.status != TASK_OPEN:
            raise StateError("任务已关闭")
        done = replace(task, status=TASK_DONE, done_at=at, note=note)
        self._tasks[task_id] = done
        self.audit.append(at=at, actor_id=actor.actor_id, action="task_completed",
                          entity=f"task:{task_id}", detail=f"{task.kind}: {note}")
        return done

    # ------------------------------------------------------------------
    # 到期提醒扫描
    # ------------------------------------------------------------------

    def scan_expiry(self, actor: Actor, now: datetime, *,
                    remind_within_days: int = 30) -> dict[str, int]:
        self._require(actor, {ROLE_REGISTRAR, ROLE_CURATOR, ROLE_ADMIN})
        reminded = expired = 0
        for lic in self.ledger.all_current():
            if self.ledger.status(lic.license_id) != "active":
                continue
            if now >= lic.valid_until:
                if lic.license_id in self._expired_processed:
                    continue
                self._expired_processed.add(lic.license_id)
                expired += 1
                self.audit.append(at=now, actor_id=actor.actor_id, action="license_expired",
                                  entity=f"license:{lic.license_id}",
                                  detail=f"有效期至 {lic.valid_until:%Y-%m-%d}")
                self._impacts_after_change(lic.license_id, now, "授权到期")
            elif lic.valid_until - now <= timedelta(days=remind_within_days):
                if lic.license_id in self._reminded:
                    continue
                self._reminded.add(lic.license_id)
                reminded += 1
                self.audit.append(at=now, actor_id=actor.actor_id, action="license_expiring",
                                  entity=f"license:{lic.license_id}",
                                  detail=f"将于 {(lic.valid_until - now).days} 天后到期")
        for override in self._overrides.values():
            if now >= override.valid_until and override.override_id not in self._overrides_expired:
                self._overrides_expired.add(override.override_id)
                self.audit.append(at=now, actor_id=actor.actor_id, action="override_expired",
                                  entity=f"override:{override.override_id}",
                                  detail=f"紧急放行已于 {override.valid_until:%Y-%m-%d %H:%M} 失效")
        return {"reminded": reminded, "expired": expired}

    # ------------------------------------------------------------------
    # 销售登记与版税对账
    # ------------------------------------------------------------------

    def record_sale(self, actor: Actor, release_id: str, *, channel: str,
                    territory: str, units: int, gross, period: str,
                    at: datetime) -> SaleRecord:
        self._require(actor, {ROLE_SUPPLY, ROLE_FINANCE, ROLE_CURATOR, ROLE_ADMIN})
        if release_id not in self._releases:
            raise NotFound(f"投产版本不存在: {release_id}")
        if self._release_state[release_id] != RELEASE_ON_SALE:
            raise StateError("产品已停售，后续销售须通过停售与版税结算流程处理")
        if units <= 0:
            raise ValidationError("销售数量必须为正数")
        release = self._releases[release_id]
        planned = sum(item.planned_quantity for item in release.items)
        sold = sum(s.units for s in self._sales if s.release_id == release_id)
        if sold + units > planned:
            raise ValidationError(f"销售数量超过投产数量（投产 {planned}，已售 {sold}，本次 {units}）")
        record = SaleRecord(release_id=release_id, channel=channel, territory=territory,
                            units=units, gross=Decimal(str(gross)), period=period,
                            at=at, actor_id=actor.actor_id)
        self._sales.append(record)
        self.audit.append(at=at, actor_id=actor.actor_id, action="sale_recorded",
                          entity=f"release:{release_id}",
                          detail=f"{period} 渠道 {channel} 地域 {territory} "
                                 f"销量 {units} 销售额 {record.gross}")
        return record

    def reconcile(self, actor: Actor, license_id: str, *, period: str,
                  at: datetime) -> RoyaltyStatement:
        self._require(actor, {ROLE_FINANCE, ROLE_ADMIN})
        lic = self.ledger.current(license_id)
        if lic is None:
            raise NotFound(f"授权不存在: {license_id}")
        if lic.royalty is None:
            raise ValidationError("该授权无版税条款")
        units = 0
        gross = Decimal("0")
        for release_id, release in self._releases.items():
            if license_id not in release.license_ids:
                continue
            for sale in self._sales:
                if sale.release_id == release_id and sale.period == period:
                    units += sale.units
                    gross += sale.gross
        term = lic.royalty
        if term.kind == ROYALTY_PER_UNIT:
            due = term.rate * units
        else:
            due = gross * term.rate / Decimal("100")
        statement = RoyaltyStatement(license_id=license_id, period=period, units=units,
                                     gross=gross, due=due, currency=term.currency)
        self.audit.append(at=at, actor_id=actor.actor_id, action="royalty_reconciled",
                          entity=f"license:{license_id}",
                          detail=f"期间 {period} 销量 {units}，销售额 {gross}，"
                                 f"应结版税 {due} {term.currency}")
        return statement

    # ------------------------------------------------------------------
    # 读取（接口层使用）
    # ------------------------------------------------------------------

    def proposals_for_partner(self, actor: Actor) -> tuple[ProductProposal, ...]:
        if actor.role != ROLE_PARTNER:
            raise PermissionDenied("仅外部合作方使用该视图")
        return tuple(p for p in self._proposals.values() if p.partner_org == actor.org)

    def proposal_status(self, actor: Actor, proposal_id: str) -> dict:
        proposal = self._proposal(proposal_id)
        self._check_proposal_visible(actor, proposal)
        board = self._boards[proposal_id]
        current = board.current
        return {
            "proposal": proposal,
            "versions": len(board.versions),
            "current_version": current.seq if current else None,
            "missing_gates": sorted(board.missing_gates()) if current else None,
            "releases": [(rid, self._release_state[rid])
                         for rid, r in self._releases.items()
                         if r.proposal_id == proposal_id],
        }

    def tasks(self, actor: Actor, *, open_only: bool = False) -> tuple[ImpactTask, ...]:
        self._require(actor, {ROLE_REGISTRAR, ROLE_CURATOR, ROLE_SUPPLY,
                              ROLE_FINANCE, ROLE_ADMIN})
        return tuple(t for t in self._tasks.values() if not open_only or t.status == TASK_OPEN)

    def releases(self, actor: Actor) -> tuple[ProductionRelease, ...]:
        self._require(actor, {ROLE_REGISTRAR, ROLE_CURATOR, ROLE_ACADEMIC, ROLE_LEGAL,
                              ROLE_SUPPLY, ROLE_FINANCE, ROLE_ADMIN})
        return tuple(self._releases.values())

    def release_state(self, actor: Actor, release_id: str) -> str:
        self._require(actor, {ROLE_REGISTRAR, ROLE_CURATOR, ROLE_ACADEMIC, ROLE_LEGAL,
                              ROLE_SUPPLY, ROLE_FINANCE, ROLE_ADMIN})
        try:
            return self._release_state[release_id]
        except KeyError:
            raise NotFound(f"投产版本不存在: {release_id}") from None

    def audit_entries(self, actor: Actor) -> tuple:
        if actor.org != MUSEUM_ORG:
            raise PermissionDenied("审计记录仅面向馆方")
        return self.audit.entries
