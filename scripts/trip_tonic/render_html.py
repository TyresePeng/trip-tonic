"""HTML 渲染器：双语、离线优先，图表全部为内联 SVG。

设计约束：
- 默认完全离线：图表用内联 SVG（甘特/饼图/路线示意），
  不引用任何外部资源；--online-map 才追加 Leaflet 图层；
  媒体相册缓存模式下图片以 data URI 内嵌
- 所有用户可见文案走 tr()；zh 为源语言，meta.language 以 "en"
  开头时全文切换英文
- HTML 输出统一 _esc() 转义，防止攻略字段里混入 HTML
"""

import base64
import html
import json
import math
import mimetypes
from pathlib import Path

from .common import _coordinate_error, _is_drive, _minutes, _source_map
from .stats import budget_pie_data, guide_stats, human_minutes, type_label
from .strings import tr

# 行程项类型 -> 甘特条/图例颜色（与整体墨绿配色一致）
_TYPE_COLORS = {"spot": "#37645a", "meal": "#c07a3a", "transport": "#56669c", "hotel": "#8a5a66", "activity": "#3e7cb1", "rest": "#9aa79c"}
# 预算饼图循环取色（超过 10 类回到开头）
_PIE_COLORS = ["#37645a", "#c07a3a", "#56669c", "#8a5a66", "#3e7cb1", "#9aa79c", "#a8763e", "#6d9a3e", "#9a3e52", "#3e6d9a"]

# 页面样式：单文件自包含（无外部 CSS/JS）；含打印分页与移动端断点
_CSS = (
    "*{box-sizing:border-box}body{margin:0;background:#f3f0e8;color:#23312e;font:16px/1.65 system-ui,-apple-system,\"Segoe UI\",sans-serif}"
    "main{max-width:1000px;margin:auto;padding:28px 18px 60px}"
    "header,.card,.day{background:#fff;border:1px solid #e4e1d8;border-radius:18px;padding:22px;margin:16px 0;box-shadow:0 8px 26px #30443b0b}"
    "header{background:linear-gradient(130deg,#163b39,#37645a);color:#fff;padding:32px}"
    "h1{font-size:clamp(2rem,6vw,3.4rem);line-height:1.1;margin:.2em 0}"
    "h2{font-size:1.45rem;margin:.1em 0 .55em}"
    "h3{margin:.25em 0}"
    ".tag,.badge{display:inline-block;border-radius:999px;background:#e7f0e9;color:#285245;padding:3px 10px;margin:3px;font-size:.88rem}"
    ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}"
    ".item{border-left:3px solid #80a894;padding:4px 0 8px 14px;margin:12px 0}"
    ".time{font-variant-numeric:tabular-nums;color:#467263;font-weight:700}"
    ".muted,small{color:#697773}"
    ".warn{border-left:4px solid #d99b4d;background:#fff6e8;padding:12px 15px;border-radius:8px}"
    "a{color:#176556;overflow-wrap:anywhere}"
    "table{border-collapse:collapse;width:100%}"
    "td,th{text-align:left;border-bottom:1px solid #e6e4df;padding:8px}"
    ".score{font-size:.85rem;color:#596c63}"
    ".route-legs{display:grid;gap:10px}"
    ".route-leg{border:1px solid #dfe7df;border-radius:12px;padding:12px}"
    ".route-map{display:block;width:100%;height:auto;max-height:150px;margin:12px 0}"
    ".route-map rect{fill:#f4f8f4;stroke:#8fae9c;stroke-width:2}"
    ".route-map text{fill:#23312e;font:14px system-ui,sans-serif}"
    ".route-map path{fill:none;stroke:#467263;stroke-width:2}"
    ".route-map .route-caption{fill:#697773;font-size:11px}"
    "figure{margin:0}"
    "figure img{display:block;width:100%;height:auto;border-radius:12px}"
    ".stats-grid{display:grid;grid-template-columns:1fr;gap:16px;align-items:start}"
    ".gantt{display:block;width:100%;height:auto;margin:6px 0 2px}"
    ".gantt text{fill:#23312e;font:12px system-ui,sans-serif}"
    ".gantt .gantt-grid{stroke:#e6e4df;stroke-width:1}"
    ".gantt .gantt-day{fill:#467263;font-weight:700;font-size:11px}"
    ".gantt .gantt-hour{fill:#697773;font-size:10px}"
    ".gantt-bar{stroke:#fff;stroke-width:1;cursor:pointer}"
    ".gantt-bar:hover{filter:brightness(1.12)}"
    ".legend{display:flex;flex-wrap:wrap;gap:12px;font-size:.8rem;color:#596c63;margin:2px 0 8px}"
    ".legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:4px}"
    ".pie-wrap{display:flex;align-items:center;gap:18px;flex-wrap:wrap}"
    ".pie{flex:0 0 auto;max-width:100%;height:auto}"
    ".pie path,.pie circle{cursor:pointer}"
    ".pie path:hover,.pie circle:hover{filter:brightness(1.1)}"
    ".pie-legend{list-style:none;padding:0;margin:0;font-size:.85rem;color:#596c63}"
    ".pie-legend li{margin:2px 0}"
    ".pie-legend i{width:10px;height:10px;border-radius:3px;display:inline-block;margin-right:6px}"
    ".map-box{height:420px;border-radius:12px;overflow:hidden;border:1px solid #dfe7df}"
    ".media-card{border:1px solid #dfe7df;border-radius:12px;padding:12px;min-width:0}"
    ".media-card .badge{margin:0 0 8px}"
    ".media-kind{display:inline-block;border-radius:999px;padding:2px 10px;font-size:.78rem;font-weight:700;margin-right:6px}"
    ".media-kind.image{background:#e7eef7;color:#3e5a86}"
    ".media-kind.video{background:#f7eee7;color:#8a5a3e}"
    ".media-thumb{margin:0;border:1px solid #dfe7df;border-radius:12px;overflow:hidden;cursor:zoom-in;background:#f8faf8;position:relative}"
    ".media-thumb img,.media-thumb video{display:block;width:100%;height:190px;object-fit:cover}"
    ".media-thumb figcaption{padding:10px 12px;font-size:.85rem;color:#596c63}"
    ".media-thumb:focus-visible{outline:3px solid #467263;outline-offset:2px}"
    ".media-thumb .video-mark{position:absolute;top:8px;right:8px;width:30px;height:30px;border-radius:999px;background:rgba(13,21,18,.6);border:1px solid rgba(255,255,255,.55)}"
    ".media-thumb .video-mark::before{content:'';display:block;margin:9px 4px 9px 11px;border-style:solid;border-width:6px 0 6px 10px;border-color:transparent transparent transparent #fff}"
    ".media-group{margin:16px 0 4px}"
    ".media-group-head{display:flex;flex-wrap:wrap;align-items:baseline;gap:10px;margin:0 0 10px}"
    ".media-group-head strong{font-size:.98rem}"
    ".media-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px}"
    ".media-groups.folded .media-group:nth-child(n+4){display:none}"
    ".media-group.folded .media-thumb:nth-child(n+5){display:none}"
    ".media-more,.media-toggle{background:none;border:1px solid #cfd9d2;border-radius:999px;padding:6px 18px;color:#467263;cursor:pointer;font-size:.85rem}"
    ".media-more:hover,.media-toggle:hover{background:#eef4f0}"
    ".media-more{margin-top:8px}"
    ".media-summary{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0 0 4px}"
    ".media-toggle{display:inline-block;margin:0}"
    ".media-toggle-end{display:block;margin:16px 0 4px}"
    ".media-groups.media-folded~.media-toggle-end{display:none}"
    ".media-links{list-style:none;padding:0;margin:14px 0 0;font-size:.9rem}"
    ".media-links li{margin:6px 0}"
    ".lightbox{position:fixed;inset:0;background:rgba(13,21,18,.94);display:none;align-items:center;justify-content:center;flex-direction:column;z-index:50;padding:20px}"
    ".lightbox.open{display:flex}"
    ".lightbox-stage{display:flex;align-items:center;justify-content:center}"
    ".lightbox-stage img,.lightbox-stage video{max-width:92vw;max-height:74vh;border-radius:10px;background:#000}"
    ".lightbox-close,.lightbox-prev,.lightbox-next{position:absolute;background:rgba(255,255,255,.14);color:#fff;border:none;border-radius:999px;width:44px;height:44px;font-size:22px;line-height:1;cursor:pointer}"
    ".lightbox-close:hover,.lightbox-prev:hover,.lightbox-next:hover{background:rgba(255,255,255,.28)}"
    ".lightbox-close{top:16px;right:20px}"
    ".lightbox-prev{left:16px;top:50%;transform:translateY(-50%)}"
    ".lightbox-next{right:16px;top:50%;transform:translateY(-50%)}"
    ".lightbox-prev:disabled,.lightbox-next:disabled{opacity:.3;cursor:default}"
    ".lightbox-caption{color:#dfe7df;margin-top:12px;text-align:center;max-width:90vw;font-size:.95rem}"
    ".lightbox-caption a{color:#8fd3c0}"
    ".lightbox-counter{color:#9aa79c;margin-top:4px;font-size:.85rem}"
    "footer{color:#64716e;border-top:1px solid #d6d4ce;margin-top:28px;padding-top:14px}"
    "@media(max-width:600px){main{padding:12px}header,.card,.day{padding:17px}}"
    "@media print{body{background:#fff;font-size:12px}main{max-width:none;padding:0}header,.card,.day{box-shadow:none;break-inside:avoid}.day+.day{break-before:page}a{color:#176556}}"
)


def _esc(value):
    """HTML 属性/文本统一转义（None 归空串）。"""
    return html.escape(str(value if value is not None else ""), quote=True)


def _image_source(image, media_root):
    """把媒体根目录里的本地图片读成 data URI（内嵌，保持单文件离线）。

    安全校验链（防任意文件读取与伪装内容）：
    1. 必须提供 media_root 且路径解析后仍在根目录内（拒绝 ../ 逃逸）
    2. 扩展名 MIME 必须是白名单图片类型，文件 <= 10MB
    3. 魔数校验文件头与声明类型一致（WebP 额外查 RIFF 容器）
    任一环节失败返回 None（渲染为"图片缺失"提示，而非崩溃）。
    """
    if not media_root or not image.get("path"):
        return None
    root = Path(media_root).resolve()
    path = (root / image["path"]).resolve()
    if root not in path.parents or not path.is_file():
        return None
    mime = mimetypes.guess_type(str(path))[0]
    signatures = {
        "image/png": (b"\x89PNG\r\n\x1a\n",),
        "image/jpeg": (b"\xff\xd8\xff",),
        "image/gif": (b"GIF87a", b"GIF89a"),
        "image/webp": (b"RIFF",),
    }
    if mime not in signatures or path.stat().st_size > 10 * 1024 * 1024:
        return None
    data = path.read_bytes()
    if not any(data.startswith(signature) for signature in signatures[mime]):
        return None
    if mime == "image/webp" and data[8:12] != b"WEBP":
        return None
    encoded = base64.b64encode(data).decode("ascii")
    return "data:{};base64,{}".format(mime, encoded)


def _source_links_html(source_ids, sources):
    """把 source_ids 渲染成（可能带链接的）标题列表，供"来源"行拼接。"""
    links = []
    for sid in source_ids if isinstance(source_ids, list) else []:
        source = sources.get(sid, {}) if isinstance(sid, str) else {}
        label = _esc(source.get("title", sid))
        url = source.get("url")
        links.append('<a href="{}" target="_blank" rel="noopener">{}</a>'.format(_esc(url), label) if url else label)
    return links


def _backup_list_html(guide, entries, label):
    """备选项渲染：字符串或 {condition, plan} 对象 -> 带 label 的列表。"""
    if not isinstance(entries, list) or not entries:
        return ""
    items = []
    for entry in entries:
        if isinstance(entry, str):
            items.append("<li>{}</li>".format(_esc(entry)))
        elif isinstance(entry, dict):
            prefix = "<strong>{}</strong>：".format(_esc(entry["condition"])) if entry.get("condition") else ""
            items.append("<li>{}{}</li>".format(prefix, _esc(entry.get("plan", ""))))
    return '<p class="muted"><strong>{}</strong></p><ul>{}</ul>'.format(_esc(label), "".join(items)) if items else ""


def _scaled_route_svg(guide, stops):
    """等距圆柱投影示意路线图（经纬度线性映射到画布）。

    只画相对位置，不画真实地理；调用方必须保证所有停靠点
    坐标有效（先过 _stops_all_have_coords）。标签超 8 字截断，
    上下交错摆放避免重叠。
    """
    lons = [stop["coords"][0] for stop in stops]
    lats = [stop["coords"][1] for stop in stops]
    span_x = max(max(lons) - min(lons), 0.01)
    span_y = max(max(lats) - min(lats), 0.01)
    width = 760.0
    height = min(360.0, max(150.0, width * span_y / span_x))
    pad = min(60.0, height / 3.0)
    points = []
    for stop in stops:
        lon, lat = stop["coords"]
        x = pad + (lon - min(lons)) / span_x * (width - 2 * pad)
        y = pad + (max(lats) - lat) / span_y * (height - 2 * pad)
        points.append((x, y, stop.get("name", "")))
    parts = ['<svg class="route-map" role="img" aria-label="{}" viewBox="0 0 {} {}" xmlns="http://www.w3.org/2000/svg"><text x="12" y="18" class="route-caption">{}</text>'.format(_esc(tr(guide, "route_aria_scaled")), int(width), int(height), _esc(tr(guide, "route_caption_scaled")))]
    parts.append('<polyline points="{}" fill="none" stroke="#467263" stroke-width="3"/>'.format(" ".join("{:.1f},{:.1f}".format(x, y) for x, y, _ in points)))
    for index, (x, y, name) in enumerate(points):
        parts.append('<circle cx="{:.1f}" cy="{:.1f}" r="7" fill="#37645a"/>'.format(x, y))
        label = name if len(name) <= 8 else name[:8] + "…"
        parts.append('<text x="{:.1f}" y="{:.1f}">{}</text>'.format(x - 6, y + (-12 if index % 2 == 0 else 22), _esc(label)))
    parts.append("</svg>")
    return "".join(parts)


def _stops_all_have_coords(stops):
    """全部停靠点都带有效坐标（可走等比例缩放图；否则退回链式示意）。"""
    return bool(stops) and all(
        isinstance(stop, dict) and "coords" in stop and _coordinate_error(stop.get("coords")) is None
        for stop in stops
    )


def _day_windows(guide):
    """甘特图数据源：每天 -> [(开始分, 结束分, 类型, 名称)]，非法时间直接丢弃。"""
    result = []
    days = guide.get("days") if isinstance(guide.get("days"), list) else []
    for day in days:
        if not isinstance(day, dict):
            continue
        windows = []
        for item in day.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            start, end = _minutes(item.get("start")), _minutes(item.get("end"))
            if start is None or end is None or end <= start:
                continue
            windows.append((start, end, item.get("type") or "activity", item.get("name", "")))
        result.append((day.get("day"), day.get("date"), windows))
    return result


def _fmt_hm(minutes):
    """分钟数 -> HH:MM 文本（甘特刻度/悬浮标题用）。"""
    return "{:02d}:{:02d}".format(minutes // 60, minutes % 60)


def _gantt_svg(guide):
    """逐日行程甘特图（内联 SVG）：条形按类型着色，2 小时间隔刻度。

    返回 (svg, 图例中出现的类型列表)；无行程窗口时返回空串。
    """
    data = [entry for entry in _day_windows(guide) if entry[2]]
    if not data:
        return "", []
    # 横轴范围取全部行程项的最早开始/最晚结束；不足 1 小时扩到 1 小时
    all_starts = [window[0] for _, _, windows in data for window in windows]
    all_ends = [window[1] for _, _, windows in data for window in windows]
    x_min, x_max = min(all_starts), max(all_ends)
    if x_max - x_min < 60:
        x_max = x_min + 60
    width, gutter, header, row_h = 760.0, 104.0, 26.0, 30.0
    height = header + row_h * len(data) + 10
    plot_w = width - gutter - 16.0

    def sx(minutes):
        return gutter + (minutes - x_min) / (x_max - x_min) * plot_w

    parts = ['<svg class="gantt" role="img" aria-label="{}" viewBox="0 0 {} {}" xmlns="http://www.w3.org/2000/svg">'.format(_esc(tr(guide, "stats_gantt_aria")), int(width), int(height))]
    # 竖网格线 + 2 小时刻度
    tick = int(x_min // 60) * 60
    while tick <= x_max:
        x = sx(tick)
        parts.append('<line class="gantt-grid" x1="{:.1f}" y1="20" x2="{:.1f}" y2="{:.1f}"/>'.format(x, x, height - 8))
        parts.append('<text class="gantt-hour" x="{:.1f}" y="16" text-anchor="middle">{}</text>'.format(x, _fmt_hm(tick)))
        tick += 120
    for row_index, (day_number, day_date, windows) in enumerate(data):
        top = header + row_index * row_h
        parts.append('<text class="gantt-day" x="10" y="{:.1f}">Day {}</text>'.format(top + 14, day_number))
        parts.append('<text class="gantt-hour" x="10" y="{:.1f}">{}</text>'.format(top + 26, _esc(day_date)))
        for start, end, item_type, name in windows:
            color = _TYPE_COLORS.get(item_type, _TYPE_COLORS["activity"])
            # 极短行程项也保底 2px 宽，避免完全不可见
            x, w = sx(start), max(sx(end) - sx(start), 2.0)
            title = _esc("{}–{} {}".format(_fmt_hm(start), _fmt_hm(end), name))
            parts.append('<rect class="gantt-bar" x="{:.1f}" y="{:.1f}" width="{:.1f}" height="14" rx="4" fill="{}"><title>{}</title></rect>'.format(x, top + 6, w, color, title))
    parts.append("</svg>")
    # 图例只列实际出现的类型（顺序固定）
    used_types = []
    for item_type in ("spot", "meal", "transport", "hotel", "activity", "rest"):
        if any(window[2] == item_type for _, _, windows in data for window in windows):
            used_types.append(item_type)
    return "".join(parts), used_types


def _budget_pie_svg(guide, profile_name, entries):
    """预算饼图（内联 SVG 扇形 + 图例列表）。

    entries 来自 stats.budget_pie_data：[(分类, 数值, 占比)]。
    单一分类（占比 >= 99.9%）整圆处理；扇形用 SVG 弧命令拼接。
    显式 width/height（180px）：SVG 只带 viewBox 时浏览器会按容器
    拉伸渲染，饼图会大得离谱；扇形带 <title> 悬停显示分类明细。
    """
    cx, cy, radius = 90.0, 90.0, 68.0
    parts = ['<svg class="pie" role="img" aria-label="{}" viewBox="0 0 180 180" width="180" height="180" xmlns="http://www.w3.org/2000/svg">'.format(_esc(tr(guide, "stats_budget_aria")))]
    legend = []
    angle = -math.pi / 2.0
    for index, (category, value, fraction) in enumerate(entries):
        color = _PIE_COLORS[index % len(_PIE_COLORS)]
        end_angle = angle + fraction * 2.0 * math.pi
        title = _esc("{} · {} · {:.0%}".format(category, value, fraction))
        if fraction >= 0.999:
            parts.append('<circle cx="{}" cy="{}" r="{}" fill="{}" stroke="#fff" stroke-width="2"><title>{}</title></circle>'.format(cx, cy, radius, color, title))
        else:
            x1, y1 = cx + radius * math.cos(angle), cy + radius * math.sin(angle)
            x2, y2 = cx + radius * math.cos(end_angle), cy + radius * math.sin(end_angle)
            # 超过半圆时 large-arc-flag 置 1
            large = 1 if fraction > 0.5 else 0
            parts.append('<path d="M {} {} L {:.1f} {:.1f} A {:.1f} {:.1f} 0 {} 1 {:.1f} {:.1f} Z" fill="{}" stroke="#fff" stroke-width="2"><title>{}</title></path>'.format(cx, cy, x1, y1, radius, radius, large, x2, y2, color, title))
        legend.append('<li><i style="background:{}"></i>{} · {} · {:.0%}</li>'.format(color, _esc(category), _esc(value), fraction))
        angle = end_angle
    parts.append("</svg>")
    return '<div class="pie-wrap">{}<ul class="pie-legend">{}</ul></div>'.format("".join(parts), "".join(legend))


def _stats_section_html(guide):
    """行程统计卡片：指标表 + 甘特图与类型图例（与 Markdown 版同源）。"""
    stats = guide_stats(guide)
    totals = stats["totals"]
    if not totals["days"]:
        return ""
    drive = human_minutes(guide, totals["drive_minutes"]) or tr(guide, "stats_none")
    drive_km = tr(guide, "stats_km").format(round(totals["drive_km"], 1)) if totals["drive_km"] else tr(guide, "stats_none")
    longest = tr(guide, "stats_none")
    if stats.get("longest_leg"):
        leg = stats["longest_leg"]
        longest = "{} → {} · {}".format(_esc(leg.get("from")), _esc(leg.get("to")), human_minutes(guide, leg["duration_min"]) or tr(guide, "duration_unverified"))
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
        (tr(guide, "stats_pace_label"), pace_text),
    ]
    if totals["media"]:
        pairs.append((tr(guide, "stats_media"), str(totals["media"])))
    rows = "".join(tr(guide, "stats_line_html").format(_esc(label), _esc(value)) for label, value in pairs)
    table = "<div><table>{}</table></div>".format(rows)
    gantt_svg, used_types = _gantt_svg(guide)
    legend = ""
    if used_types:
        legend = '<div class="legend">' + "".join('<span><i style="background:{}"></i>{}</span>'.format(_TYPE_COLORS[item_type], _esc(type_label(guide, item_type))) for item_type in used_types) + "</div>"
    chart = '<div>{}{}</div>'.format(legend, gantt_svg)
    return '<section class="card"><h2>{}</h2><div class="stats-grid">{}{}</div></section>'.format(_esc(tr(guide, "stats")), table, chart)


def _online_map_section_html(guide):
    """可选 Leaflet 在线地图（--online-map）：渲染 GeoJSON 图层 + 弹窗。

    仅此节引入外部资源（Leaflet CDN + OSM 瓦片）；JSON 序列化后
    替换 "</" 防止提前闭合 <script> 标签。bounds 计算失败时回退
    到以中国为中心的默认视野。
    """
    from .render_geojson import geojson_data

    payload = json.dumps(geojson_data(guide), ensure_ascii=False).replace("</", "<\\/")
    script = (
        "var tripData = " + payload + ";\n"
        "var map = L.map(\"trip-map\");\n"
        "L.tileLayer(\"https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png\", {attribution: \"&copy; OpenStreetMap contributors\", maxZoom: 18}).addTo(map);\n"
        "var layer = L.geoJSON(tripData, {onEachFeature: function (feature, featureLayer) {"
        "if (feature.properties && feature.properties.name) { featureLayer.bindPopup(String(feature.properties.name)); }"
        "}}).addTo(map);\n"
        "try { map.fitBounds(layer.getBounds(), {padding: [20, 20]}); } catch (error) { map.setView([30, 105], 4); }\n"
    )
    return (
        '<section class="card"><h2>{}</h2><div id="trip-map" class="map-box"></div><p class="muted">{}</p>'
        '<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">'
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>'
        '<script>{}</script></section>'
    ).format(_esc(tr(guide, "online_map_title")), _esc(tr(guide, "online_map_note")), script)


# 灯箱脚本：__MEDIA_GROUPS__ 占位符替换为分组 JSON 数据。
# 纯原生 JS、零依赖；文本一律 textContent 写入（用户数据不经 innerHTML），
# JSON 序列化时替换 "</" 防止提前闭合 <script>。
# 翻页在组内循环（上一张/下一张在当前笔记的图集内绕回，不跨组）。
_LIGHTBOX_JS = """(function () {
  "use strict";
  var groups = __MEDIA_GROUPS__;
  var box = document.createElement("div");
  box.className = "lightbox";
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "true");
  var close = document.createElement("button");
  close.className = "lightbox-close";
  close.type = "button";
  close.setAttribute("aria-label", "close");
  close.textContent = "\\u00d7";
  var prev = document.createElement("button");
  prev.className = "lightbox-prev";
  prev.type = "button";
  prev.setAttribute("aria-label", "previous");
  prev.textContent = "\\u2039";
  var next = document.createElement("button");
  next.className = "lightbox-next";
  next.type = "button";
  next.setAttribute("aria-label", "next");
  next.textContent = "\\u203a";
  var stage = document.createElement("div");
  stage.className = "lightbox-stage";
  var caption = document.createElement("div");
  caption.className = "lightbox-caption";
  var counter = document.createElement("div");
  counter.className = "lightbox-counter";
  box.appendChild(close);
  box.appendChild(prev);
  box.appendChild(stage);
  box.appendChild(next);
  box.appendChild(caption);
  box.appendChild(counter);
  document.body.appendChild(box);
  var currentGroup = 0;
  var current = 0;
  function render(groupIndex, index) {
    currentGroup = groupIndex;
    current = index;
    var group = groups[groupIndex];
    var item = group.items[index];
    stage.textContent = "";
    var media;
    if (item.kind === "video") {
      media = document.createElement("video");
      media.controls = true;
      media.preload = "metadata";
    } else {
      media = document.createElement("img");
      media.alt = item.title;
    }
    media.src = item.src;
    stage.appendChild(media);
    caption.textContent = "";
    var titleLine = document.createElement("div");
    titleLine.textContent = item.typeLabel + " \\u00b7 " + item.title;
    caption.appendChild(titleLine);
    if (group.sourceTitle) {
      var sourceLine = document.createElement("div");
      sourceLine.textContent = group.sourceLabel + " ";
      var link = document.createElement("a");
      link.href = group.sourceUrl;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = group.sourceTitle;
      sourceLine.appendChild(link);
      caption.appendChild(sourceLine);
    }
    counter.textContent = (index + 1) + " / " + group.items.length;
  }
  function open(groupIndex, index) {
    render(groupIndex, index);
    box.classList.add("open");
  }
  function closeBox() {
    box.classList.remove("open");
    stage.textContent = "";
  }
  function step(delta) {
    var count = groups[currentGroup].items.length;
    render(currentGroup, (current + delta + count) % count);
  }
  close.addEventListener("click", closeBox);
  box.addEventListener("click", function (event) {
    if (event.target === box) { closeBox(); }
  });
  prev.addEventListener("click", function () { step(-1); });
  next.addEventListener("click", function () { step(1); });
  document.addEventListener("keydown", function (event) {
    if (!box.classList.contains("open")) { return; }
    if (event.key === "Escape") { closeBox(); }
    else if (event.key === "ArrowLeft") { step(-1); }
    else if (event.key === "ArrowRight") { step(1); }
  });
  var thumbs = document.querySelectorAll(".media-thumb");
  Array.prototype.forEach.call(thumbs, function (thumb) {
    function activate() {
      var groupIndex = parseInt(thumb.getAttribute("data-group"), 10);
      var index = parseInt(thumb.getAttribute("data-index"), 10);
      if (isNaN(groupIndex) || isNaN(index)) { return; }
      if (groups[groupIndex] && index >= 0 && index < groups[groupIndex].items.length) { open(groupIndex, index); }
    }
    thumb.addEventListener("click", activate);
    thumb.addEventListener("keydown", function (event) {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); }
    });
  });
})();"""

# 相册折叠脚本：分区级（媒体多时默认只显示前几组）与组内级
# （每组默认只显示前几张）；分区头与底部各有一个切换按钮，
# 点击任意一个同步全部按钮文案。文案由 data-more/data-less
# 提供，切换时写 textContent，不经过 innerHTML。
_ALBUM_JS = """(function () {
  "use strict";
  var wrap = document.getElementById("media-groups");
  if (wrap) {
    Array.prototype.forEach.call(document.querySelectorAll(".media-toggle"), function (btn) {
      btn.addEventListener("click", function () {
        var folded = wrap.classList.toggle("media-folded");
        Array.prototype.forEach.call(document.querySelectorAll(".media-toggle"), function (other) {
          other.textContent = folded ? other.getAttribute("data-more") : other.getAttribute("data-less");
        });
      });
    });
  }
  Array.prototype.forEach.call(document.querySelectorAll(".media-more"), function (btn) {
    btn.addEventListener("click", function () {
      var group = btn.closest(".media-group");
      var folded = group.classList.toggle("folded");
      btn.textContent = folded ? btn.getAttribute("data-more") : btn.getAttribute("data-less");
    });
  });
})();"""


# 相册折叠阈值：默认只展示前 3 个笔记分组、每组前 4 张，
# 其余收进"查看更多"；避免媒体多时相霸占整篇攻略。
_MEDIA_GROUPS_PREVIEW = 3
_MEDIA_GROUP_PREVIEW = 4


def _media_section_html(guide, sources, media_resolved=None):
    """媒体区：按来源笔记分组的相册（卡片样式与图文区一致：
    上图下文说明），点击开灯箱组内循环翻页；未缓存条目回退链接
    （有相册时为紧凑行列表，无相册时保持原有大卡片）。

    内容多时两级折叠：分区级默认显示前 _MEDIA_GROUPS_PREVIEW 组
    （"查看更多"展开），组内级默认显示前 _MEDIA_GROUP_PREVIEW 张
    （"查看全部 N 项"展开）。

    媒体本地化只服务个人离线参考：版权归属原作者，分组头与灯箱
    都保留来源笔记回链；图片以 data URI 内嵌，视频以产物目录
    media/ 下的相对路径引用（需连同目录保存）。
    """
    resolved_map = media_resolved or {}
    groups_html, groups_payload, uncached, total_items = [], [], [], 0
    for source in guide.get("sources", []):
        if not isinstance(source, dict) or not isinstance(source.get("media"), list):
            continue
        source_title = source.get("title", source.get("id", "source"))
        items_payload, figures = [], []
        for entry in source["media"]:
            if not isinstance(entry, dict) or not entry.get("url"):
                continue
            url = str(entry["url"])
            description = entry.get("description") or source_title or tr(guide, "media_desc_fallback")
            local = resolved_map.get(url)
            if not local:
                uncached.append((source, entry))
                continue
            # 已缓存：进相册卡片（缩略图 + 灯箱数据）
            kind = local["kind"]
            type_label = tr(guide, "media_type_video") if kind == "video" else tr(guide, "media_type_image")
            if kind == "video":
                thumb = '<span class="video-mark"></span><video src="{}" preload="metadata" muted playsinline></video>'.format(_esc(local["src"]))
            else:
                thumb = '<img src="{}" alt="{}">'.format(_esc(local["src"]), _esc(description))
            figures.append('<figure class="media-thumb" data-group="{}" data-index="{}" tabindex="0" role="button">{}<figcaption>{}</figcaption></figure>'.format(len(groups_payload), len(items_payload), thumb, _esc(description)))
            items_payload.append({"kind": kind, "src": local["src"], "title": description, "typeLabel": type_label})
        if not items_payload:
            continue
        # 分组头：笔记标题（可回链原文）+ 本组条目数
        count_label = _esc(tr(guide, "media_group_count").format(len(items_payload)))
        if source.get("url"):
            head = '<strong><a href="{}" target="_blank" rel="noopener">{}</a></strong> <span class="muted">{}</span>'.format(_esc(source["url"]), _esc(source_title), count_label)
        else:
            head = "<strong>{}</strong> <span class=\"muted\">{}</span>".format(_esc(source_title), count_label)
        # 组内折叠：超过预览张数时默认只显示前几张
        group_classes = "media-group"
        group_tail = ""
        if len(items_payload) > _MEDIA_GROUP_PREVIEW:
            group_classes += " folded"
            more_label = _esc(tr(guide, "media_more_group").format(len(items_payload)))
            less_label = _esc(tr(guide, "media_less"))
            group_tail = '<button class="media-more" type="button" data-more="{}" data-less="{}">{}</button>'.format(more_label, less_label, more_label)
        groups_html.append('<div class="{}"><div class="media-group-head">{}</div><div class="media-grid">{}</div>{}</div>'.format(group_classes, head, "".join(figures), group_tail))
        groups_payload.append({
            "sourceTitle": source_title,
            "sourceUrl": source.get("url") or "",
            "sourceLabel": tr(guide, "media_from_label"),
            "items": items_payload,
        })
        total_items += len(items_payload)
    if not groups_html and not uncached:
        return ""
    parts = ['<section class="card"><h2>{}</h2>'.format(_esc(tr(guide, "h_media")))]
    if groups_html:
        # 概览行：笔记数与媒体数；分组多时切换按钮放在头部，
        # 收起不用滚到分区底部（底部另有一个展开后才出现的收起）
        summary = '<span class="muted">{}</span>'.format(_esc(tr(guide, "media_summary").format(len(groups_payload), total_items)))
        groups_classes = "media-groups"
        top_toggle = ""
        end_toggle = ""
        if len(groups_html) > _MEDIA_GROUPS_PREVIEW:
            groups_classes += " media-folded"
            more_label = _esc(tr(guide, "media_more_sections").format(len(groups_html) - _MEDIA_GROUPS_PREVIEW))
            less_label = _esc(tr(guide, "media_less"))
            top_toggle = '<button class="media-toggle" type="button" data-more="{}" data-less="{}">{}</button>'.format(more_label, less_label, more_label)
            end_toggle = '<button class="media-toggle media-toggle-end" type="button" data-more="{}" data-less="{}">{}</button>'.format(more_label, less_label, less_label)
        parts.append('<div class="media-summary">{}{}</div>'.format(summary, top_toggle))
        parts.append('<div class="{}" id="media-groups">{}</div>'.format(groups_classes, "".join(groups_html)))
        if end_toggle:
            parts.append(end_toggle)
        payload = json.dumps(groups_payload, ensure_ascii=False).replace("</", "<\\/")
        parts.append("<script>{}</script>".format(_LIGHTBOX_JS.replace("__MEDIA_GROUPS__", payload)))
        parts.append("<script>{}</script>".format(_ALBUM_JS))
    if uncached:
        if groups_html:
            # 混合场景：未命中条目收敛为一行式紧凑链接
            lines = []
            for source, entry in uncached:
                source_title = source.get("title", source.get("id", "source"))
                is_video = entry.get("type") == "video"
                kind_class = "video" if is_video else "image"
                kind_label = tr(guide, "media_type_video") if is_video else tr(guide, "media_type_image")
                description = entry.get("description") or source_title or tr(guide, "media_desc_fallback")
                note_link = '<a href="{}" target="_blank" rel="noopener">{}</a>'.format(_esc(source.get("url")), _esc(source_title)) if source.get("url") else _esc(source_title)
                lines.append('<li><span class="media-kind {}">{}</span> <a href="{}" target="_blank" rel="noopener">{}</a> <span class="muted">{}</span></li>'.format(kind_class, _esc(kind_label), _esc(str(entry["url"])), _esc(description), _esc(tr(guide, "media_source_note")).format(note_link)))
            parts.append('<ul class="media-links">{}</ul>'.format("".join(lines)))
        else:
            # 无相册：保持原有大卡片（签名链接过期时的完整回退形态）
            cards = []
            for source, entry in uncached:
                source_title = source.get("title", source.get("id", "source"))
                source_label = _esc(source_title)
                source_link = '<a href="{}" target="_blank" rel="noopener">{}</a>'.format(_esc(source.get("url")), source_label) if source.get("url") else source_label
                is_video = entry.get("type") == "video"
                kind_label = tr(guide, "media_type_video") if is_video else tr(guide, "media_type_image")
                kind_class = "video" if is_video else "image"
                link = '<a href="{}" target="_blank" rel="noopener">{}</a>'.format(_esc(str(entry["url"])), _esc(tr(guide, "media_open_link")))
                description = entry.get("description") or source_title or tr(guide, "media_desc_fallback")
                cards.append('<article class="media-card"><span class="media-kind {}">{}</span><strong>{}</strong><p>{}</p><p class="muted">{}</p></article>'.format(kind_class, _esc(kind_label), _esc(description), link, _esc(tr(guide, "media_source_note")).format(source_link)))
            parts.append('<div class="grid">{}</div>'.format("".join(cards)))
    # 有本地缓存时换用"已缓存"说明（不再是纯链接说明）
    note = tr(guide, "media_cached_note_html") if groups_html else tr(guide, "media_note_html")
    parts.append('<p class="muted">{}</p></section>'.format(_esc(note)))
    return "".join(parts)


def html_text(guide, report, media_root=None, online_map=False, media_resolved=None):
    """渲染完整单文件 HTML；report 为已完成的校验结果（供警告区）。

    media_resolved：{url: {kind, src}} 本地媒体映射（fetch-media 缓存
    命中的条目）；命中者进相册灯箱，未命中保持链接卡片。

    章节顺序：页头 -> 假设 -> 总体路线(含示意 SVG) -> 在线地图(可选)
    -> 本地图片 -> 媒体相册(按笔记分组) -> 逐日行程 ->
    统计(表+甘特) -> 住宿/美食/商家/交通/避坑/预算/清单/提示 ->
    证据卡 -> 来源 -> 警告 -> 页脚。
    """
    meta, sources = guide.get("meta", {}), _source_map(guide)
    subtitle = meta.get("subtitle", tr(guide, "subtitle"))
    days_tag = tr(guide, "days_unit").format(meta.get("days", len(guide.get("days", []))))
    travelers_tag = tr(guide, "people_unit").format(meta.get("travelers", tr(guide, "not_specified")))
    pace_tag = (guide.get("preferences", {}) or {}).get("pace") or tr(guide, "not_specified")
    head = """<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{subtitle}">
<title>{title}</title>
<style>
{css}
</style>
</head>
<body>
<main>
<header><p>TRIPTONIC · FIELD NOTES TO ITINERARY</p><h1>{title}</h1><p>{subtitle}</p><span class="tag">{destination}</span><span class="tag">{days_tag}</span><span class="tag">{travelers_tag}</span><span class="tag">{pace_tag}</span></header>""".format(lang=_esc(meta.get("language", "zh-CN")), title=_esc(meta.get("title", tr(guide, "title_fallback"))), subtitle=_esc(subtitle), destination=_esc(meta.get("destination", "")), days_tag=_esc(days_tag), travelers_tag=_esc(travelers_tag), pace_tag=_esc(pace_tag), css=_CSS)
    parts = [head]
    # 假设与待确认（meta.assumptions 与顶层 assumptions 合并，突出展示）
    assumptions = meta.get("assumptions", []) + guide.get("assumptions", [])
    if assumptions:
        parts.append('<section class="card warn"><h2>{}</h2><ul>{}</ul></section>'.format(_esc(tr(guide, "assumptions")), "".join("<li>{}</li>".format(_esc(value)) for value in assumptions)))
    # ---- 总体路线：概览 + 示意图（等比例或链式）+ 逐段卡片 ----
    route = guide.get("route", {}) or {}
    if route:
        parts.append('<section class="card"><h2>{}</h2><p>{}</p><p class="muted">{}</p><div class="route-legs">'.format(_esc(tr(guide, "route")), _esc(route.get("overview", "")), _esc(tr(guide, "route_note_html"))))
        stops = route.get("stops", [])
        if _stops_all_have_coords(stops) and len(stops) >= 2:
            # 坐标齐全：按经纬度比例画相对位置图
            parts.append(_scaled_route_svg(guide, stops))
        elif stops:
            # 坐标缺失：退化为等距链式示意（不假装地理位置）
            width = max(320, 240 * len(stops))
            parts.append('<svg class="route-map" role="img" aria-label="{}" viewBox="0 0 {} 110" xmlns="http://www.w3.org/2000/svg"><text x="12" y="18" class="route-caption">{}</text>'.format(_esc(tr(guide, "route_aria_chain")), width, _esc(tr(guide, "route_caption_chain"))))
            for index, stop in enumerate(stops):
                x = 12 + index * 240
                label = _esc(stop.get("name", ""))
                parts.append('<rect x="{}" y="36" width="190" height="54" rx="14"/><text x="{}" y="68">{}</text>'.format(x, x + 12, label))
                if index < len(stops) - 1:
                    parts.append('<path d="M {} 63 H {}"/><path d="m {} 57 7 6-7 6"/>'.format(x + 195, x + 230, x + 223))
            parts.append("</svg>")
        for index, leg in enumerate(route.get("legs", []), 1):
            # 时长优先 duration_text（诚实区间），其次数值，否则标注待核实
            duration = _esc(leg.get("duration_text")) if leg.get("duration_text") else (tr(guide, "minutes_html").format(_esc(leg["duration_min"])) if leg.get("duration_min") is not None else tr(guide, "duration_unverified"))
            # 自驾段缺里程时明确写"里程待核实"
            distance = tr(guide, "km_html").format(_esc(leg["distance_km"])) if leg.get("distance_km") is not None else (tr(guide, "distance_unverified_html") if _is_drive(leg.get("mode")) else "")
            estimate = tr(guide, "estimate_note_html") if leg.get("estimated") else ""
            refs = " · ".join(_source_links_html(leg.get("source_ids"), sources))
            parts.append('<div class="route-leg"><strong>{}. {} → {}</strong><br>{} · {}{}{}<br><small>{}</small></div>'.format(index, _esc(leg.get("from", "")), _esc(leg.get("to", "")), _esc(leg.get("mode") or tr(guide, "mode_fallback")), duration, distance, estimate, refs))
        if route.get("caveats"):
            parts.append('<ul>{}</ul>'.format("".join("<li>{}</li>".format(_esc(note)) for note in route["caveats"])))
        parts.append("</div></section>")
    if online_map:
        parts.append(_online_map_section_html(guide))
    # ---- 本地图片：读取失败渲染"图片缺失"警告而非跳过 ----
    if guide.get("images"):
        parts.append('<section class="card"><h2>{}</h2><div class="grid">'.format(_esc(tr(guide, "h_images"))))
        for image in guide["images"]:
            source = _image_source(image, media_root)
            if not source:
                parts.append('<article><h3>{}</h3><p class="warn">{}</p></article>'.format(_esc(image.get("title", tr(guide, "image_title_fallback"))), _esc(tr(guide, "image_missing_html"))))
                continue
            caption = "<figcaption>{}</figcaption>".format(_esc(image.get("caption", ""))) if image.get("caption") else ""
            parts.append('<figure><img src="{}" alt="{}">{}<strong>{}</strong></figure>'.format(source, _esc(image.get("alt", image.get("title", tr(guide, "image_alt_fallback")))), caption, _esc(image.get("title", ""))))
        parts.append('</div><p class="muted">{}</p></section>'.format(_esc(tr(guide, "image_note_html"))))
    # ---- 媒体相册（按笔记分组，本地缓存优先，未命中回退链接） ----
    parts.append(_media_section_html(guide, sources, media_resolved))
    # ---- 逐日行程 ----
    for day in guide.get("days", []):
        parts.append('<section class="day"><h2>{}</h2><p class="muted">{}</p>'.format(_esc(tr(guide, "day_heading_html").format(day.get("day", ""), day.get("title", ""))), _esc(day.get("date", ""))))
        parts.append(_backup_list_html(guide, day.get("backup"), tr(guide, "backup")))
        for item in day.get("items", []):
            rec = item.get("recommendation")
            badge = '<span class="badge">{}</span>'.format(_esc(rec)) if rec else ""
            route = item.get("route_from_previous") or {}
            if route:
                duration = route.get("duration_text") or (tr(guide, "minutes_html").format(route["duration_min"]) if route.get("duration_min") is not None else tr(guide, "duration_unverified"))
                is_drive = _is_drive(route.get("mode"))
                distance = tr(guide, "km_html").format(route["distance_km"]) if route.get("distance_km") is not None else (tr(guide, "distance_unverified_html") if is_drive else "")
                route_html = '<p class="muted">{}</p>'.format(_esc(tr(guide, "transfer_html").format(route.get("mode") or tr(guide, "mode_fallback"), duration, distance, tr(guide, "estimate_paren") if route.get("estimated") else "")))
            else:
                route_html = ""
            source_links = _source_links_html(item.get("source_ids"), sources)
            # _esc 只包模板本身（"来源：{}" 无特殊字符）；链接串必须在转义外插入，否则锚点会被转成纯文本
            source_html = '<p class="score">{}</p>'.format(_esc(tr(guide, "source_html")).format(" · ".join(source_links))) if source_links else ""
            price = '<p>{} {}</p>'.format(_esc(tr(guide, "price_html").format(item.get("price", ""))), _esc(tr(guide, "price_user_note"))) if item.get("price") else ""
            backup_html = _backup_list_html(guide, item.get("backup"), tr(guide, "backup"))
            parts.append('<article class="item"><div class="time">{}–{} {}</div><h3>{}</h3><p>{}</p>{}{}{}{}{}</article>'.format(_esc(item.get("start", "")), _esc(item.get("end", "")), badge, _esc(item.get("name", "")), _esc(item.get("description", "")), route_html, price, source_html, "<p class=\"score\">{}</p>".format(_esc(tr(guide, "confidence_html").format(item["confidence"]))) if item.get("confidence") else "", backup_html))
        parts.append("</section>")
    # ---- 行程统计（表 + 甘特图 + 图例） ----
    parts.append(_stats_section_html(guide))
    # ---- 住宿 / 美食推荐 ----
    for title, key, name_key, detail_keys in ((tr(guide, "hotels"), "hotels", "area", ("name", "reason", "price", "address", "hours", "checked_at", "confidence", "connection")), (tr(guide, "h_foods"), "foods", "name", ("shop", "reason", "price", "address", "hours", "checked_at", "confidence"))):
        rows = guide.get(key, [])
        if rows:
            parts.append('<section class="card"><h2>{}</h2><div class="grid">'.format(_esc(title)))
            for record in rows:
                details = "<br>".join(_esc(record[field]) for field in detail_keys if record.get(field))
                refs = _source_links_html(record.get("source_ids"), sources)
                ref_html = '<p class="score">{}</p>'.format(_esc(tr(guide, "source_html")).format(" · ".join(refs))) if refs else ""
                # 住宿卡片标题优先具体酒店名，否则用区域
                heading = record.get("name") if key == "hotels" and record.get("name") else record.get(name_key, "")
                parts.append('<article><h3>{}</h3><p>{}</p>{}</article>'.format(_esc(heading), details, ref_html))
            parts.append("</div></section>")
    # ---- 商家：餐饮类并入美食语境，其余单列 ----
    if guide.get("businesses"):
        from .render_markdown import _is_food_category

        food_businesses = [business for business in guide["businesses"] if _is_food_category(business.get("category"))]
        other_businesses = [business for business in guide["businesses"] if business not in food_businesses]
        for title, businesses in ((tr(guide, "food_businesses"), food_businesses), (tr(guide, "other_businesses"), other_businesses)):
            if not businesses:
                continue
            parts.append('<section class="card"><h2>{}</h2><div class="grid">'.format(_esc(title)))
            field_labels = (
                (tr(guide, "b_address"), "address"),
                (tr(guide, "b_hours"), "hours"),
                (tr(guide, "b_phone"), "phone"),
                (tr(guide, "b_price"), "price"),
                (tr(guide, "b_checked"), "checked_at"),
                (tr(guide, "ev_confidence"), "confidence"),
            )
            for business in businesses:
                details = "<br>".join("{}：{}".format(_esc(label), _esc(business[key])) for label, key in field_labels if business.get(key))
                refs = _source_links_html(business.get("source_ids"), sources)
                parts.append('<article><h3>{}</h3><p class="muted">{}</p><p>{}</p><p>{}</p><p class="score">{}</p></article>'.format(_esc(business.get("name", "")), _esc(business.get("category", "")), _esc(business.get("reason", "")), details, " · ".join(refs)))
            parts.append('</div><p class="muted">{}</p></section>'.format(_esc(tr(guide, "businesses_note_html"))))
    # ---- 交通 / 避坑 ----
    if guide.get("transport"):
        parts.append('<section class="card"><h2>{}</h2><div class="grid">'.format(_esc(tr(guide, "transport"))))
        for record in guide["transport"]:
            refs = _source_links_html(record.get("source_ids"), sources)
            parts.append('<article><h3>{}</h3><p>{}</p><p>{}</p><p class="score">{}</p></article>'.format(_esc(record.get("title", record.get("mode", tr(guide, "mode_fallback")))), _esc(record.get("detail", "")), _esc(record.get("price", "")), _esc(tr(guide, "source_html")).format(" · ".join(refs))))
        parts.append("</div></section>")
    if guide.get("avoid"):
        parts.append('<section class="card"><h2>{}</h2><ul>'.format(_esc(tr(guide, "avoid"))))
        for record in guide["avoid"]:
            if isinstance(record, dict):
                refs = _source_links_html(record.get("source_ids"), sources)
                # 兼容两种字段写法：wrong/right（规范）与 name/reason（生成端常见），
                # 否则内容为空只剩来源链接
                wrong = record.get("wrong") or record.get("name") or ""
                right = record.get("right") or record.get("reason") or ""
                parts.append('<li><strong>{}</strong>{}<br><strong>{}</strong>{}<p class="score">{}</p></li>'.format(_esc(tr(guide, "avoid_html_prefix")), _esc(wrong), _esc(tr(guide, "suggest_html_prefix")), _esc(right), " · ".join(refs)))
            else:
                parts.append("<li>{}</li>".format(_esc(record)))
        parts.append("</ul></section>")
    # ---- 预算：分项表 + 可解析时叠加饼图 ----
    budget = guide.get("budget", {})
    if budget.get("profiles"):
        parts.append('<section class="card"><h2>{}</h2><div class="grid">'.format(_esc(tr(guide, "h_budget"))))
        pie_data = budget_pie_data(guide)
        for profile_name, profile in budget["profiles"].items():
            rows = "".join("<tr><td>{}</td><td>{}</td></tr>".format(_esc(category), _esc(amount)) for category, amount in profile.get("categories", {}).items())
            pie = _budget_pie_svg(guide, profile_name, pie_data.get(profile_name)) if profile_name in pie_data else ""
            parts.append('<article><h3>{}</h3><table>{}<tr><th>{}</th><th>{}</th></tr></table>{}<p class="muted">{}</p></article>'.format(_esc(profile_name), rows, _esc(tr(guide, "budget_total_label")), _esc(profile.get("total", tr(guide, "budget_pending"))), pie, _esc(tr(guide, "budget_note_html"))))
        parts.append("</div></section>")
    # ---- 行前清单（带日期的项与 ICS 全天事件对应） ----
    if guide.get("checklist"):
        entries = []
        for entry in guide["checklist"]:
            if not isinstance(entry, dict):
                continue
            date_badge = ' <span class="badge">{}</span>'.format(_esc(entry["date"])) if entry.get("date") else ""
            detail = "<p>{}</p>".format(_esc(entry["detail"])) if entry.get("detail") else ""
            entries.append("<li><strong>{}{}</strong>{}</li>".format(_esc(entry.get("title", "")), date_badge, detail))
        if entries:
            parts.append('<section class="card"><h2>{}</h2><ul>{}</ul><p class="muted">{}</p></section>'.format(_esc(tr(guide, "checklist")), "".join(entries), _esc(tr(guide, "checklist_note_html"))))
    if guide.get("tips"):
        parts.append('<section class="card"><h2>{}</h2><ul>{}</ul></section>'.format(_esc(tr(guide, "h_tips")), "".join("<li>{}</li>".format(_esc(tip)) for tip in guide["tips"])))
    # ---- 证据卡 ----
    if guide.get("evidence"):
        parts.append('<section class="card"><h2>{}</h2><div class="grid">'.format(_esc(tr(guide, "evidence"))))
        for card in guide["evidence"]:
            if not isinstance(card, dict):
                continue
            claim = card.get("claim") or card.get("summary") or card.get("topic") or tr(guide, "evidence_fallback")
            meta_bits = "<br>".join("{}：{}".format(_esc(label), _esc(card[key])) for label, key in ((tr(guide, "ev_topic"), "topic"), (tr(guide, "ev_status"), "status"), (tr(guide, "ev_confidence"), "confidence"), (tr(guide, "ev_checked"), "checked_at")) if card.get(key))
            caveat = '<p class="muted">{}</p>'.format(_esc(card["caveat"])) if card.get("caveat") else ""
            refs = _source_links_html(card.get("source_ids"), sources)
            ref_html = '<p class="score">{}</p>'.format(_esc(tr(guide, "source_html")).format(" · ".join(refs))) if refs else ""
            parts.append('<article class="route-leg"><h3>{}</h3><p>{}</p><p class="muted">{}</p>{}{}</article>'.format(_esc(claim), _esc(card.get("summary", "")), meta_bits, caveat, ref_html))
        parts.append("</div></section>")
    # ---- 来源清单（编号列表） ----
    parts.append('<section class="card"><h2>{}</h2><ol>'.format(_esc(tr(guide, "h_sources"))))
    for source in guide.get("sources", []):
        label = _esc(source.get("title", source.get("id", "source")))
        link = '<a href="{}" target="_blank" rel="noopener">{}</a>'.format(_esc(source.get("url")), label) if source.get("url") else label
        parts.append("<li>{} · {}</li>".format(link, _esc(tr(guide, "source_type_checked_html")).format(_esc(source.get("type", "")), _esc(source.get("checked_at", "")))))
    parts.append("</ol><p class=\"muted\">{}</p></section>".format(_esc(tr(guide, "sources_note_html"))))
    # ---- 待核实警告（必须进产物，不能只留在控制台） ----
    for issue in report.get("warnings", []) + report.get("conflicts", []):
        parts.append('<p class="warn">{}</p>'.format(_esc(tr(guide, "warning_line_html").format(issue.get("code"), issue.get("message")))))
    parts.append('<footer>{}</footer></main></body></html>'.format(_esc(tr(guide, "footer_html"))))
    return "\n".join(parts)
