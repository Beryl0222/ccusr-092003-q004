"""授权变化对在售产品的影响处置任务。"""
from dataclasses import dataclass
from datetime import datetime

TASK_STOP_SALE = "停售"
TASK_INVENTORY = "库存处置"
TASK_ROYALTY = "待结版税"

TASK_OPEN = "open"
TASK_DONE = "done"


@dataclass(frozen=True)
class ImpactTask:
    task_id: str
    kind: str
    release_id: str
    license_id: str
    reason: str
    created_at: datetime
    status: str = TASK_OPEN
    done_at: datetime | None = None
    note: str = ""
