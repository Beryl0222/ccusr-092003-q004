"""作品与权利主体登记。

入藏只记录保管事实，不隐含复制、改编或商业销售等任何授权；
作品可以有多个权利主体（艺术家、家属、机构），授权必须逐一取得。
"""
from dataclasses import dataclass

from errors import NotFound, ValidationError


@dataclass(frozen=True)
class RightsHolder:
    holder_id: str
    name: str
    kind: str  # 艺术家 / 家属 / 机构 / 基金会


@dataclass(frozen=True)
class Work:
    work_id: str
    title: str
    creator: str
    holder_ids: frozenset[str]
    acquired: bool = True  # 是否已入藏；入藏不等于取得任何授权

    def __post_init__(self):
        object.__setattr__(self, "holder_ids", frozenset(self.holder_ids))


class Catalog:
    def __init__(self) -> None:
        self._holders: dict[str, RightsHolder] = {}
        self._works: dict[str, Work] = {}

    def register_holder(self, holder: RightsHolder) -> None:
        if not holder.holder_id or not holder.name:
            raise ValidationError("权利主体缺少标识或名称")
        if holder.holder_id in self._holders:
            raise ValidationError(f"权利主体已登记: {holder.holder_id}")
        self._holders[holder.holder_id] = holder

    def register_work(self, work: Work) -> None:
        if not work.work_id or not work.title:
            raise ValidationError("作品缺少标识或题名")
        if work.work_id in self._works:
            raise ValidationError(f"作品已登记: {work.work_id}")
        if not work.holder_ids:
            raise ValidationError("作品必须登记至少一个权利主体")
        missing = work.holder_ids - self._holders.keys()
        if missing:
            raise ValidationError(f"权利主体未登记: {sorted(missing)}")
        self._works[work.work_id] = work

    def holder(self, holder_id: str) -> RightsHolder:
        try:
            return self._holders[holder_id]
        except KeyError:
            raise NotFound(f"权利主体不存在: {holder_id}") from None

    def work(self, work_id: str) -> Work:
        try:
            return self._works[work_id]
        except KeyError:
            raise NotFound(f"作品不存在: {work_id}") from None

    def works(self) -> tuple[Work, ...]:
        return tuple(self._works.values())

    def holders(self) -> tuple[RightsHolder, ...]:
        return tuple(self._holders.values())
