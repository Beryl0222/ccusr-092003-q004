"""美术馆文创授权的基础领域对象。"""
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Grant:
    grant_id: str
    work_id: str
    holder_id: str
    scope: frozenset[str]
    valid_from: datetime
    valid_until: datetime
    revision: int

    def covers(self, action: str, at: datetime) -> bool:
        return action in self.scope and self.valid_from <= at < self.valid_until


def validate_grant(grant: Grant) -> None:
    if not grant.grant_id or not grant.work_id or not grant.holder_id:
        raise ValueError("授权记录缺少主体标识")
    if grant.revision < 1 or grant.valid_until <= grant.valid_from:
        raise ValueError("授权版本或有效期无效")
