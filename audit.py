"""追加式审计日志。

到期提醒、权利影响、版税对账等关键动作全部落账；条目以哈希链
串联，任何事后篡改都会被 verify() 发现。日志只提供追加与读取，
不提供修改接口。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

GENESIS = "GENESIS"


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    at: datetime
    actor_id: str
    action: str
    entity: str
    detail: str
    prev_hash: str
    digest: str


def _digest(seq: int, at: datetime, actor_id: str, action: str,
            entity: str, detail: str, prev_hash: str) -> str:
    payload = "|".join([str(seq), at.isoformat(), actor_id, action, entity, detail, prev_hash])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []

    def append(self, *, at: datetime, actor_id: str, action: str,
               entity: str, detail: str = "") -> AuditEntry:
        prev_hash = self._entries[-1].digest if self._entries else GENESIS
        seq = len(self._entries) + 1
        entry = AuditEntry(
            seq=seq, at=at, actor_id=actor_id, action=action, entity=entity,
            detail=detail, prev_hash=prev_hash,
            digest=_digest(seq, at, actor_id, action, entity, detail, prev_hash),
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[AuditEntry, ...]:
        return tuple(self._entries)

    def of(self, *, action: str | None = None, entity: str | None = None) -> tuple[AuditEntry, ...]:
        return tuple(
            entry for entry in self._entries
            if (action is None or entry.action == action)
            and (entity is None or entry.entity == entity)
        )

    def verify(self) -> bool:
        prev_hash = GENESIS
        for entry in self._entries:
            if entry.prev_hash != prev_hash:
                return False
            if entry.digest != _digest(entry.seq, entry.at, entry.actor_id,
                                       entry.action, entry.entity, entry.detail,
                                       entry.prev_hash):
                return False
            prev_hash = entry.digest
        return True
