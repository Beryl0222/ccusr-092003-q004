"""逐项权利核验。

提案条目必须对作品的**每一个**权利主体都找到有效授权，并逐项满足
用途、地域、渠道、数量、销售窗口与版税条件；任一维度不满足都会
形成具体的失败原因，而不是笼统的"未授权"。

as_of 用于权利影响复核：除了销售窗口，还要求授权在该时点仍然有效
（授权到期后即使原销售窗口在其有效期内，也不得继续销售）。
"""
from datetime import datetime

from catalog import Work
from licensing import USAGE_SELL, LicenseLedger
from proposal import ProposalItem, RightsCheck


def evaluate_item(item: ProposalItem, work: Work, ledger: LicenseLedger,
                  allocated: dict[str, int], *,
                  check_quantity: bool = True,
                  as_of: datetime | None = None) -> RightsCheck:
    failures: list[str] = []
    license_ids: list[str] = []
    for holder_id in sorted(work.holder_ids):
        lic = ledger.active_for(work.work_id, holder_id)
        if lic is None:
            if ledger.ever_licensed(work.work_id, holder_id):
                failures.append(f"权利主体 {holder_id} 的授权已撤回")
            else:
                failures.append(f"缺少权利主体 {holder_id} 的授权（入藏不等于授权）")
            continue
        if as_of is not None and not lic.valid_from <= as_of < lic.valid_until:
            if as_of >= lic.valid_until:
                failures.append(
                    f"权利主体 {holder_id} 的授权已于 {lic.valid_until:%Y-%m-%d} 到期")
            else:
                failures.append(
                    f"权利主体 {holder_id} 的授权 {lic.valid_from:%Y-%m-%d} 才生效")
        if not lic.covers_window(item.sale_from, item.sale_until):
            failures.append(
                f"权利主体 {holder_id} 的授权有效期 "
                f"{lic.valid_from:%Y-%m-%d}~{lic.valid_until:%Y-%m-%d} "
                f"不覆盖销售窗口 {item.sale_from:%Y-%m-%d}~{item.sale_until:%Y-%m-%d}")
        for usage in sorted(item.usages - lic.usages):
            failures.append(f"用途「{usage}」不在权利主体 {holder_id} 的许可范围")
        for territory in sorted(item.territories):
            if not lic.covers_territory(territory):
                failures.append(f"地域「{territory}」不在权利主体 {holder_id} 的许可范围")
        for channel in sorted(item.channels - lic.channels):
            failures.append(f"渠道「{channel}」不在权利主体 {holder_id} 的许可范围")
        if USAGE_SELL in item.usages and lic.royalty is None:
            failures.append(f"权利主体 {holder_id} 的授权缺少商业销售版税条款")
        if check_quantity and lic.quantity_cap is not None:
            remaining = lic.quantity_cap - allocated.get(lic.license_id, 0)
            if item.planned_quantity > remaining:
                failures.append(
                    f"数量超出权利主体 {holder_id} 的许可上限"
                    f"（上限 {lic.quantity_cap}，剩余 {remaining}，申请 {item.planned_quantity}）")
        license_ids.append(lic.license_id)
    ok = not failures
    return RightsCheck(item, ok, tuple(failures), tuple(license_ids) if ok else ())
