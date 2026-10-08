"""ICS 日历导出：浮动本地时间、DTSTAMP、交通提醒、清单全天事件。

规范要点：
- 行程时间用浮动本地时间（无 TZID）：符合 RFC 5545，且避免
  输出没有配套 VTIMEZONE 定义的 TZID；X-WR-TIMEZONE 仅作提示
- 长行按 UTF-8 字节数折叠（<=75 字节，续行以空格开头）
- transport 类型行程项带 30 分钟提醒（VALARM）
- checklist 带 date 的项导出为透明全天事件
"""

from datetime import datetime, timedelta, timezone

from .common import _coordinate_error, _source_map, _valid_date
from .strings import tr


def _ics_escape(value):
    """ICS 文本转义：反斜杠/分号/逗号/换行。"""
    return str(value).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def ics_text(guide, now=None):
    """渲染完整 ICS；now 可注入（测试确定 DTSTAMP）。"""
    if now is None:
        now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    meta = guide.get("meta", {})
    timezone_name = meta.get("timezone", "Asia/Shanghai")
    sources = _source_map(guide)
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//TripTonic//Travel Guide//CN", "CALSCALE:GREGORIAN", "X-WR-TIMEZONE:{}".format(_ics_escape(timezone_name))]
    # ---- 行程项事件 ----
    for day in guide.get("days", []):
        daystamp = str(day.get("date", "")).replace("-", "")
        for index, item in enumerate(day.get("items", [])):
            start = str(item.get("start", "00:00")).replace(":", "") + "00"
            end = str(item.get("end", "00:00")).replace(":", "") + "00"
            # UID 由日期+天序号+项序号组成，保证稳定可重复导入
            uid = "trip-tonic-{}-{}-{}@local".format(daystamp, day.get("day", ""), index)
            # 浮动本地时间符合 RFC 且避免输出无 VTIMEZONE 配套的 TZID；
            # X-WR-TIMEZONE 只是给客户端的时区提示
            event = [
                "BEGIN:VEVENT",
                "UID:" + uid,
                "DTSTAMP:" + stamp,
                "DTSTART:{}T{}".format(daystamp, start),
                "DTEND:{}T{}".format(daystamp, end),
                "SUMMARY:" + _ics_escape(item.get("name", tr(guide, "ics_item"))),
            ]
            # GEO 字段：纬度在前、经度在后（guide 内部是 [经度, 纬度]）
            coords = item.get("coords")
            if isinstance(coords, list) and len(coords) == 2 and not _coordinate_error(coords):
                event.append("GEO:{:.5f};{:.5f}".format(coords[1], coords[0]))
            if item.get("type") in ("spot", "meal", "activity", "hotel", "rest"):
                event.append("LOCATION:" + _ics_escape(item.get("name", "")))
            # 描述：正文 + 接驳信息 + 来源标题（多段换行拼接）
            description_parts = []
            if item.get("description"):
                description_parts.append(str(item["description"]))
            route = item.get("route_from_previous") or {}
            if isinstance(route, dict) and (route.get("mode") or route.get("duration_min") is not None or route.get("duration_text")):
                duration = route.get("duration_text") or (tr(guide, "ics_minutes").format(route.get("duration_min")) if route.get("duration_min") is not None else tr(guide, "duration_unverified"))
                description_parts.append(tr(guide, "ics_transfer").format(route.get("mode") or tr(guide, "mode_fallback"), duration))
            if isinstance(item.get("source_ids"), list) and item["source_ids"]:
                titles = "、".join(str(sources.get(sid, {}).get("title", sid)) for sid in item["source_ids"] if isinstance(sid, str))
                if titles:
                    description_parts.append(tr(guide, "ics_sources").format(titles))
            if description_parts:
                event.append("DESCRIPTION:" + _ics_escape("\n".join(description_parts)))
            # 交通项提前 30 分钟提醒
            if item.get("type") == "transport":
                event.extend(["BEGIN:VALARM", "TRIGGER:-PT30M", "ACTION:DISPLAY", "DESCRIPTION:" + _ics_escape(tr(guide, "ics_alarm")), "END:VALARM"])
            event.append("END:VEVENT")
            lines.extend(event)
    # ---- 清单全天事件：仅导出带合法 date 的项 ----
    checklist = guide.get("checklist")
    for index, entry in enumerate(checklist if isinstance(checklist, list) else []):
        if not isinstance(entry, dict) or not entry.get("title"):
            continue
        checked_day = _valid_date(entry.get("date"))
        if not checked_day:
            continue
        daystamp = checked_day.strftime("%Y%m%d")
        # DTEND 为次日（全天事件按开区间约定）
        next_daystamp = (checked_day + timedelta(days=1)).strftime("%Y%m%d")
        event = [
            "BEGIN:VEVENT",
            "UID:trip-tonic-checklist-{}-{}@local".format(daystamp, index),
            "DTSTAMP:" + stamp,
            "DTSTART;VALUE=DATE:" + daystamp,
            "DTEND;VALUE=DATE:" + next_daystamp,
            "SUMMARY:" + _ics_escape(tr(guide, "ics_checklist").format(str(entry["title"]))),
            "TRANSP:TRANSPARENT",
        ]
        if entry.get("detail"):
            event.append("DESCRIPTION:" + _ics_escape(entry["detail"]))
        event.append("END:VEVENT")
        lines.extend(event)
    lines.append("END:VCALENDAR")
    # ---- 按 UTF-8 字节数折叠长行（RFC 5545：每行 <=75 八位组，续行以单个空格开头） ----
    folded = []
    for line in lines:
        current = ""
        current_bytes = 0
        for character in line:
            encoded_size = len(character.encode("utf-8"))
            if current_bytes + encoded_size > 75:
                folded.append(current)
                current, current_bytes = " ", 1
            current += character
            current_bytes += encoded_size
        folded.append(current)
    return "\r\n".join(folded) + "\r\n"
