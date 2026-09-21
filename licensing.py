"""授权登记与不可变变更链。

授权记录必须登记可核验来源（合同编号与文件摘要），按用途、地域、
渠道、数量、版税与有效期刻画许可范围。变更与撤回都以追加事件入账，
历史版本完整保留，已发生事实不会被悄悄改写。

有效期沿用 domain.py 的半开区间约定：valid_from <= t < valid_until。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from catalog import Catalog
from errors import NotFound, StateError, ValidationError

# 用途
USAGE_REPRODUCE = "复制"
USAGE_ADAPT = "改编"
USAGE_SELL = "商业销售"

# 渠道
CHANNEL_STORE = "馆内门店"
CHANNEL_ONLINE = "电商"
CHANNEL_DISTRIB = "馆外分销"

# 地域通配
TERRITORY_GLOBAL = "全球"

ROYALTY_PER_UNIT = "per_unit"
ROYALTY_PERCENT = "percent"

KIND_REGISTERED = "registered"
KIND_AMENDED = "amended"
KIND_WITHDRAWN = "withdrawn"

STATUS_ACTIVE = "active"
STATUS_WITHDRAWN = "withdrawn"


@dataclass(frozen=True)
class RoyaltyTerm:
    kind: str      # per_unit 每件定额 / percent 销售额百分比
    rate: Decimal  # 每件金额，或百分比数值（8 表示 8%）
    currency: str

    def __post_init__(self):
        object.__setattr__(self, "rate", Decimal(str(self.rate)))
        if self.kind not in (ROYALTY_PER_UNIT, ROYALTY_PERCENT):
            raise ValidationError(f"未知版税方式: {self.kind}")
        if self.rate < 0:
            raise ValidationError("版税率不能为负")
        if not self.currency:
            raise ValidationError("版税缺少结算币种")


@dataclass(frozen=True)
class License:
    license_id: str
    work_id: str
    holder_id: str
    source_ref: str    # 授权来源（合同/授权书编号）
    source_hash: str   # 授权文件摘要，可核验
    usages: frozenset[str]
    territories: frozenset[str]
    channels: frozenset[str]
    quantity_cap: int | None
    royalty: RoyaltyTerm | None
    valid_from: datetime
    valid_until: datetime
    revision: int

    def __post_init__(self):
        object.__setattr__(self, "usages", frozenset(self.usages))
        object.__setattr__(self, "territories", frozenset(self.territories))
        object.__setattr__(self, "channels", frozenset(self.channels))

    def covers_window(self, start: datetime, end: datetime) -> bool:
        return self.valid_from <= start and end <= self.valid_until

    def covers_territory(self, territory: str) -> bool:
        return territory in self.territories or TERRITORY_GLOBAL in self.territories


@dataclass(frozen=True)
class LicenseEvent:
    kind: str          # registered / amended / withdrawn
    license: License   # 事件发生后的快照（撤回时为最后一版）
    at: datetime
    actor_id: str
    reason: str


class LicenseLedger:
    """追加式授权台账：当前状态由事件链推导，历史不可改写。"""

    def __init__(self, catalog: Catalog) -> None:
        self._catalog = catalog
        self._events: list[LicenseEvent] = []
        self._current: dict[str, License] = {}
        self._status: dict[str, str] = {}

    # ---- 写入 ----

    def register(self, license: License, *, actor_id: str, at: datetime,
                 reason: str = "") -> LicenseEvent:
        if license.license_id in self._current:
            raise ValidationError(f"授权编号已存在: {license.license_id}")
        if license.revision != 1:
            raise ValidationError("新授权版本号必须为 1")
        self._validate(license)
        existing = self.active_for(license.work_id, license.holder_id)
        if existing is not None:
            raise ValidationError(
                f"权利主体 {license.holder_id} 对作品 {license.work_id} 已存在有效授权 "
                f"{existing.license_id}，请通过变更修订")
        return self._append(KIND_REGISTERED, license, at, actor_id, reason, STATUS_ACTIVE)

    def amend(self, license: License, *, actor_id: str, at: datetime,
              reason: str) -> LicenseEvent:
        if not reason or not reason.strip():
            raise ValidationError("授权变更必须说明理由")
        current = self.current(license.license_id)
        if current is None:
            raise NotFound(f"授权不存在: {license.license_id}")
        if self._status[license.license_id] != STATUS_ACTIVE:
            raise StateError("已撤回的授权不能再变更")
        if license.work_id != current.work_id or license.holder_id != current.holder_id:
            raise ValidationError("变更不能改变授权的作品或权利主体")
        if license.revision != current.revision + 1:
            raise ValidationError(f"变更版本号必须为 {current.revision + 1}")
        self._validate(license)
        return self._append(KIND_AMENDED, license, at, actor_id, reason, STATUS_ACTIVE)

    def withdraw(self, license_id: str, *, actor_id: str, at: datetime,
                 reason: str) -> LicenseEvent:
        if not reason or not reason.strip():
            raise ValidationError("撤回授权必须说明理由")
        current = self.current(license_id)
        if current is None:
            raise NotFound(f"授权不存在: {license_id}")
        if self._status[license_id] != STATUS_ACTIVE:
            raise StateError("授权已撤回")
        return self._append(KIND_WITHDRAWN, current, at, actor_id, reason, STATUS_WITHDRAWN)

    def _append(self, kind: str, license: License, at: datetime, actor_id: str,
                reason: str, status: str) -> LicenseEvent:
        event = LicenseEvent(kind, license, at, actor_id, reason)
        self._events.append(event)
        self._current[license.license_id] = license
        self._status[license.license_id] = status
        return event

    def _validate(self, license: License) -> None:
        if not license.license_id or not license.work_id or not license.holder_id:
            raise ValidationError("授权记录缺少主体标识")
        if not license.source_ref or not license.source_hash:
            raise ValidationError("授权必须登记可核验的来源（合同编号与文件摘要）")
        work = self._catalog.work(license.work_id)
        self._catalog.holder(license.holder_id)
        if license.holder_id not in work.holder_ids:
            raise ValidationError(f"{license.holder_id} 不是作品 {license.work_id} 的权利主体")
        if license.valid_until <= license.valid_from:
            raise ValidationError("授权有效期无效")
        if not license.usages or not license.territories or not license.channels:
            raise ValidationError("授权必须明确用途、地域与渠道")
        if license.quantity_cap is not None and license.quantity_cap <= 0:
            raise ValidationError("许可数量上限必须为正数")
        if USAGE_SELL in license.usages and license.royalty is None:
            raise ValidationError("含商业销售的授权必须约定版税条款")

    # ---- 读取 ----

    def current(self, license_id: str) -> License | None:
        return self._current.get(license_id)

    def status(self, license_id: str) -> str:
        return self._status.get(license_id, "unknown")

    def active_for(self, work_id: str, holder_id: str) -> License | None:
        for lic in self._current.values():
            if (lic.work_id == work_id and lic.holder_id == holder_id
                    and self._status[lic.license_id] == STATUS_ACTIVE):
                return lic
        return None

    def ever_licensed(self, work_id: str, holder_id: str) -> bool:
        return any(event.license.work_id == work_id
                   and event.license.holder_id == holder_id
                   for event in self._events)

    def all_current(self) -> tuple[License, ...]:
        return tuple(self._current.values())

    def events(self) -> tuple[LicenseEvent, ...]:
        return tuple(self._events)

    def history(self, license_id: str) -> tuple[LicenseEvent, ...]:
        return tuple(event for event in self._events
                     if event.license.license_id == license_id)
