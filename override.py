"""紧急人工放行：限定时效、责任到人。

放行只能豁免流程性审批环节（学术/法务/合作方承诺），永远不能
豁免权利条件；超过时效的放行自动失效，并在到期扫描中落账。
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class EmergencyOverride:
    override_id: str
    proposal_id: str
    gates: frozenset[str]  # 被放行的审批环节（仅流程环节，不含权利条件）
    issued_by: str
    issued_at: datetime
    valid_until: datetime  # 限定时效
    responsibility: str    # 责任说明

    def __post_init__(self):
        object.__setattr__(self, "gates", frozenset(self.gates))

    def active(self, at: datetime) -> bool:
        return self.issued_at <= at < self.valid_until
