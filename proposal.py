"""产品提案：引用多件作品，逐项声明用途、地域、渠道、数量与销售窗口。"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProposalItem:
    work_id: str
    usages: frozenset[str]
    territories: frozenset[str]
    channels: frozenset[str]
    planned_quantity: int
    sale_from: datetime
    sale_until: datetime

    def __post_init__(self):
        object.__setattr__(self, "usages", frozenset(self.usages))
        object.__setattr__(self, "territories", frozenset(self.territories))
        object.__setattr__(self, "channels", frozenset(self.channels))


@dataclass(frozen=True)
class ProductProposal:
    proposal_id: str
    exhibition_id: str
    title: str
    partner_org: str  # 指定设计/供应链合作方，合作方承诺由其作出
    items: tuple[ProposalItem, ...]
    created_by: str
    created_at: datetime

    def __post_init__(self):
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class RightsCheck:
    """单个提案条目的权利核验结果。"""
    item: ProposalItem
    ok: bool
    failures: tuple[str, ...]
    license_ids: tuple[str, ...]  # 通过时：每个权利主体各自依据的授权
