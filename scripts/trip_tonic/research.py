"""研究记录 lint：结构校验 + 分档覆盖要求。

行程长度（meta.trip_days，缺失回退中档）决定最低工作量：
- 1-3 天： 4 次检索 / 6 篇深读笔记 / 3 篇读评论 / 4 条主题轴
- 4-7 天： 6 次检索 / 8 篇深读笔记 / 4 篇读评论 / 5 条主题轴
- 8 天以上：8 次检索 / 10 篇深读笔记 / 5 篇读评论 / 6 条主题轴

每次检索必须记录 topic 主题轴，且至少一次记录时效过滤。
研究记录只是规划产物，不代表实际做过这些研究。
"""

from .common import _issue, _valid_date
from .schema import SchemaCorruptError, _schema_issues, load_research_schema

# 笔记检查深度（逐级递增：仅看卡片 -> 打开全文 -> 打开评论）
INSPECTION_LEVELS = ("search_card_only", "full_note_opened", "comments_opened")

# 检索主题轴：确保研究覆盖行程/景点/美食/住宿/交通/时效/避坑
SEARCH_TOPICS = ("itinerary", "attractions", "food", "lodging", "transport", "conditions", "pitfalls")

# (最大天数, 档位标签, 最低检索数, 最低深读数, 最低评论数, 最低主题轴数)
_TIERS = (
    (3, "1-3 天", 4, 6, 3, 4),
    (7, "4-7 天", 6, 8, 4, 5),
    (None, "8 天以上", 8, 10, 5, 6),
)
# trip_days 缺失/非法时的回退档位（中档）
_DEFAULT_TIER = (7, "4-7 天", 6, 8, 4, 5)


def _requirements(trip_days):
    """按行程天数取档位元组；非法或缺失回退中档。"""
    if isinstance(trip_days, bool) or not isinstance(trip_days, int) or trip_days < 1:
        return _DEFAULT_TIER
    for tier in _TIERS:
        if tier[0] is None or trip_days <= tier[0]:
            return tier
    return _DEFAULT_TIER


def research_record_issues(record):
    """校验研究记录 JSON，返回 {valid, errors, warnings, coverage}。"""
    errors, warnings = [], []
    if not isinstance(record, dict):
        return {"valid": False, "errors": [_issue("error", "ROOT", "根节点必须是对象", "$")], "warnings": [], "coverage": {}}

    # ---- 第 1 层：JSON Schema 子集校验（损坏报错，缺失降级警告） ----
    try:
        schema = load_research_schema()
        errors.extend(_schema_issues(record, schema))
    except SchemaCorruptError as error:
        errors.append(_issue("error", "SCHEMA_CORRUPT", str(error), "references/research-record-schema.json"))
    except OSError:
        warnings.append(_issue("warning", "SCHEMA_UNAVAILABLE", "未能加载研究记录 JSON Schema；仅执行内置校验", "references/research-record-schema.json"))

    searches = record.get("searches") if isinstance(record.get("searches"), list) else []
    notes = record.get("notes") if isinstance(record.get("notes"), list) else []
    gaps = record.get("gaps") if isinstance(record.get("gaps"), list) else []

    # ---- 笔记：source_id 去重、检查深度枚举、日期、媒体条目 ----
    note_ids = []
    for index, note in enumerate(notes):
        if not isinstance(note, dict):
            continue
        note_id = note.get("source_id")
        if note_id:
            if note_id in note_ids:
                errors.append(_issue("error", "RESEARCH_DUPLICATE_ID", "笔记 source_id 重复：{}".format(note_id), "notes[{}]".format(index)))
            note_ids.append(note_id)
        inspection = note.get("inspection")
        if inspection is not None and inspection not in INSPECTION_LEVELS:
            errors.append(_issue("error", "RESEARCH_INSPECTION", "inspection 必须为 {}".format(" / ".join(INSPECTION_LEVELS)), "notes[{}].inspection".format(index)))
        if note.get("checked_at") and not _valid_date(note.get("checked_at")):
            errors.append(_issue("error", "RESEARCH_DATE", "checked_at 必须为 YYYY-MM-DD", "notes[{}].checked_at".format(index)))
        # 媒体链接：结构校验（type 枚举 + 必须有 url），协议由 schema pattern 把关
        media = note.get("media")
        if media is not None:
            if not isinstance(media, list):
                errors.append(_issue("error", "RESEARCH_MEDIA", "notes[].media 必须是数组", "notes[{}].media".format(index)))
            else:
                for media_index, entry in enumerate(media):
                    if not isinstance(entry, dict) or entry.get("type") not in ("image", "video") or not entry.get("url"):
                        errors.append(_issue("error", "RESEARCH_MEDIA", "媒体条目需要 type（image/video）与 HTTP(S) url", "notes[{}].media[{}]".format(index, media_index)))

    # ---- 检索：日期、topic 主题轴枚举，统计已覆盖主题 ----
    topics_seen = []
    for index, search in enumerate(searches):
        if not isinstance(search, dict):
            continue
        if search.get("checked_at") and not _valid_date(search.get("checked_at")):
            errors.append(_issue("error", "RESEARCH_DATE", "checked_at 必须为 YYYY-MM-DD", "searches[{}].checked_at".format(index)))
        topic = search.get("topic")
        if topic is None:
            errors.append(_issue("error", "RESEARCH_TOPIC", "检索缺少 topic（可选值：{}）".format(" / ".join(SEARCH_TOPICS)), "searches[{}].topic".format(index)))
        elif topic not in SEARCH_TOPICS:
            errors.append(_issue("error", "RESEARCH_TOPIC", "topic 必须为 {}".format(" / ".join(SEARCH_TOPICS)), "searches[{}].topic".format(index)))
        elif topic not in topics_seen:
            topics_seen.append(topic)
    # 至少一次检索记录了时效过滤（filters）
    has_filters = any(isinstance(search, dict) and search.get("filters") for search in searches)

    # ---- 证据卡与决策：引用的笔记应存在（note_ids 为空时跳过，避免整记录误报） ----
    evidence = record.get("evidence_cards") if isinstance(record.get("evidence_cards"), list) else []
    for index, card in enumerate(evidence):
        if not isinstance(card, dict):
            continue
        for source_id in card.get("source_ids", []) if isinstance(card.get("source_ids"), list) else []:
            if note_ids and source_id not in note_ids:
                warnings.append(_issue("warning", "RESEARCH_SOURCE_MISSING", "证据卡引用的笔记不存在：{}".format(source_id), "evidence_cards[{}].source_ids".format(index)))

    decisions = record.get("decisions") if isinstance(record.get("decisions"), list) else []
    for index, decision in enumerate(decisions):
        if not isinstance(decision, dict):
            continue
        for source_id in decision.get("source_ids", []) if isinstance(decision.get("source_ids"), list) else []:
            if note_ids and source_id not in note_ids:
                warnings.append(_issue("warning", "RESEARCH_SOURCE_MISSING", "决策引用的笔记不存在：{}".format(source_id), "decisions[{}].source_ids".format(index)))

    # 深读 = 打开过全文或评论；评论串 = 打开过评论
    full_notes = [note for note in notes if isinstance(note, dict) and note.get("inspection") in ("full_note_opened", "comments_opened")]
    comment_threads = [note for note in notes if isinstance(note, dict) and note.get("inspection") == "comments_opened"]

    # ---- 分档覆盖检查：按 trip_days 取档，全部为 warning 级（--strict 下升级） ----
    meta = record.get("meta") if isinstance(record.get("meta"), dict) else {}
    if meta.get("destination") in (None, ""):
        errors.append(_issue("error", "RESEARCH_META", "研究记录缺少 meta.destination", "meta.destination"))
    trip_days = meta.get("trip_days")
    valid_days = isinstance(trip_days, int) and not isinstance(trip_days, bool) and trip_days >= 1
    tier = _requirements(trip_days)
    # 解包档位元组（首个字段 max_days 仅供 _requirements 内部使用）
    _, label, search_min, notes_min, comments_min, topics_min = tier
    # 提示语区分"分档要求"与"默认建议"（trip_days 非法时）
    scope = label + "行程的最低" if valid_days else "建议的"
    if not searches:
        warnings.append(_issue("warning", "RESEARCH_SEARCH_COVERAGE", "未记录任何检索；应按行程天数覆盖主题矩阵（见 references/opencli-research.md）", "searches"))
    else:
        if len(searches) < search_min:
            warnings.append(_issue("warning", "RESEARCH_SEARCH_COVERAGE", "检索仅 {} 次，低于{} {} 次".format(len(searches), scope, search_min), "searches"))
        if len(topics_seen) < topics_min:
            warnings.append(_issue("warning", "RESEARCH_TOPIC_COVERAGE", "检索主题仅覆盖 {}/{} 类（{}）；缺少：{}".format(len(topics_seen), topics_min, "、".join(topics_seen), "、".join(topic for topic in SEARCH_TOPICS if topic not in topics_seen)), "searches"))
        if not has_filters:
            warnings.append(_issue("warning", "RESEARCH_RECENCY", "未记录任何时效过滤（searches[].filters）；优先按最近发布排序/过滤并记录所用筛选", "searches"))
    if len(full_notes) < notes_min:
        warnings.append(_issue("warning", "RESEARCH_NOTE_COVERAGE", "完整阅读笔记仅 {} 篇，低于{} {} 篇".format(len(full_notes), scope, notes_min), "notes"))
    if len(comment_threads) < comments_min:
        warnings.append(_issue("warning", "RESEARCH_COMMENT_COVERAGE", "读过评论的笔记仅 {} 篇，低于{} {} 篇".format(len(comment_threads), scope, comments_min), "notes"))
    if not gaps:
        warnings.append(_issue("warning", "RESEARCH_GAPS_MISSING", "未记录研究缺口或局限；应显式列出未能核实的事项", "gaps"))

    # coverage 供 CLI/Agent 汇总展示实际覆盖情况
    coverage = {"searches": len(searches), "notes_inspected": len(full_notes), "comment_threads": len(comment_threads), "evidence_cards": len(evidence), "decisions": len(decisions), "topics_covered": topics_seen, "trip_days": trip_days if valid_days else None}
    return {"valid": not errors, "errors": errors, "warnings": warnings, "coverage": coverage}
