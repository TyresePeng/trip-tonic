"""规范化输出：guide.json 的规范键序 + 安全默认值。

guide.normalized.json 产物使用规范键序，两个目的：
1. 同一份攻略经不同工具链生成后 diff 稳定（键序不抖动）
2. 自动补 day 编号与 meta.days，便于逐日对比

未声明的额外字段全部保留（schema 允许 additionalProperties），
只排序、不改值。
"""

import json

# 各层级的规范键序；未列出的键按字母序追加在已知键之后
_CANONICAL_ORDER = {
    "root": ["schema_version", "meta", "preferences", "sources", "route", "days", "checklist", "evidence", "images", "image_suggestions", "transport", "hotels", "foods", "businesses", "avoid", "tips", "assumptions", "budget"],
    "meta": ["title", "subtitle", "destination", "origin", "language", "start_date", "days", "travelers", "currency", "timezone", "assumptions"],
    "preferences": ["budget_level", "pace", "group_type", "party_summary", "interests", "dietary", "accessibility", "transport", "earliest_start", "latest_end"],
    "sources": ["id", "title", "url", "type", "checked_at", "confidence", "media", "notes"],
    "media": ["type", "url", "description"],
    "route": ["overview", "stops", "legs", "caveats"],
    "stops": ["name", "day", "coords", "source_ids", "notes"],
    "legs": ["from", "to", "mode", "duration_min", "duration_text", "distance_km", "estimated", "source_ids", "notes"],
    "days": ["day", "date", "title", "backup", "items", "notes"],
    "items": ["name", "type", "start", "end", "description", "backup", "coords", "source_ids", "recommendation", "confidence", "estimated", "route_from_previous", "price"],
    "route_from_previous": ["mode", "duration_min", "duration_text", "distance_km", "estimated", "source_ids", "notes"],
    "backup": ["condition", "plan", "source_ids"],
    "images": ["title", "path", "alt", "caption", "license", "source_ids"],
    "image_suggestions": ["title", "description", "caption", "prompt", "source_ids"],
    "checklist": ["title", "detail", "date", "phase", "source_ids"],
    "evidence": ["topic", "claim", "summary", "status", "checked_at", "confidence", "caveat", "source_ids"],
    "transport": ["mode", "title", "detail", "price", "recommended", "source_ids"],
    "hotels": ["name", "area", "reason", "price", "address", "hours", "connection", "days", "date", "nights", "checked_at", "confidence", "source_ids"],
    "foods": ["name", "shop", "reason", "price", "address", "hours", "checked_at", "confidence", "source_ids"],
    "businesses": ["name", "category", "address", "hours", "phone", "price", "reason", "checked_at", "confidence", "source_ids"],
    "avoid": ["wrong", "right", "name", "reason", "source_ids", "checked_at"],
}


def _ordered(value, order_key):
    """递归重排字典键序：已知键按规范序，未知键按字母序追加。"""
    if isinstance(value, dict):
        order = _CANONICAL_ORDER.get(order_key)
        if not order:
            return value
        keys = [key for key in order if key in value] + sorted(key for key in value if key not in order)
        result = {}
        for key in keys:
            # 键名出现在键序表里才会递归排序其子结构（如 sources -> media）
            child_key = key if key in _CANONICAL_ORDER else None
            result[key] = _ordered(value[key], child_key) if child_key else value[key]
        return result
    if isinstance(value, list):
        return [_ordered(entry, order_key) for entry in value]
    return value


def normalized_guide(guide):
    """规范化键序并补全天数编号（day 编号、meta.days）；额外字段一律保留。"""
    # 深拷贝：规范化产物绝不回写调用方的 guide 对象
    result = _ordered(json.loads(json.dumps(guide, ensure_ascii=False)), "root")
    days = result.get("days")
    if isinstance(days, list):
        for index, day in enumerate(days):
            if isinstance(day, dict) and day.get("day") is None:
                day["day"] = index + 1
        meta = result.get("meta")
        if isinstance(meta, dict) and meta.get("days") is None:
            meta["days"] = len(days)
    return result
