"""KML 导出（Google Earth）：校验过的点位 + 有序路线连线。

与其他文本产物一致使用 LF 换行。坐标非法的点直接丢弃，
不猜测位置。
"""

from xml.sax.saxutils import escape

from .common import _coordinate_error
from .strings import tr


def _coord_text(coords):
    """KML 坐标文本：经度,纬度,高程（高程固定为 0）。"""
    return "{},{},0".format(coords[0], coords[1])


def _valid_coords(value):
    """坐标有效性：二元列表且通过极值/数值校验。"""
    return isinstance(value, list) and len(value) == 2 and not _coordinate_error(value)


def kml_text(guide):
    """渲染 KML 文档：路线 Folder（连线 + 停靠点）+ 每日 Folder（行程点）。"""
    meta = guide.get("meta", {})
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        "<Document>",
        "<name>{}</name>".format(escape(str(meta.get("title", tr(guide, "title_fallback"))))),
    ]
    route = guide.get("route", {}) or {}
    stops = route.get("stops", []) if isinstance(route.get("stops"), list) else []
    stop_points = [stop.get("coords") for stop in stops if isinstance(stop, dict) and _valid_coords(stop.get("coords"))]
    # 路线 Folder：至少两个有效停靠点才画连线
    if len(stop_points) >= 2:
        lines.extend([
            "<Folder>",
            "<name>{}</name>".format(escape(tr(guide, "route"))),
            "<Placemark><name>{}</name><LineString><coordinates>{}</coordinates></LineString></Placemark>".format(
                escape(tr(guide, "geojson_route_line")),
                " ".join(_coord_text(coords) for coords in stop_points),
            ),
        ])
        for stop in stops:
            if not isinstance(stop, dict) or not _valid_coords(stop.get("coords")):
                continue
            lines.append("<Placemark><name>{}</name><Point><coordinates>{}</coordinates></Point></Placemark>".format(
                escape(str(stop.get("name", ""))), _coord_text(stop["coords"])))
        lines.append("</Folder>")
    # 每日 Folder：当天带坐标的行程项；整天无坐标则跳过该 Folder
    for day in guide.get("days", []):
        if not isinstance(day, dict):
            continue
        day_items = [
            (item.get("name", ""), item.get("coords"))
            for item in (day.get("items", []) or [])
            if isinstance(item, dict) and _valid_coords(item.get("coords"))
        ]
        if not day_items:
            continue
        lines.extend(["<Folder>", "<name>Day {} · {}</name>".format(escape(str(day.get("day", ""))), escape(str(day.get("date", ""))))])
        for name, coords in day_items:
            lines.append("<Placemark><name>{}</name><Point><coordinates>{}</coordinates></Point></Placemark>".format(escape(str(name)), _coord_text(coords)))
        lines.append("</Folder>")
    lines.extend(["</Document>", "</kml>"])
    return "\n".join(lines) + "\n"
