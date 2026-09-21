"""设计送审版本与三方审批汇合。

设计文件每次送审都形成新版本；学术审核、法务确认、合作方承诺只
针对当前版本，送审新版本后旧版本上的审批不再计入汇合。冻结形成
的投产版本是不可变快照：之后权利变化只触发处置，不改写本记录。
"""
from dataclasses import dataclass
from datetime import datetime

from errors import StateError, ValidationError
from proposal import ProposalItem

GATE_ACADEMIC = "学术审核"
GATE_LEGAL = "法务确认"
GATE_PARTNER = "合作方承诺"
GATES = (GATE_ACADEMIC, GATE_LEGAL, GATE_PARTNER)


@dataclass(frozen=True)
class DesignVersion:
    version_id: str
    proposal_id: str
    seq: int
    file_ref: str
    file_hash: str
    submitted_by: str
    submitted_at: datetime
    note: str = ""


@dataclass(frozen=True)
class Approval:
    gate: str
    version_seq: int
    actor_id: str
    at: datetime
    comment: str = ""


class ApprovalBoard:
    """每个提案一块看板：送审产生新版本，审批只针对当前版本。"""

    def __init__(self, proposal_id: str) -> None:
        self.proposal_id = proposal_id
        self.versions: list[DesignVersion] = []
        self.approvals: list[Approval] = []

    @property
    def current(self) -> DesignVersion | None:
        return self.versions[-1] if self.versions else None

    def submit(self, *, file_ref: str, file_hash: str, submitted_by: str,
               at: datetime, note: str = "") -> DesignVersion:
        if not file_ref or not file_hash:
            raise ValidationError("送审必须提供设计文件引用与内容摘要")
        seq = len(self.versions) + 1
        version = DesignVersion(f"{self.proposal_id}-V{seq}", self.proposal_id, seq,
                                file_ref, file_hash, submitted_by, at, note)
        self.versions.append(version)
        return version

    def approve(self, *, gate: str, actor_id: str, at: datetime,
                comment: str = "") -> Approval:
        if gate not in GATES:
            raise ValidationError(f"未知审批环节: {gate}")
        current = self.current
        if current is None:
            raise StateError("尚未提交设计文件，无法审批")
        if any(a.gate == gate and a.version_seq == current.seq for a in self.approvals):
            raise StateError(f"{gate} 已在版本 V{current.seq} 上确认，如需复议请先送审新版本")
        approval = Approval(gate, current.seq, actor_id, at, comment)
        self.approvals.append(approval)
        return approval

    def missing_gates(self) -> frozenset[str]:
        current = self.current
        if current is None:
            return frozenset(GATES)
        done = {a.gate for a in self.approvals if a.version_seq == current.seq}
        return frozenset(gate for gate in GATES if gate not in done)

    def approvals_for(self, version_seq: int) -> tuple[Approval, ...]:
        return tuple(a for a in self.approvals if a.version_seq == version_seq)


@dataclass(frozen=True)
class ProductionRelease:
    """冻结的投产版本：事实快照，之后权利变化只触发处置，不改写本记录。"""
    release_id: str
    proposal_id: str
    version_seq: int
    design: DesignVersion
    items: tuple[ProposalItem, ...]
    approvals: tuple[Approval, ...]
    license_ids: tuple[str, ...]
    license_revisions: tuple[tuple[str, int], ...]
    frozen_at: datetime
    frozen_by: str
    override_id: str | None = None
