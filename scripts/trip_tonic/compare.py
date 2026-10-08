"""攻略对比：结构摘要 diff + 语义变更 + 取舍评估。

语义匹配以"天序号 + 行程项名称"为键——刻意保守：重命名的
行程项会被当作删除+新增处理，不做模糊匹配猜测。

输出三部分：
- differences：元信息/天数/停靠点/预算合计等结构层差异
- semantic：  逐日行程项增删与时间变化、路线段增删改、预算变化
- tradeoffs： 活动密度/自驾时长/最长单段/待核实项数量对比
"""

from .common import _leading_number, normalize_mode
from .stats import guide_stats
from .validator import validate_guide


def _summary(guide):
    """元信息摘要 + 校验问题计数（对比标题/天数/问题规模变化）。"""
    report = validate_guide(guide)
    meta = guide.get("meta", {})
    return {
        "title": meta.get("title"),
        "destination": meta.get("destination"),
        "days": meta.get("days"),
        "travelers": meta.get("travelers"),
        "errors": len(report["errors"]),
        "warnings": len(report["warnings"]),
        "conflicts": len(report["conflicts"]),
    }


def _daily(guide):
    """逐日摘要：天序号/日期/标题/行程项数量。"""
    return [
        {"day": day.get("day"), "date": day.get("date"), "title": day.get("title"), "items": len(day.get("items", []) or [])}
        for day in guide.get("days", [])
        if isinstance(day, dict)
    ]


def _stops(guide):
    """总体路线停靠点名称序列。"""
    route = guide.get("route", {}) or {}
    return [stop.get("name") for stop in route.get("stops", []) if isinstance(stop, dict)]


def _budgets(guide):
    """各预算方案的合计总额（原文，可为区间字符串）。"""
    budget = guide.get("budget", {}) or {}
    profiles = budget.get("profiles", {}) if isinstance(budget.get("profiles"), dict) else {}
    return {name: (profile or {}).get("total") for name, profile in profiles.items()}


def _day_semantics(guide):
    """按天归组行程项：{天序号: {名称: {start, end}}}；day 缺失按序号补。"""
    result = {}
    for day in guide.get("days", []) if isinstance(guide.get("days"), list) else []:
        if not isinstance(day, dict):
            continue
        items = {}
        for item in day.get("items", []) or []:
            if isinstance(item, dict) and item.get("name"):
                items[item["name"]] = {"start": item.get("start"), "end": item.get("end")}
        result[day.get("day", len(result) + 1)] = items
    return result


def _semantic_days(left, right):
    """逐日语义 diff：removed/added/time_changes（仅记录有变化的天）。

    天序号排序时 None 排最后，保证混合类型可排序。
    """
    left_days, right_days = _day_semantics(left), _day_semantics(right)
    day_changes = []
    for day_number in sorted(set(left_days) | set(right_days), key=lambda value: (value is None, value)):
        left_items, right_items = left_days.get(day_number, {}), right_days.get(day_number, {})
        removed = sorted(name for name in left_items if name not in right_items)
        added = sorted(name for name in right_items if name not in left_items)
        time_changes = []
        # 两边同名项比较 start/end 元组
        for name in sorted(set(left_items) & set(right_items)):
            if left_items[name] != right_items[name]:
                time_changes.append({"name": name, "left": left_items[name], "right": right_items[name]})
        if removed or added or time_changes:
            day_changes.append({"day": day_number, "removed": removed, "added": added, "time_changes": time_changes})
    return day_changes


def _semantic_route(left, right):
    """路线段语义 diff：以 (from, to) 为键比较时长/方式的增删改。"""
    def _legs(guide):
        route = guide.get("route", {}) or {}
        legs = []
        for leg in route.get("legs", []) if isinstance(route.get("legs"), list) else []:
            if isinstance(leg, dict) and leg.get("from") and leg.get("to"):
                legs.append({"from": leg.get("from"), "to": leg.get("to"), "duration_min": leg.get("duration_min"), "mode": leg.get("mode")})
        return legs

    def _key(leg):
        return (leg["from"], leg["to"])

    left_legs, right_legs = _legs(left), _legs(right)
    left_map = {_key(leg): leg for leg in left_legs}
    right_map = {_key(leg): leg for leg in right_legs}
    changes = []
    for key in sorted(set(left_map) | set(right_map)):
        left_leg, right_leg = left_map.get(key), right_map.get(key)
        if left_leg is None:
            changes.append({"leg": list(key), "change": "added", "duration_min": right_leg.get("duration_min")})
        elif right_leg is None:
            changes.append({"leg": list(key), "change": "removed", "duration_min": left_leg.get("duration_min")})
        elif left_leg.get("duration_min") != right_leg.get("duration_min") or left_leg.get("mode") != right_leg.get("mode"):
            changes.append({
                "leg": list(key),
                "change": "modified",
                "duration_min": {"left": left_leg.get("duration_min"), "right": right_leg.get("duration_min")},
                "mode": {"left": left_leg.get("mode"), "right": right_leg.get("mode")},
            })
    return changes


def _semantic_budget(left, right):
    """预算语义 diff：数值化前后比较，输出原文与差值（单边缺失按 0 计差）。"""
    changes = {}
    for name in set(_budgets(left)) | set(_budgets(right)):
        left_value, right_value = _leading_number(_budgets(left).get(name)), _leading_number(_budgets(right).get(name))
        if left_value != right_value and (left_value is not None or right_value is not None):
            changes[name] = {"left": _budgets(left).get(name), "right": _budgets(right).get(name), "delta": (right_value or 0) - (left_value or 0)}
    return changes


def _tradeoff_notes(left, right):
    """取舍评估：两版攻略的活动密度、自驾负担与待核实规模对比。"""
    notes = []
    left_stats, right_stats = guide_stats(left), guide_stats(right)
    item_delta = right_stats["totals"]["items"] - left_stats["totals"]["items"]
    if item_delta:
        notes.append("活动项 {} → {}（{:+d}，右侧{}）".format(
            left_stats["totals"]["items"], right_stats["totals"]["items"], item_delta,
            "更紧凑" if item_delta > 0 else "更宽松"))
    drive_delta = right_stats["totals"]["drive_minutes"] - left_stats["totals"]["drive_minutes"]
    if drive_delta:
        notes.append("日程自驾时长 {} → {} 分钟（{:+d}）".format(
            left_stats["totals"]["drive_minutes"], right_stats["totals"]["drive_minutes"], drive_delta))
    if left_stats["longest_leg"] or right_stats["longest_leg"]:
        left_longest = left_stats["longest_leg"] or {}
        right_longest = right_stats["longest_leg"] or {}
        if left_longest.get("duration_min") != right_longest.get("duration_min"):
            notes.append("最长单段 {} → {} 分钟".format(
                left_longest.get("duration_min"), right_longest.get("duration_min")))
    # 待核实项数量变化：变多说明新版本引入了更多不确定信息
    left_report, right_report = validate_guide(left), validate_guide(right)
    left_open = len(left_report["warnings"]) + len(left_report["conflicts"])
    right_open = len(right_report["warnings"]) + len(right_report["conflicts"])
    if left_open != right_open:
        notes.append("待核实/冲突项 {} → {}".format(left_open, right_open))
    return notes


def compare_guides(left, right):
    """对比两份攻略，返回 {differences, semantic, tradeoffs}。"""
    differences = {}
    for field, extractor in (("meta", _summary), ("days", _daily), ("stops", _stops), ("budget_totals", _budgets)):
        left_value, right_value = extractor(left), extractor(right)
        if left_value != right_value:
            differences[field] = {"left": left_value, "right": right_value}
    semantic = {"days": _semantic_days(left, right), "route_legs": _semantic_route(left, right), "budgets": _semantic_budget(left, right)}
    # 空的语义类别整体剔除，保持输出紧凑
    semantic = {key: value for key, value in semantic.items() if value}
    return {"differences": differences, "semantic": semantic, "tradeoffs": _tradeoff_notes(left, right)}
