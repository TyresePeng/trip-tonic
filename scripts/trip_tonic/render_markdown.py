"""Markdown 渲染器：双语正文、总体路线、统计、备选方案、媒体链接。

输出为纯 Markdown 文本（LF 换行）。所有用户可见文案走 tr()，
zh 为源语言，meta.language 以 "en" 开头时全文切换英文。
"""

from .common import _is_drive
from .stats import guide_stats, human_minutes
from .strings import tr
from .validator import validate_guide


def _backup_lines(guide, entries, indent):
    """把备选项（字符串或 {condition, plan} 对象）渲染为列表行。"""
    lines = []
    for entry in entries if isinstance(entries, list) else []:
        if isinstance(entry, str):
            lines.append(tr(guide, "backup_line").format(indent, entry))
        elif isinstance(entry, dict):
            condition = tr(guide, "condition_parens").format(entry["condition"]) if entry.get("condition") else ""
            lines.append(tr(guide, "backup_cond_line").format(indent, condition, entry.get("plan", "")))
    return lines


def _media_lines(guide, media_resolved=None):
    """Markdown 媒体列表：链接卡片 + 已缓存视频的本地路径链接。

    图片缓存只在 HTML 里内嵌（MD 内嵌 data URI 过于臃肿），
    视频给出产物目录 media/ 下的相对链接，MD 阅读器可直接播放。
    """
    lines = []
    resolved_map = media_resolved or {}
    for source in guide.get("sources", []):
        if not isinstance(source, dict) or not isinstance(source.get("media"), list):
            continue
        source_title = source.get("title", source.get("id", "source"))
        source_url = source.get("url")
        for entry in source["media"]:
            if not isinstance(entry, dict) or not entry.get("url"):
                continue
            media_url = str(entry["url"])
            kind = tr(guide, "media_type_video") if entry.get("type") == "video" else tr(guide, "media_type_image")
            # 无描述时回退到来源标题，保证链接始终有上下文
            description = entry.get("description") or source_title
            lines.append(tr(guide, "media_line_md").format(kind, description, tr(guide, "media_open_link"), media_url))
            source_ref = "[{}]({})".format(source_title, source_url) if source_url else source_title
            lines.append(tr(guide, "media_from_md").format(tr(guide, "media_source_note").format(source_ref)))
            local = resolved_map.get(media_url)
            if local and local.get("kind") == "video":
                lines.append(tr(guide, "media_local_md").format(local["src"]))
    return lines


def _stats_lines(guide):
    """行程统计小节：总量指标 + 节奏评估（与 HTML 版同源）。"""
    stats = guide_stats(guide)
    totals = stats["totals"]
    lines = []
    drive = human_minutes(guide, totals["drive_minutes"]) or tr(guide, "stats_none")
    drive_km = tr(guide, "stats_km").format(round(totals["drive_km"], 1)) if totals["drive_km"] else tr(guide, "stats_none")
    longest = tr(guide, "stats_none")
    if stats.get("longest_leg"):
        leg = stats["longest_leg"]
        longest = "{} → {} · {}".format(leg.get("from"), leg.get("to"), human_minutes(guide, leg["duration_min"]) or tr(guide, "duration_unverified"))
    avg_span = human_minutes(guide, totals["avg_span"]) or tr(guide, "stats_none")
    if stats["pace"] == "ok":
        pace_text = tr(guide, "stats_pace_ok").format(stats["pace_name"])
    elif stats["pace"] == "over":
        pace_text = tr(guide, "stats_pace_over").format(stats["pace_name"])
    else:
        pace_text = tr(guide, "stats_pace_unknown")
    pairs = [
        (tr(guide, "stats_days"), tr(guide, "stats_days_value").format(totals["days"])),
        (tr(guide, "stats_items"), tr(guide, "stats_items_value").format(totals["items"])),
        (tr(guide, "stats_meals"), str(totals["meals"])),
        (tr(guide, "stats_drive"), drive),
        (tr(guide, "stats_drive_km"), drive_km),
        (tr(guide, "stats_longest_leg"), longest),
        (tr(guide, "stats_avg_span"), avg_span),
    ]
    # 有媒体链接时追加计数行
    if totals["media"]:
        pairs.append((tr(guide, "stats_media"), str(totals["media"])))
    lines.extend(tr(guide, "stats_line").format(label, value) for label, value in pairs)
    lines.append("- " + tr(guide, "stats_pace").format(pace_text))
    return lines


def markdown_text(guide, report=None, media_resolved=None):
    """渲染完整 Markdown；report 可传入已有校验结果避免重复校验。

    media_resolved：{url: {kind, src}} 本地媒体映射；已缓存视频
    追加产物目录下的本地链接。
    """
    meta = guide.get("meta", {})
    lines = [
        "# " + str(meta.get("title", tr(guide, "title_fallback"))),
        "",
        "- " + tr(guide, "destination_label").format(meta.get("destination", "")),
        "- " + tr(guide, "dates_line").format(meta.get("start_date", "")),
        "- " + tr(guide, "travelers_line").format(meta.get("travelers", tr(guide, "not_specified"))),
        "",
    ]
    # 假设与待确认（meta.assumptions 与顶层 assumptions 合并展示）
    assumptions = meta.get("assumptions", []) + guide.get("assumptions", [])
    if assumptions:
        lines.extend(["## " + tr(guide, "assumptions"), ""] + ["- " + str(item) for item in assumptions] + [""])
    # ---- 总体路线：概览、停靠点顺序、逐段交通 ----
    route = guide.get("route", {}) or {}
    if route:
        lines.extend(["## " + tr(guide, "route"), "", route.get("overview") or tr(guide, "route_overview_fallback"), ""])
        stops = route.get("stops", [])
        if stops:
            lines.append(tr(guide, "route_order_line").format(" → ".join(stop.get("name", "") for stop in stops)))
            lines.append("")
        for index, leg in enumerate(route.get("legs", []), 1):
            # 时长优先 duration_text（诚实区间），其次数值，否则标注待核实
            duration = leg.get("duration_text") or (tr(guide, "minutes_short").format(leg["duration_min"]) if leg.get("duration_min") is not None else tr(guide, "duration_unverified"))
            distance = tr(guide, "km_short").format(leg["distance_km"]) if leg.get("distance_km") is not None else ""
            estimate = tr(guide, "estimate_note") if leg.get("estimated") else ""
            lines.append(tr(guide, "md_leg_line").format(index, leg.get("from", ""), leg.get("to", ""), leg.get("mode") or tr(guide, "mode_fallback"), tr(guide, "part_join") + duration, distance, estimate))
            if leg.get("notes"):
                lines.append(tr(guide, "md_leg_notes").format(leg["notes"]))
            lines.extend(tr(guide, "source_line").format(sid) for sid in leg.get("source_ids", []))
        lines.append("")
    # ---- 本地图片素材（用户提供或许可允许的本地文件） ----
    if guide.get("images"):
        lines.extend(["## " + tr(guide, "md_images"), ""])
        for image in guide["images"]:
            lines.append("![{}]({})".format(image.get("alt", image.get("title", "")), image.get("path", "")))
            if image.get("caption"):
                lines.append("*{}*".format(image["caption"]))
        lines.append("")
    # ---- 媒体与视频链接（研究采集的直链卡片） ----
    media_lines = _media_lines(guide, media_resolved)
    if media_lines:
        lines.extend(["## " + tr(guide, "h_media"), ""])
        lines.extend(media_lines)
        lines.append(tr(guide, "media_note_md"))
        lines.append("")
    # ---- 逐日行程 ----
    for day in guide.get("days", []):
        lines.extend(["## " + tr(guide, "day_heading").format(day.get("day", ""), day.get("title", ""), day.get("date", "")), ""])
        lines.extend(_backup_lines(guide, day.get("backup"), ""))
        for item in day.get("items", []):
            # 行程项或其接驳任一标注 estimated 即追加估算标记
            suffix = tr(guide, "estimated_tag") if item.get("estimated") or (item.get("route_from_previous") or {}).get("estimated") else ""
            description = tr(guide, "description_join") + item["description"] if item.get("description") else ""
            route = item.get("route_from_previous") or {}
            if route:
                transfer_duration = route.get("duration_text") or (tr(guide, "minutes_short").format(route["duration_min"]) if route.get("duration_min") is not None else tr(guide, "duration_unverified"))
                is_drive = _is_drive(route.get("mode"))
                # 自驾接驳缺里程时明确写"里程待核实"，而不是静默省略
                transfer_distance = tr(guide, "km_compact").format(route["distance_km"]) if route.get("distance_km") is not None else (tr(guide, "distance_unverified_compact") if is_drive else "")
                description += tr(guide, "transfer_md").format(route.get("mode") or tr(guide, "mode_fallback"), transfer_duration, transfer_distance)
            lines.append("- {}–{} **{}**{}{}".format(item.get("start", ""), item.get("end", ""), item.get("name", ""), description, suffix))
            for sid in item.get("source_ids", []):
                lines.append(tr(guide, "source_line").format(sid))
            lines.extend(_backup_lines(guide, item.get("backup"), "  "))
        lines.append("")
    # ---- 行程统计 ----
    lines.extend(["## " + tr(guide, "stats"), ""])
    lines.extend(_stats_lines(guide))
    lines.append("")
    # ---- 交通 / 住宿 / 美食 / 商家 / 避坑 / 预算 / 清单 / 提示 ----
    if guide.get("transport"):
        lines.extend(["## " + tr(guide, "transport"), ""])
        for record in guide["transport"]:
            price = tr(guide, "md_transport_price").format(record["price"]) if record.get("price") else ""
            lines.append(tr(guide, "md_transport_line").format(record.get("title", record.get("mode", tr(guide, "mode_fallback"))), record.get("detail", ""), price))
            lines.extend(tr(guide, "source_line").format(sid) for sid in record.get("source_ids", []))
        lines.append("")
    for title, key, fields in ((tr(guide, "hotels"), "hotels", ("name", "area", "reason", "price", "address", "hours")), (tr(guide, "md_foods"), "foods", ("name", "shop", "reason", "price"))):
        records = guide.get(key, [])
        if records:
            lines.extend(["## " + title, ""])
            for record in records:
                lines.append("- " + " · ".join(str(record[field]) for field in fields if record.get(field)))
                lines.extend(tr(guide, "source_line").format(sid) for sid in record.get("source_ids", []))
            lines.append("")
    if guide.get("businesses"):
        # 餐饮类商家并入美食推荐语境，其余单列
        food_businesses = [business for business in guide["businesses"] if _is_food_category(business.get("category"))]
        other_businesses = [business for business in guide["businesses"] if business not in food_businesses]
        for title, businesses in ((tr(guide, "food_businesses"), food_businesses), (tr(guide, "other_businesses"), other_businesses)):
            if not businesses:
                continue
            lines.extend(["## " + title, ""])
            for business in businesses:
                detail = " · ".join(str(business[field]) for field in ("category", "address", "hours", "price", "phone") if business.get(field))
                reason = tr(guide, "md_reason_join").format(business["reason"]) if business.get("reason") else ""
                lines.append("- **{}**（{}）{}".format(business.get("name", ""), detail, reason))
                if business.get("checked_at"):
                    lines.append(tr(guide, "checked_confidence_line").format(business["checked_at"], business.get("confidence", tr(guide, "not_specified"))))
                lines.extend(tr(guide, "source_line").format(sid) for sid in business.get("source_ids", []))
            lines.append("")
    if guide.get("avoid"):
        lines.extend(["## " + tr(guide, "avoid"), ""])
        for record in guide["avoid"]:
            if isinstance(record, dict):
                # 兼容 wrong/right（规范）与 name/reason（生成端常见）两种写法
                wrong = record.get("wrong") or record.get("name") or ""
                right = record.get("right") or record.get("reason") or ""
                lines.append(tr(guide, "avoid_line").format(wrong, right))
                lines.extend(tr(guide, "source_line").format(sid) for sid in record.get("source_ids", []))
            else:
                lines.append("- " + str(record))
        lines.append("")
    budget = guide.get("budget", {})
    if budget:
        lines.extend(["## " + tr(guide, "md_budget"), ""])
        for profile_name, profile in budget.get("profiles", {}).items():
            lines.append(tr(guide, "budget_md_line").format(profile_name, profile.get("total", tr(guide, "budget_pending"))))
            lines.extend(tr(guide, "budget_md_category").format(category, amount) for category, amount in profile.get("categories", {}).items())
        lines.append("")
    if guide.get("checklist"):
        # 复选框语法：- [ ] 标题（限日期）：细节
        lines.extend(["## " + tr(guide, "checklist"), ""])
        for entry in guide.get("checklist"):
            if not isinstance(entry, dict):
                continue
            date_part = tr(guide, "checklist_date_md").format(entry["date"]) if entry.get("date") else ""
            detail = tr(guide, "checklist_detail_join").format(entry["detail"]) if entry.get("detail") else ""
            lines.append("- [ ] {}{}{}".format(entry.get("title", ""), date_part, detail))
        lines.append("")
    if guide.get("tips"):
        lines.extend(["## " + tr(guide, "md_tips"), ""] + ["- " + str(tip) for tip in guide["tips"]] + [""])
    # ---- 待核实与警告（必须进产物，不能只在控制台提示） ----
    if report is None:
        report = validate_guide(guide)
    outstanding = report["warnings"] + report["conflicts"]
    if outstanding:
        lines.extend(["## " + tr(guide, "warnings"), ""])
        lines.extend(tr(guide, "warning_line_md").format(issue.get("code", "WARNING"), issue.get("message", "")) for issue in outstanding)
        lines.append("")
    # ---- 证据卡 ----
    if guide.get("evidence"):
        lines.extend(["## " + tr(guide, "evidence"), ""])
        for card in guide["evidence"]:
            if not isinstance(card, dict):
                continue
            claim = card.get("claim") or card.get("summary") or card.get("topic") or tr(guide, "evidence_fallback")
            lines.append("- **{}**".format(claim))
            for key, label in (("topic", "ev_topic"), ("summary", "ev_summary"), ("status", "ev_status"), ("caveat", "ev_caveat"), ("confidence", "ev_confidence"), ("checked_at", "ev_checked")):
                if card.get(key):
                    lines.append(tr(guide, "md_kv_line").format(tr(guide, label), card[key]))
            lines.extend(tr(guide, "source_line").format(sid) for sid in card.get("source_ids", []))
        lines.append("")
    # ---- 来源清单 ----
    lines.extend(["## " + tr(guide, "md_sources"), ""])
    for source in guide.get("sources", []):
        title, url = source.get("title", source.get("id", "source")), source.get("url")
        line = "- [{}]({})".format(title, url) if url else "- {}".format(title)
        lines.append("{}{}".format(line, tr(guide, "source_type_checked_md").format(source.get("type", "unknown"), source.get("checked_at", tr(guide, "not_specified")))))
    return "\n".join(lines).rstrip() + "\n"


def _is_food_category(category):
    """商家 category 是否属于餐饮类（中英文关键词模糊匹配）。"""
    text = str(category or "").lower()
    return any(word in text for word in ("餐", "美食", "咖啡", "小吃", "restaurant", "food", "cafe", "coffee", "snack"))
