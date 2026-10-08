"""行程统计：从 guide.json 计算诚实汇总数据，供渲染与构建结果使用。

规则：
- 自驾时长统计每日 route_from_previous 接驳缓冲；最长单段读 route.legs
- rest 类型不计入活动项；meal 单独计数
- 所有数字都来自有来源或显式标注估算的输入，统计层不发明新事实
"""

from .common import PACE_LIMITS, _leading_number, _minutes, normalize_mode
from .strings import tr

# 行程项 type -> i18n 标签键（图例/统计用）
_TYPE_LABEL_KEYS = {
    "spot": "t_spot",
    "meal": "t_meal",
    "transport": "t_transport",
    "hotel": "t_hotel",
    "activity": "t_activity",
    "rest": "t_rest",
}


def type_label(guide, item_type):
    """行程项类型的本地化标签（未知类型按活动处理）。"""
    key = _TYPE_LABEL_KEYS.get(item_type or "", "t_activity")
    return tr(guide, key)


def guide_stats(guide):
    """计算总体统计：totals 汇总、days 逐日、最长单段与节奏评估。

    返回结构：
    - totals: days/items/meals/drive_minutes/drive_km/avg_span/media
    - days:   每天的活动数、餐食数、时间跨度、空闲分钟、自驾量
    - longest_leg: route.legs 中 duration_min 最大的一段
    - pace:   ok / over / unknown（与 preferences.pace 上限比较）
    """
    days = []
    totals = {"days": 0, "items": 0, "meals": 0, "drive_minutes": 0, "drive_km": 0.0, "avg_span": 0, "media": 0}
    valid_days = guide.get("days") if isinstance(guide.get("days"), list) else []
    span_values = []
    for day in valid_days:
        if not isinstance(day, dict):
            continue
        totals["days"] += 1
        items = [item for item in (day.get("items") or []) if isinstance(item, dict)]
        # 当日时间跨度：首项开始到末项结束（用于节奏与 avg_span）
        windows = [(_minutes(item.get("start")), _minutes(item.get("end"))) for item in items]
        windows = [(start_value, end_value) for start_value, end_value in windows if start_value is not None and end_value is not None]
        span = (max(end for _, end in windows) - min(start for start, _ in windows)) if windows else 0
        span_values.append(span)
        day_drive_minutes, day_drive_km = 0, 0.0
        # 空闲分钟：相邻行程项之间的间隙（不代表实际自由时间，仅统计口径）
        idle_minutes = 0
        previous_end = None
        item_count, meal_count = 0, 0
        for item in items:
            # 自驾接驳先经同义词归一（"自驾"/"开车" 等都算 drive）
            route = item.get("route_from_previous") if isinstance(item.get("route_from_previous"), dict) else {}
            if normalize_mode(route.get("mode")) == "drive":
                duration = route.get("duration_min")
                if isinstance(duration, int) and not isinstance(duration, bool):
                    day_drive_minutes += duration
                distance = route.get("distance_km")
                if isinstance(distance, (int, float)) and not isinstance(distance, bool):
                    day_drive_km += float(distance)
            start, end = _minutes(item.get("start")), _minutes(item.get("end"))
            if previous_end is not None and start is not None and start > previous_end:
                idle_minutes += start - previous_end
            if end is not None:
                previous_end = end if previous_end is None else max(previous_end, end)
            # rest 不占活动预算，meal 单独计数
            if item.get("type") != "rest":
                item_count += 1
            if item.get("type") == "meal":
                meal_count += 1
        totals["items"] += item_count
        totals["meals"] += meal_count
        totals["drive_minutes"] += day_drive_minutes
        totals["drive_km"] += day_drive_km
        days.append({
            "day": day.get("day"),
            "date": day.get("date"),
            "items": item_count,
            "meals": meal_count,
            "span": span,
            "idle": idle_minutes,
            "drive_minutes": day_drive_minutes,
            "drive_km": day_drive_km,
        })
    if span_values:
        totals["avg_span"] = round(sum(span_values) / len(span_values))

    # 最长单段：仅统计 route.legs 里的整数分钟（市内接驳不参与）
    longest_leg = None
    route = guide.get("route") if isinstance(guide.get("route"), dict) else {}
    for leg in route.get("legs", []) if isinstance(route.get("legs"), list) else []:
        if not isinstance(leg, dict):
            continue
        duration = leg.get("duration_min")
        if isinstance(duration, int) and not isinstance(duration, bool) and (longest_leg is None or duration > longest_leg["duration_min"]):
            longest_leg = {"from": leg.get("from"), "to": leg.get("to"), "duration_min": duration}

    # 媒体链接数：sources[].media 中带 url 的条目（供统计行显示）
    sources = guide.get("sources") if isinstance(guide.get("sources"), list) else []
    totals["media"] = sum(
        1
        for source in sources
        if isinstance(source, dict) and isinstance(source.get("media"), list)
        for entry in source["media"]
        if isinstance(entry, dict) and entry.get("url")
    )

    # 节奏评估：任一天超上限即 over；未设置偏好为 unknown
    pace = (guide.get("preferences") or {}).get("pace") if isinstance(guide.get("preferences"), dict) else None
    pace_status = "unknown"
    if pace in PACE_LIMITS and days:
        pace_span, pace_items = PACE_LIMITS[pace]
        overloaded = any(day["span"] > pace_span or day["items"] > pace_items for day in days)
        pace_status = "over" if overloaded else "ok"

    return {"totals": totals, "days": days, "longest_leg": longest_leg, "pace": pace_status, "pace_name": pace if pace in PACE_LIMITS else None}


def human_minutes(guide, minutes):
    """分钟数转人类可读文本（"45 分钟" / "2 小时 15 分"）；无效或非正数返回 None。"""
    if not isinstance(minutes, (int, float)) or isinstance(minutes, bool) or minutes <= 0:
        return None
    minutes = int(round(minutes))
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return tr(guide, "ics_minutes").format(minutes)
    return tr(guide, "stats_hours").format(hours, rest)


def budget_pie_data(guide):
    """预算饼图数据：按 profile 返回 [(分类, 数值, 占比)]。

    只有当 profile 的全部分类都能解析出数字时才产出（否则该 profile
    不画饼图），避免用半吊子数据画出误导性比例。
    """
    budget = guide.get("budget") if isinstance(guide.get("budget"), dict) else {}
    profiles = budget.get("profiles") if isinstance(budget.get("profiles"), dict) else {}
    result = {}
    for profile_name, profile in profiles.items():
        if not isinstance(profile, dict):
            continue
        categories = profile.get("categories") if isinstance(profile.get("categories"), dict) else {}
        entries = []
        for category, amount in categories.items():
            value = _leading_number(amount)
            if value is None:
                # 任一分项无法数值化即放弃该 profile 的饼图
                entries = None
                break
            entries.append((category, value))
        if not entries:
            continue
        total = sum(value for _, value in entries)
        if total <= 0:
            continue
        result[profile_name] = [(category, value, value / total) for category, value in entries]
    return result
