"""GeoJSON 导出：只输出经过校验的坐标，含有序路线 LineString 与 bbox。

坐标非法的点直接丢弃（不猜、不修）：宁可少一个点，也不输出
错误位置误导导航。所有点用于计算 bbox，方便地图工具自动缩放。
"""

from .common import _coordinate_error
from .strings import tr


def geojson_data(guide):
    """生成 FeatureCollection：行程项点 + 路线停靠点 + 路线线。"""
    features = []
    points = []

    def _add_point(coords, properties):
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": coords}, "properties": properties})
        points.append(coords)

    # 行程项坐标点（属性带天序号/日期/时间窗，供弹窗与样式使用）
    for day in guide.get("days", []):
        for item in day.get("items", []):
            coords = item.get("coords")
            if isinstance(coords, list) and len(coords) == 2 and not _coordinate_error(coords):
                _add_point(coords, {"name": item.get("name", ""), "day": day.get("day"), "date": day.get("date"), "start": item.get("start"), "end": item.get("end"), "type": item.get("type", "spot")})
    # 路线停靠点与连线（连线按 stops 声明顺序，非实际道路）
    route = guide.get("route", {}) or {}
    stops = route.get("stops", []) if isinstance(route.get("stops"), list) else []
    stop_points = []
    for stop in stops:
        if not isinstance(stop, dict):
            continue
        coords = stop.get("coords")
        if isinstance(coords, list) and len(coords) == 2 and not _coordinate_error(coords):
            stop_points.append(coords)
            _add_point(coords, {"name": stop.get("name", ""), "type": "stop", "day": stop.get("day")})
    if len(stop_points) >= 2:
        features.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": stop_points}, "properties": {"name": tr(guide, "geojson_route_line"), "type": "route"}})
    collection = {"type": "FeatureCollection", "features": features}
    # bbox：全部有效点的经纬度极值
    if points:
        collection["bbox"] = [
            min(point[0] for point in points),
            min(point[1] for point in points),
            max(point[0] for point in points),
            max(point[1] for point in points),
        ]
    return collection
