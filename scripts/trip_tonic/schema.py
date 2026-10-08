"""JSON Schema 加载与标准库子集校验器。

只实现本项目两个 reference schema 实际用到的 JSON Schema 关键字
（type/const/enum/minLength/format:date/pattern/minimum/required/
properties/items/prefixItems/minItems/maxItems），因此零第三方依赖。

schema 文件本身也走严格 JSON 解析：解析失败抛 SchemaCorruptError，
validator 将其报告为 SCHEMA_CORRUPT 硬错误——参考契约坏了绝不静默降级。
"""

import re
from pathlib import Path

from .common import REPO_ROOT, _issue, _valid_date, load_json_file

GUIDE_SCHEMA_PATH = REPO_ROOT / "references" / "guide-schema.json"
RESEARCH_SCHEMA_PATH = REPO_ROOT / "references" / "research-record-schema.json"


class SchemaCorruptError(ValueError):
    """参考 schema 自身损坏（如重复键、非法 JSON）时抛出。"""


# 进程内缓存：schema 文件在同一命令里只会加载一次
_schema_cache = {}


def _load_cached(path, cache_key):
    """按缓存键加载 schema；解析失败转为 SchemaCorruptError。"""
    if cache_key not in _schema_cache:
        try:
            _schema_cache[cache_key] = load_json_file(path)
        except ValueError as error:
            raise SchemaCorruptError("参考 schema 无法解析：{}".format(error)) from error
    return _schema_cache[cache_key]


def load_guide_schema():
    """加载 guide-schema.json（缓存）。"""
    return _load_cached(GUIDE_SCHEMA_PATH, "guide")


def load_research_schema():
    """加载 research-record-schema.json（缓存）。"""
    return _load_cached(RESEARCH_SCHEMA_PATH, "research")


def _schema_issues(value, schema, path="$", root=True):
    """递归校验 value 是否满足 schema 子集，返回问题列表（空即通过）。

    注意 pattern 按 JSON Schema 规范用部分匹配（re.search），不是 fullmatch；
    日期 format 复用 _valid_date 的严格 YYYY-MM-DD 检查。
    """
    issues = []
    expected = schema.get("type")
    # JSON Schema 的 integer 不接受 true/false（Python 里 bool 是 int 子类，需排除）
    types = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool}
    if expected:
        accepted = types.get(expected)
        valid = isinstance(value, accepted) if accepted else True
        if expected == "integer":
            valid = isinstance(value, int) and not isinstance(value, bool)
        elif expected == "number":
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
        if not valid:
            return [_issue("error", "SCHEMA_TYPE", "期望类型 {}".format(expected), path)]
    if "const" in schema and value != schema["const"]:
        issues.append(_issue("error", "SCHEMA_CONST", "值必须为 {!r}".format(schema["const"]), path))
    if "enum" in schema and value not in schema["enum"]:
        issues.append(_issue("error", "SCHEMA_ENUM", "值不在允许范围内", path))
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            issues.append(_issue("error", "SCHEMA_MIN_LENGTH", "字符串不能为空", path))
        if schema.get("format") == "date" and not _valid_date(value):
            issues.append(_issue("error", "SCHEMA_DATE", "日期格式必须为 YYYY-MM-DD", path))
        pattern = schema.get("pattern")
        if pattern and not re.search(pattern, value):
            issues.append(_issue("error", "SCHEMA_PATTERN", "字符串格式无效", path))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < schema.get("minimum", float("-inf")):
            issues.append(_issue("error", "SCHEMA_MINIMUM", "数值低于最小值", path))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", []):
            if required not in value:
                issues.append(_issue("error", "SCHEMA_REQUIRED", "缺少必需字段 {}".format(required), path + ("." if path != "$" else "") + required))
        # 只递归声明过的属性；未声明字段交给 additionalProperties 策略（本 schema 均为 true）
        for key, child in properties.items():
            if key in value:
                issues.extend(_schema_issues(value[key], child, path + ("." if path != "$" else "") + key, False))
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            issues.append(_issue("error", "SCHEMA_MIN_ITEMS", "数组元素数量不足", path))
        if len(value) > schema.get("maxItems", float("inf")):
            issues.append(_issue("error", "SCHEMA_MAX_ITEMS", "数组元素数量超过限制", path))
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, child in enumerate(value):
                issues.extend(_schema_issues(child, item_schema, "{}[{}]".format(path, index), False))
        prefix = schema.get("prefixItems", [])
        for index, child_schema in enumerate(prefix[:len(value)]):
            issues.extend(_schema_issues(value[index], child_schema, "{}[{}]".format(path, index), False))
    return issues
