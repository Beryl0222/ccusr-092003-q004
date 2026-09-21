"""权利链服务的领域异常。"""


class RightsChainError(Exception):
    """领域错误的基类。"""


class PermissionDenied(RightsChainError):
    """角色或机构无权执行该操作。"""


class NotFound(RightsChainError):
    """引用的实体不存在。"""


class ValidationError(RightsChainError):
    """数据不满足领域约束。"""


class StateError(RightsChainError):
    """当前状态不允许该操作。"""


class RightsNotSatisfied(RightsChainError):
    """提案引用作品的权利条件未逐项满足。"""

    def __init__(self, checks):
        self.checks = tuple(checks)
        failures = [failure for check in self.checks for failure in check.failures]
        super().__init__("权利条件未满足: " + "; ".join(failures))


class ApprovalIncomplete(RightsChainError):
    """学术审核、法务确认、合作方承诺未在当前设计版本上汇合。"""
