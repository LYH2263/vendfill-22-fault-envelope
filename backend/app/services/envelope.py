"""失败信封：成功与失败严格互斥。

失败路径只允许三个字段：error_code（原因码）、object_id（对象标识）、message（说明全文）。
成功路径禁止出现其中任何一个字段。

说明落库前统一截断：超出 MESSAGE_MAX 即截短并追加漂移标记「说明漂移」，
页上显示的就是这条截短文本本身；任何一方都不得把它补全写回。
"""
from __future__ import annotations

from dataclasses import dataclass

MESSAGE_MAX = 80
DRIFT_MARK = "说明漂移"
ERROR_FIELDS = ("error_code", "object_id", "message")


@dataclass
class AppError(Exception):
    """携带三字段信封内容的业务异常，绝不可退化为无码字符串。"""

    error_code: str
    object_id: str
    message: str
    http_status: int = 422


def truncate_message(message: str) -> tuple[str, bool]:
    """返回 (落库/回包说明, 是否漂移)。超长则截短并追加漂移标记。"""
    if message is None:
        return "", False
    if len(message) <= MESSAGE_MAX:
        return message, False
    keep = MESSAGE_MAX - len(DRIFT_MARK)
    return message[:max(keep, 0)] + DRIFT_MARK, True


def envelope(error_code: str, object_id: str | int, message: str) -> dict:
    """构造三字段信封——顺序固定、字段固定，多一个少一个都不行。"""
    text, _ = truncate_message(str(message))
    return {"error_code": error_code, "object_id": str(object_id), "message": text}
