"""结构化攻略校验器：输出确定性的错误、警告与行程冲突。

校验分三层：
1. JSON Schema 子集校验（字段类型/必填/枚举，见 schema.py）
2. 领域规则：来源引用、日期顺序、时间重叠、接驳缓冲、节奏强度、
   自驾疲劳、住宿连续性、预算一致性、媒体链接时效等
3. 行程冲突（conflicts）：时间重叠、接驳时间不够——这类问题会阻止构建

诊断分级约定：
- error  -> 结构错误，valid=false，build 拒绝执行
- warning-> 待核实/提醒，默认放行但渲染进产物，--strict 模式下拒绝
- conflict-> 行程内在矛盾，与 error 同等对待
"""

from datetime import timedelta

from .common import (
    CANONICAL_MODES,
    PACE_LIMITS,
    SOURCE_TYPES,
    _coordinate_error,
    _is_drive,
    _issue,
    _leading_number,
    _minutes,
    _valid_date,
    normalize_mode,
)
from .schema import SchemaCorruptError, _schema_issues, load_guide_schema

# MODE_UNRECOGNIZED 警告附带的修复建议文案
_MODE_HINT = "；建议使用规范值 {}".format("/".join(CANONICAL_MODES)) + " 或常用中文（自驾/步行/公交/地铁/火车/飞机/出租车/骑行/轮渡/缆车/班车）"


def validate_guide(guide, today=None):
    """校验 guide 结构；today 可注入基准日期（供测试时效规则/CLI --today）。"""
    from datetime import date

    today = today or date.today()
    errors, warnings, conflicts = [], [], []
    if not isinstance(guide, dict):
        return {"valid": False, "errors": [_issue("error", "ROOT", "根节点必须是对象", "$")], "warnings": [], "conflicts": []}

    # ---- 第 1 层：JSON Schema 子集校验 ----
    # schema 本身损坏是硬错误（SCHEMA_CORRUPT）；文件缺失时降级为仅内置校验
    try:
        schema = load_guide_schema()
        errors.extend(_schema_issues(guide, schema))
    except SchemaCorruptError as error:
        errors.append(_issue("error", "SCHEMA_CORRUPT", str(error), "references/guide-schema.json"))
    except OSError:
        warnings.append(_issue("warning", "SCHEMA_UNAVAILABLE", "未能加载 JSON Schema；仅执行内置业务校验", "references/guide-schema.json"))

    # ---- meta 与版本 ----
    if guide.get("schema_version") != "1.0":
        errors.append(_issue("error", "SCHEMA_VERSION", "schema_version 必须为 1.0", "schema_version"))
    meta = guide.get("meta")
    if not isinstance(meta, dict):
        errors.append(_issue("error", "META", "缺少 meta 对象", "meta"))
        meta = {}
    for field in ("title", "destination", "language", "start_date", "days"):
        if meta.get(field) in (None, ""):
            errors.append(_issue("error", "META_FIELD", "缺少字段 {}".format(field), "meta." + field))
    start_date = _valid_date(meta.get("start_date"))
    if meta.get("start_date") and not start_date:
        errors.append(_issue("error", "START_DATE", "开始日期格式应为 YYYY-MM-DD", "meta.start_date"))

    # ---- sources：来源白名单、去重、时效、媒体链接 ----
    sources = guide.get("sources")
    if not isinstance(sources, list):
        errors.append(_issue("error", "SOURCES", "sources 必须是数组", "sources"))
        sources = []
    source_ids = set()
    for index, source in enumerate(sources):
        path = "sources[{}]".format(index)
        if not isinstance(source, dict):
            errors.append(_issue("error", "SOURCE", "来源必须是对象", path))
            continue
        source_id = source.get("id")
        if not source_id:
            errors.append(_issue("error", "SOURCE_ID", "来源缺少 id", path))
        elif source_id in source_ids:
            errors.append(_issue("error", "SOURCE_DUPLICATE", "来源 id 重复", path))
        else:
            source_ids.add(source_id)
        if not source.get("title"):
            errors.append(_issue("error", "SOURCE_TITLE", "来源缺少 title", path))
        if source.get("type") not in SOURCE_TYPES:
            errors.append(_issue("error", "SOURCE_TYPE", "来源 type 无效", path))
        checked = _valid_date(source.get("checked_at"))
        if not checked:
            errors.append(_issue("error", "SOURCE_DATE", "checked_at 必须为 YYYY-MM-DD", path))
        elif (today - checked).days > 180:
            warnings.append(_issue("warning", "SOURCE_STALE", "来源核实日期超过 180 天", path))
        url = source.get("url")
        if url and not str(url).startswith(("https://", "http://")):
            errors.append(_issue("error", "SOURCE_URL", "来源 URL 必须使用 HTTP(S)", path))
        # 媒体链接（图片/视频）：只校验结构与协议，签名链接过期风险单列 MEDIA_STALE
        media = source.get("media")
        if media is not None:
            if not isinstance(media, list):
                errors.append(_issue("error", "MEDIA_INVALID", "media 必须是数组", path + ".media"))
            elif media:
                for media_index, entry in enumerate(media):
                    media_path = "{}.media[{}]".format(path, media_index)
                    if not isinstance(entry, dict):
                        errors.append(_issue("error", "MEDIA_INVALID", "媒体条目必须是对象", media_path))
                        continue
                    if entry.get("type") not in ("image", "video"):
                        errors.append(_issue("error", "MEDIA_TYPE", "媒体 type 必须为 image / video", media_path + ".type"))
                    media_url = entry.get("url")
                    if not media_url or not str(media_url).startswith(("https://", "http://")):
                        errors.append(_issue("error", "MEDIA_URL", "媒体 URL 必须使用 HTTP(S)", media_path + ".url"))
                # 小红书 CDN 签名链接寿命短：超过 14 天提醒重新核实
                if checked and (today - checked).days > 14:
                    warnings.append(_issue("warning", "MEDIA_STALE", "媒体链接来源核实日期超过 14 天，签名链接可能已过期", path))

    # ---- days：日期序列、时间窗口、接驳与节奏 ----
    days = guide.get("days")
    if not isinstance(days, list) or not days:
        errors.append(_issue("error", "DAYS", "days 必须是非空数组", "days"))
        days = []
    elif isinstance(meta.get("days"), int) and not isinstance(meta.get("days"), bool) and meta["days"] != len(days):
        errors.append(_issue("error", "DAY_COUNT", "meta.days 与 days 数量不一致", "days"))

    preferences = guide.get("preferences") if isinstance(guide.get("preferences"), dict) else {}
    earliest_start, latest_end_limit = _minutes(preferences.get("earliest_start")), _minutes(preferences.get("latest_end"))
    # 多日行程是否出现住宿信息（type=hotel 行程项或 hotels 记录）
    trip_has_lodging_item = False

    for day_index, day in enumerate(days):
        day_path = "days[{}]".format(day_index)
        if not isinstance(day, dict):
            errors.append(_issue("error", "DAY", "每日行程必须是对象", day_path))
            continue
        # 日期必须合法，且与 start_date + 天数序号一致（不一致为警告而非错误）
        day_date = _valid_date(day.get("date"))
        if not day_date:
            errors.append(_issue("error", "DAY_DATE", "日期格式应为 YYYY-MM-DD", day_path))
        elif start_date:
            try:
                expected_date = start_date + timedelta(days=day_index)
            except OverflowError:
                errors.append(_issue("error", "DAY_SEQUENCE", "行程日期超出支持范围", day_path))
            else:
                if day_date != expected_date:
                    warnings.append(_issue("warning", "DAY_SEQUENCE", "日期与开始日期/天数顺序不一致", day_path))
        if day.get("day") is not None and day.get("day") != day_index + 1:
            warnings.append(_issue("warning", "DAY_NUMBER", "day 编号应与行程序号一致", day_path + ".day"))
        items = day.get("items")
        if not isinstance(items, list) or not items:
            errors.append(_issue("error", "DAY_EMPTY", "每天至少需要一个行程项", day_path))
            continue
        # 非首日的首个行程项应说明住宿→首站接驳（DAY_START_TRANSFER_MISSING）
        first_item = items[0] if isinstance(items[0], dict) else None
        if day_index >= 1 and first_item and first_item.get("type") != "transport":
            first_route = first_item.get("route_from_previous")
            if not (isinstance(first_route, dict) and (first_route.get("mode") or first_route.get("duration_min") is not None)):
                warnings.append(_issue("warning", "DAY_START_TRANSFER_MISSING", "当日首个行程项缺少 route_from_previous（住宿→首站接驳）；即使是步行接驳也建议注明", day_path + ".items[0]"))
        # 日级 backup：每项必须是含 plan 的对象
        day_backup = day.get("backup")
        if day_backup is not None:
            if not isinstance(day_backup, list):
                errors.append(_issue("error", "BACKUP_TYPE", "backup 必须是数组", day_path + ".backup"))
            else:
                for backup_index, entry in enumerate(day_backup):
                    if isinstance(entry, dict) and entry.get("plan"):
                        continue
                    errors.append(_issue("error", "BACKUP_FIELD", "备选项必须是含 plan 的对象", "{}.backup[{}]".format(day_path, backup_index)))
        day_item_count, day_drive_minutes = 0, 0
        previous_end, previous_name = None, None
        for item_index, item in enumerate(items):
            path = "{}.items[{}]".format(day_path, item_index)
            if not isinstance(item, dict):
                errors.append(_issue("error", "ITEM", "行程项必须是对象", path))
                continue
            if not item.get("name"):
                errors.append(_issue("error", "ITEM_NAME", "行程项缺少 name", path))
            # 坐标错误直接报错：错误坐标会污染 GeoJSON/KML 产物
            if "coords" in item:
                coordinate_error = _coordinate_error(item.get("coords"))
                if coordinate_error:
                    errors.append(_issue("error", "COORDINATES", coordinate_error, path + ".coords"))
            start, end = _minutes(item.get("start")), _minutes(item.get("end"))
            if start is None or end is None:
                errors.append(_issue("error", "ITEM_TIME", "时间格式必须为 HH:MM", path))
                continue
            if end <= start:
                errors.append(_issue("error", "ITEM_RANGE", "结束时间必须晚于开始时间", path))
            # 时间窗口（TIME_WINDOW）：与偏好最早出发/最晚结束比较
            if earliest_start is not None and start < earliest_start:
                warnings.append(_issue("warning", "TIME_WINDOW", "行程开始时间 {} 早于偏好最早出发时间 {}".format(item.get("start"), preferences.get("earliest_start")), path))
            if latest_end_limit is not None and end > latest_end_limit:
                warnings.append(_issue("warning", "TIME_WINDOW", "行程结束时间 {} 晚于偏好最晚结束时间 {}".format(item.get("end"), preferences.get("latest_end")), path))
            # 行程项级 backup 校验，规则同日级
            item_backup = item.get("backup")
            if item_backup is not None:
                if not isinstance(item_backup, list):
                    errors.append(_issue("error", "BACKUP_TYPE", "backup 必须是数组", path + ".backup"))
                else:
                    for backup_index, entry in enumerate(item_backup):
                        if isinstance(entry, dict) and entry.get("plan"):
                            continue
                        errors.append(_issue("error", "BACKUP_FIELD", "备选项必须是含 plan 的对象", "{}.backup[{}]".format(path, backup_index)))
            # 时间重叠是冲突（阻止构建）
            if previous_end is not None and start < previous_end:
                conflicts.append(_issue("conflict", "TIME_OVERLAP", "{} 与 {} 时间重叠".format(previous_name, item.get("name", "未命名")), path))
            route = item.get("route_from_previous") or {}
            if not isinstance(route, dict):
                errors.append(_issue("error", "ITEM_ROUTE", "route_from_previous 必须是对象", path + ".route_from_previous"))
                route = {}
            elif route.get("mode") and normalize_mode(route.get("mode")) is None:
                warnings.append(_issue("warning", "MODE_UNRECOGNIZED", "接驳方式 \"{}\" 未被识别{}".format(route.get("mode"), _MODE_HINT), path + ".route_from_previous.mode"))
            # 接驳缓冲：声明的交通时长超过可用间隔 -> 冲突（TRANSIT_TOO_SHORT）
            if previous_end is not None and route.get("duration_min") is not None:
                try:
                    transfer = int(route["duration_min"])
                except (ValueError, TypeError):
                    errors.append(_issue("error", "ROUTE_DURATION", "交通时长必须为整数分钟", path))
                else:
                    if transfer > max(0, start - previous_end):
                        conflicts.append(_issue("conflict", "TRANSIT_TOO_SHORT", "交通约需 {} 分钟，但可用间隔为 {} 分钟".format(transfer, max(0, start - previous_end)), path))
            # 自驾接驳：缺时长/里程出警告（诚实标记"待核实"而非编造）
            if _is_drive(route.get("mode")):
                if route.get("duration_min") is None and not route.get("duration_text"):
                    warnings.append(_issue("warning", "DRIVE_DURATION_MISSING", "日程自驾接驳缺少时长或待核实说明", path))
                if route.get("distance_km") is None:
                    warnings.append(_issue("warning", "DRIVE_DISTANCE_MISSING", "日程自驾接驳缺少里程或待核实说明", path))
                leg_minutes = route.get("duration_min")
                if isinstance(leg_minutes, int) and not isinstance(leg_minutes, bool):
                    day_drive_minutes += leg_minutes
                    if leg_minutes > 240:
                        warnings.append(_issue("warning", "DRIVE_FATIGUE", "单段自驾约 {} 分钟，超过连续驾驶建议上限，应安排中途休息".format(leg_minutes), path))
            if item.get("type") == "hotel":
                trip_has_lodging_item = True
            # rest 类型不计入节奏统计（休息不占活动预算）
            if item.get("type") != "rest":
                day_item_count += 1
            for source_id in item.get("source_ids", []) if isinstance(item.get("source_ids", []), list) else []:
                if source_id not in source_ids:
                    warnings.append(_issue("warning", "SOURCE_MISSING", "引用不存在的来源 {}".format(source_id), path))
            previous_end, previous_name = max(previous_end or 0, end), item.get("name", "未命名")
        # 全天自驾合计超 6 小时 -> 疲劳警告
        if day_drive_minutes > 360:
            warnings.append(_issue("warning", "DRIVE_FATIGUE", "当日自驾合计约 {} 分钟，长途驾驶应轮换驾驶或拆分行程".format(day_drive_minutes), day_path))
        # 节奏强度（PACE_OVERLOAD）：按偏好上限比较当日时间跨度与活动项数
        windows = [(_minutes(entry.get("start")), _minutes(entry.get("end"))) for entry in items if isinstance(entry, dict)]
        windows = [(start_value, end_value) for start_value, end_value in windows if start_value is not None and end_value is not None]
        pace = preferences.get("pace")
        if pace in PACE_LIMITS and windows:
            span = max(end_value for _, end_value in windows) - min(start_value for start_value, _ in windows)
            pace_span, pace_items = PACE_LIMITS[pace]
            if span > pace_span or day_item_count > pace_items:
                warnings.append(_issue("warning", "PACE_OVERLOAD", "节奏偏好为 {}，当日时间跨度 {} 分钟、活动项 {} 个，超过建议上限（{} 分钟 / {} 项）".format(pace, span, day_item_count, pace_span, pace_items), day_path))

    # 多日行程住宿连续性（LODGING_PLAN_MISSING）：hotel 行程项或 hotels.days/date 均可
    hotels_records = guide.get("hotels")
    hotels_cover_days = isinstance(hotels_records, list) and any(
        isinstance(record, dict) and (record.get("days") or record.get("date") or record.get("nights"))
        for record in hotels_records
    )
    if len(days) >= 2 and not trip_has_lodging_item and not hotels_cover_days:
        warnings.append(_issue("warning", "LODGING_PLAN_MISSING", "多日行程未标注每晚住宿；可用 type=hotel 的行程项或 hotels 记录的 days/date 字段覆盖（夜间交通当日可忽略）", "days"))

    # ---- 各推荐集合：结构、来源引用、30 天时效 ----
    for collection in ("transport", "hotels", "foods", "avoid"):
        records = guide.get(collection, []) or []
        if not isinstance(records, list):
            errors.append(_issue("error", "COLLECTION", "{} 必须是数组".format(collection), collection))
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(_issue("error", "RECORD", "记录必须是对象", "{}[{}]".format(collection, index)))
                continue
            # 避坑条目必须有可渲染内容：wrong/right（规范写法）或 name/reason
            # （生成端常见写法）二选一，否则产物中只剩来源链接
            if collection == "avoid" and not ((record.get("wrong") and record.get("right")) or (record.get("name") and record.get("reason"))):
                warnings.append(_issue("warning", "AVOID_STRUCTURE", "避坑条目缺少 wrong/right 或 name/reason 字段，产物中无法展示避坑内容", "{}[{}]".format(collection, index)))
            for source_id in record.get("source_ids", []) if isinstance(record.get("source_ids", []), list) else []:
                if source_id not in source_ids:
                    warnings.append(_issue("warning", "SOURCE_MISSING", "引用不存在的来源 {}".format(source_id), "{}[{}]".format(collection, index)))
            # 住宿/餐饮核实超 30 天：价格与营业情况易变，提醒复核
            if collection in ("hotels", "foods") and record.get("checked_at"):
                checked = _valid_date(record["checked_at"])
                if checked and (today - checked).days > 30:
                    code = "LODGING_STALE" if collection == "hotels" else "FOOD_STALE"
                    label = "住宿" if collection == "hotels" else "餐饮"
                    warnings.append(_issue("warning", code, "{}信息核实超过30天，应重新确认价格、营业与可用情况".format(label), "{}[{}]".format(collection, index)))

    for collection in ("businesses", "images"):
        records = guide.get(collection, []) or []
        if not isinstance(records, list):
            errors.append(_issue("error", "COLLECTION", "{} 必须是数组".format(collection), collection))
            continue
        for index, record in enumerate(records):
            if not isinstance(record, dict):
                errors.append(_issue("error", "RECORD", "记录必须是对象", "{}[{}]".format(collection, index)))
                continue
            for source_id in record.get("source_ids", []) if isinstance(record.get("source_ids", []), list) else []:
                if source_id not in source_ids:
                    warnings.append(_issue("warning", "SOURCE_MISSING", "引用不存在的来源 {}".format(source_id), "{}[{}]".format(collection, index)))
            if collection == "businesses" and record.get("checked_at"):
                checked = _valid_date(record["checked_at"])
                if checked and (today - checked).days > 30:
                    warnings.append(_issue("warning", "BUSINESS_STALE", "商家信息核实超过30天，应重新确认营业、地址和价格", "businesses[{}]".format(index)))

    # ---- 总体路线：停靠点、逐段交通 ----
    route = guide.get("route", {}) or {}
    if not isinstance(route, dict):
        errors.append(_issue("error", "ROUTE", "route 必须是对象", "route"))
        route = {}
    stops = route.get("stops", []) or []
    legs = route.get("legs", []) or []
    if not isinstance(stops, list):
        errors.append(_issue("error", "ROUTE_STOPS", "route.stops 必须是数组", "route.stops"))
        stops = []
    if not isinstance(legs, list):
        errors.append(_issue("error", "ROUTE_LEGS", "route.legs 必须是数组", "route.legs"))
        legs = []
    for index, stop in enumerate(stops):
        if not isinstance(stop, dict):
            errors.append(_issue("error", "ROUTE_STOP", "路线停靠点必须是对象", "route.stops[{}]".format(index)))
            continue
        if "coords" in stop:
            coordinate_error = _coordinate_error(stop["coords"])
            if coordinate_error:
                errors.append(_issue("error", "COORDINATES", coordinate_error, "route.stops[{}].coords".format(index)))
        for source_id in stop.get("source_ids", []) if isinstance(stop.get("source_ids", []), list) else []:
            if source_id not in source_ids:
                warnings.append(_issue("warning", "SOURCE_MISSING", "引用不存在的来源 {}".format(source_id), "route.stops[{}]".format(index)))
    for index, leg in enumerate(legs):
        path = "route.legs[{}]".format(index)
        if not isinstance(leg, dict):
            errors.append(_issue("error", "ROUTE_LEG", "路线段必须是对象", path))
            continue
        if not leg.get("from") or not leg.get("to"):
            errors.append(_issue("error", "ROUTE_LEG", "路线段必须提供 from/to", path))
        if leg.get("duration_min") is not None and (not isinstance(leg["duration_min"], int) or leg["duration_min"] < 0):
            errors.append(_issue("error", "ROUTE_DURATION", "路线段 duration_min 必须是非负整数", path))
        if leg.get("duration_text") is not None and not isinstance(leg["duration_text"], str):
            errors.append(_issue("error", "ROUTE_DURATION", "路线段 duration_text 必须是字符串", path))
        if leg.get("mode") and normalize_mode(leg.get("mode")) is None:
            warnings.append(_issue("warning", "MODE_UNRECOGNIZED", "路线段交通方式 \"{}\" 未被识别{}".format(leg.get("mode"), _MODE_HINT), path + ".mode"))
        for source_id in leg.get("source_ids", []) if isinstance(leg.get("source_ids", []), list) else []:
            if source_id not in source_ids:
                warnings.append(_issue("warning", "SOURCE_MISSING", "引用不存在的来源 {}".format(source_id), path))
        # 城际自驾段：同样要求时长/里程，疲劳阈值比市内段更宽（300 分钟）
        if _is_drive(leg.get("mode")):
            if leg.get("duration_min") is None and not leg.get("duration_text"):
                warnings.append(_issue("warning", "DRIVE_DURATION_MISSING", "自驾路段缺少时长或待核实说明", path))
            if leg.get("distance_km") is None:
                warnings.append(_issue("warning", "DRIVE_DISTANCE_MISSING", "自驾路段缺少里程或待核实说明", path))
            leg_minutes = leg.get("duration_min")
            if isinstance(leg_minutes, int) and not isinstance(leg_minutes, bool) and leg_minutes > 300:
                warnings.append(_issue("warning", "DRIVE_FATIGUE", "城际自驾路段约 {} 分钟，超过长途连续驾驶建议，应安排中途休息或拆分".format(leg_minutes), path))
    # 段数通常 = 停靠点数 - 1
    if stops and legs and len(legs) != len(stops) - 1:
        warnings.append(_issue("warning", "ROUTE_LEG_COUNT", "路线段数量通常应为停靠点数量减一", "route.legs"))
    # 段起终点应与相邻停靠点顺序一致
    for index, leg in enumerate(legs):
        if not isinstance(leg, dict) or index + 1 >= len(stops):
            continue
        if isinstance(stops[index], dict) and isinstance(stops[index + 1], dict):
            expected_pair = (stops[index].get("name"), stops[index + 1].get("name"))
            actual_pair = (leg.get("from"), leg.get("to"))
            if all(expected_pair) and actual_pair != expected_pair:
                warnings.append(_issue("warning", "ROUTE_LEG_SEQUENCE", "路线段起终点与相邻停靠点顺序不一致", "route.legs[{}]".format(index)))

    # ---- 推荐完整性与证据链 ----
    for collection, label in (("hotels", "住宿"), ("foods", "餐饮"), ("businesses", "店铺/服务商")):
        if not guide.get(collection):
            warnings.append(_issue("warning", "RECOMMENDATIONS_MISSING", "缺少{}推荐；请补充有来源的推荐，或说明无法核实及原因".format(label), collection))
    foods = guide.get("foods")
    if isinstance(foods, list) and foods and all(record.get("shop") == "不指定商家" for record in foods if isinstance(record, dict)):
        warnings.append(_issue("warning", "FOOD_SHOP_MISSING", "餐饮目前只有品类建议，没有具体店铺候选", "foods"))
    hotels = guide.get("hotels")
    if isinstance(hotels, list) and hotels and not any(isinstance(hotel, dict) and hotel.get("name") for hotel in hotels):
        warnings.append(_issue("warning", "HOTEL_PROPERTY_MISSING", "目前只有住宿区域，没有具体酒店候选；请补充有来源的酒店名称或说明无法核实", "hotels"))

    # ---- 行前清单与证据卡 ----
    checklist = guide.get("checklist")
    if checklist is not None:
        if not isinstance(checklist, list):
            errors.append(_issue("error", "COLLECTION", "checklist 必须是数组", "checklist"))
        else:
            for index, entry in enumerate(checklist):
                path = "checklist[{}]".format(index)
                if not isinstance(entry, dict):
                    errors.append(_issue("error", "RECORD", "清单项必须是对象", path))
                    continue
                if not entry.get("title"):
                    errors.append(_issue("error", "CHECKLIST_TITLE", "清单项缺少 title", path))
                # 带 date 的清单项会导出为 ICS 全天事件
                if entry.get("date") and not _valid_date(entry.get("date")):
                    errors.append(_issue("error", "CHECKLIST_DATE", "清单项 date 必须为 YYYY-MM-DD", path))
                for source_id in entry.get("source_ids", []) if isinstance(entry.get("source_ids", []), list) else []:
                    if source_id not in source_ids:
                        warnings.append(_issue("warning", "SOURCE_MISSING", "引用不存在的来源 {}".format(source_id), path))

    evidence = guide.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, list):
            errors.append(_issue("error", "COLLECTION", "evidence 必须是数组", "evidence"))
        else:
            for index, card in enumerate(evidence):
                path = "evidence[{}]".format(index)
                if not isinstance(card, dict):
                    errors.append(_issue("error", "RECORD", "证据卡必须是对象", path))
                    continue
                if not (card.get("claim") or card.get("summary") or card.get("topic")):
                    errors.append(_issue("error", "EVIDENCE_FIELD", "证据卡缺少 claim/summary/topic", path))
                if card.get("checked_at") and not _valid_date(card.get("checked_at")):
                    errors.append(_issue("error", "EVIDENCE_DATE", "证据卡 checked_at 必须为 YYYY-MM-DD", path))
                for source_id in card.get("source_ids", []) if isinstance(card.get("source_ids", []), list) else []:
                    if source_id not in source_ids:
                        warnings.append(_issue("warning", "SOURCE_MISSING", "引用不存在的来源 {}".format(source_id), path))

    # ---- 预算一致性：合计与分项之和 ----
    budget = guide.get("budget")
    if isinstance(budget, dict) and isinstance(budget.get("profiles"), dict):
        for profile_name, profile in budget["profiles"].items():
            if not isinstance(profile, dict):
                continue
            total = _leading_number(profile.get("total"))
            categories = profile.get("categories") if isinstance(profile.get("categories"), dict) else {}
            amounts = [_leading_number(amount) for amount in categories.values()] if categories else []
            if total is not None and amounts and all(amount is not None for amount in amounts) and abs(sum(amounts) - total) > 0.01:
                warnings.append(_issue("warning", "BUDGET_MISMATCH", "预算方案 {} 的合计 {} 与分项之和 {} 不一致".format(profile_name, total, sum(amounts)), "budget.profiles.{}".format(profile_name)))

    # 视觉层：无本地图片也无媒体链接 -> 提醒（纯文字攻略）
    has_media = any(
        isinstance(source, dict) and isinstance(source.get("media"), list) and source["media"]
        for source in (guide.get("sources") or []) if isinstance(guide.get("sources"), list)
    )
    if not guide.get("images") and not has_media:
        warnings.append(_issue("warning", "VISUALS_MISSING", "没有图片素材或媒体链接；应提供合法本地图片，或在研究时采集 sources[].media 媒体链接", "images"))

    return {"valid": not errors, "errors": errors, "warnings": warnings, "conflicts": conflicts}
