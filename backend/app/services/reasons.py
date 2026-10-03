"""原因码与说明全文模板——接口回包、种子数据、页面错误条共用同一套字。

任何失败都必须从这里取码取文，禁止在各处临时拼无码字符串。
"""
from __future__ import annotations

# ---- 原因码（枚举即契约，不得新增无码分支） ----
GEN_OVERBOOKED = "GEN_OVERBOOKED"                # 生成被拒：存在超占货道
MANUAL_OVER_GAP = "MANUAL_OVER_GAP"              # 手改补货量超过缺口
MANUAL_QTY_INVALID = "MANUAL_QTY_INVALID"        # 手改补货量不是非负整数
REDEEM_ALREADY = "REDEEM_ALREADY_REDEEMED"       # 核销冲突：重复核销
REDEEM_EXCEEDS = "REDEEM_EXCEEDS_CAPACITY"       # 核销冲突：落库会超容量
CAP_INVALID = "INVALID_CAPACITY"                 # 非法容量保存
LINE_NOT_IN_ORDER = "LINE_NOT_IN_ORDER"
LOCATION_NOT_FOUND = "LOCATION_NOT_FOUND"
ORDER_NOT_FOUND = "ORDER_NOT_FOUND"
LANE_NOT_FOUND = "LANE_NOT_FOUND"
BAD_REQUEST = "BAD_REQUEST"

SCENE_GENERATE = "generate"
SCENE_MANUAL = "manual_edit"
SCENE_REDEEM = "redeem"
SCENE_CAPACITY = "capacity"


def gen_overbooked(slot_no: str, sku_name: str, cap: int, stock: int, transit: int) -> str:
    return (
        f"生成被拒：货道{slot_no}（{sku_name}）库存{stock}加在途{transit}合计{stock + transit}"
        f"已超过容量{cap}，存在超占货道，本次未生成任何补货单、未改动任何库存；"
        f"请先核销在途或调整机面库存后重新生成。"
    )


def manual_over_gap(order_id: int, slot_no: str, sku_name: str, qty: int, gap: int) -> str:
    return (
        f"手改失败：补货单{order_id}货道{slot_no}（{sku_name}）手改补货量{qty}超过当前缺口{gap}，"
        f"超出{qty - gap}件；该手改行未落单、机面库存未改动，整单保持失败前状态，"
        f"请按缺口以内的非负数量重新提交。"
    )


def manual_qty_invalid(order_id: int, slot_no: str, raw: object) -> str:
    return (
        f"手改失败：补货单{order_id}货道{slot_no}提交的补货量{raw!r}不是非负整数，"
        f"该手改行未落单、机面库存未改动，整单保持失败前状态。"
    )


def redeem_already(order_id: int) -> str:
    return (
        f"核销冲突：补货单{order_id}此前已核销，禁止重复核销；重复核销不会二次增加库存，"
        f"本次请求已整体回滚，未新增任何补货单行、未改动库存，如需补量请重新生成补货单。"
    )


def redeem_exceeds(order_id: int, slot_no: str, sku_name: str, fill: int, cap: int, stock: int) -> str:
    return (
        f"核销冲突：补货单{order_id}货道{slot_no}（{sku_name}）核销{fill}件后库存将达{stock + fill}，"
        f"超过容量{cap}；本次核销已整体回滚，全部货道库存保持失败前状态、补货单仍标记未核销。"
    )


def cap_invalid(slot_no: str, raw: object) -> str:
    return (
        f"非法容量保存：货道{slot_no}提交的容量{raw!r}不是正整数，保存已被拒绝，"
        f"机面库存与货道数据保持失败前状态。"
    )


def cap_below_holdings(slot_no: str, sku_name: str, cap: int, stock: int, transit: int) -> str:
    return (
        f"非法容量保存：货道{slot_no}（{sku_name}）容量{cap}低于库存{stock}加在途{transit}合计"
        f"{stock + transit}，保存已被拒绝，机面库存与货道数据保持失败前状态。"
    )


def cap_below_holdings(slot_no: str, sku_name: str, cap: int, stock: int, transit: int) -> str:
    return (
        f"非法容量保存：货道{slot_no}（{sku_name}）容量{cap}低于库存{stock}加在途{transit}合计"
        f"{stock + transit}，保存已被拒绝，机面库存与货道数据保持失败前状态。"
    )


def line_not_in_order(order_id: int, lane_id: int) -> str:
    return (
        f"手改失败：补货单{order_id}不含货道{lane_id}对应的行，手改目标不存在，"
        f"未落任何行、未改动库存，整单保持失败前状态。"
    )


def not_found(kind: str, ident: object) -> str:
    return (
        f"对象不存在：{kind}{ident}查无记录，请求被拒绝，未生成任何补货单、未改动任何库存。"
    )


def bad_request(path: str) -> str:
    return f"请求不合法：{path} 的参数或请求体无法解析，请求被拒绝，系统状态保持失败前状态。"
