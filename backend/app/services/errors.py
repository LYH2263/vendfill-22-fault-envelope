"""失败信封：失败路径只允许出现 code / subject / detail 三个字段。

- 成功回包禁止携带 code/subject/detail；
- 任何失败都必须通过 FailError 抛出，由处理器统一落成三字段信封，
  禁止只回无码字符串；
- DETAIL_FULL 是说明全文的唯一真源（前端 errors.ts 仅做只读镜像，用于漂移比对）；
  落库与回包只存按 DETAIL_MAXLEN 截短后的 detail，前端不得补全写回；
- 模板只允许使用 {subject} 一个占位：三字段信封是三口同字的唯一来源，
  前端仅凭信封即可由全文真源判断当前 detail 是否被截短（说明漂移）。
"""
from __future__ import annotations

# 原因码
LOCATION_NOT_FOUND = "location_not_found"
LANE_NOT_FOUND = "lane_not_found"
REFILL_NOT_FOUND = "refill_not_found"
GENERATION_REJECTED = "generation_rejected"
MANUAL_OVER_GAP = "manual_over_gap"
FULFILL_CONFLICT = "fulfill_conflict"
INVALID_CAPACITY = "invalid_capacity"
BAD_REQUEST = "bad_request"
NOT_FOUND = "not_found"
METHOD_NOT_ALLOWED = "method_not_allowed"
INTERNAL_ERROR = "internal_error"

ALL_CODES = (
    LOCATION_NOT_FOUND,
    LANE_NOT_FOUND,
    REFILL_NOT_FOUND,
    GENERATION_REJECTED,
    MANUAL_OVER_GAP,
    FULFILL_CONFLICT,
    INVALID_CAPACITY,
    BAD_REQUEST,
    NOT_FOUND,
    METHOD_NOT_ALLOWED,
    INTERNAL_ERROR,
)

# 说明全文（唯一真源）。仅以对象标识 subject 为参数，保证三口同字、可离线比对。
DETAIL_FULL: dict[str, str] = {
    GENERATION_REJECTED: (
        "生成被拒：{subject} 存在缺口为负的超占货道，库存与在途之和已超过货道容量，"
        "无法生成补货单；请先核销在途或调整库存后重试。"
    ),
    MANUAL_OVER_GAP: (
        "手改超缺口：{subject} 的手工补量超过该货道当前缺口，补量必须为不超过缺口的"
        "非负整数；请按缺口范围内重新填报。"
    ),
    FULFILL_CONFLICT: (
        "核销冲突：{subject} 核销时库存或在途已相对生成补货单时发生变化，"
        "为避免半改库存，本次核销已整体作废、不落任何改动；请重新生成补货单。"
    ),
    INVALID_CAPACITY: (
        "非法容量保存：{subject} 提交的容量非法，容量必须为不小于 1 的整数，"
        "且不得低于当前库存与在途之和；本次保存已拒绝。"
    ),
    LOCATION_NOT_FOUND: "点位不存在：{subject} 未找到，请核对点位标识后重试。",
    LANE_NOT_FOUND: "货道不存在：{subject} 未找到，请核对货道标识后重试。",
    REFILL_NOT_FOUND: "补货单不存在：{subject} 未找到，请核对补货单号后重试。",
    BAD_REQUEST: "请求不合法：{subject}；请按接口字段与类型要求修正后重试。",
    NOT_FOUND: "资源不存在：{subject} 未匹配到任何接口或数据，请核对地址后重试。",
    METHOD_NOT_ALLOWED: "方法不允许：{subject}；请改用该资源支持的请求方法。",
    INTERNAL_ERROR: "服务内部错误：{subject} 处理失败，本次请求未落任何改动，请稍后重试。",
}

# 落库/回包说明长度上限（按字符）。种子两条失败说明均超过此上限而被截短，
# 用于验证「截短后仍显示截短并带漂移」。
DETAIL_MAXLEN = 40

TRUNC_MARK = "…"


def render_detail(code: str, subject: object) -> str:
    """渲染说明全文，再按 DETAIL_MAXLEN 截短；返回值即落库/回包的 detail。"""
    text = DETAIL_FULL[code].format(subject=str(subject))
    if len(text) <= DETAIL_MAXLEN:
        return text
    return text[: DETAIL_MAXLEN - len(TRUNC_MARK)] + TRUNC_MARK


def envelope(code: str, subject: str, detail: str) -> dict[str, str]:
    """三字段信封；字段集合与顺序固定为 code, subject, detail。"""
    return {"code": code, "subject": str(subject), "detail": detail}


class FailError(Exception):
    """所有业务失败的唯一载体；禁止以无码字符串替代。"""

    def __init__(self, code: str, subject: str, detail: str, status_code: int = 422):
        self.code = code
        self.subject = str(subject)
        self.detail = detail
        self.status_code = status_code
        super().__init__(f"[{code}] {subject}: {detail}")

    def to_envelope(self) -> dict[str, str]:
        return envelope(self.code, self.subject, self.detail)


def fail(code: str, subject: object, *, status_code: int = 422) -> FailError:
    """由原因码与对象标识构造失败；detail 由全文真源渲染（可能截短）。"""
    return FailError(code, str(subject), render_detail(code, subject), status_code=status_code)
