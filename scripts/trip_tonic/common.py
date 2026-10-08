"""共享常量与工具函数。

整个构建管线（校验、统计、渲染、导出）共用的基础设施都在这里：
- 领域常量：交通方式规范 token、节奏强度上限、来源类型白名单
- 严格 JSON 解析（重复键直接报错，防止上游工具生成含糊数据）
- 日期/时间/坐标/价格等标量字段的宽松解析与校验
- CLI 输出辅助（强制 UTF-8、JSON 打印）
"""

import json
import math
import re
import sys
from datetime import date
from pathlib import Path

# 仓库根目录（scripts/trip_tonic/common.py 向上两级），用于定位 references/ 与 examples/
REPO_ROOT = Path(__file__).resolve().parents[2]

# HH:MM 24 小时制时间格式
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
# sources[].type 允许的取值；user=用户笔记，official=官方，estimate=估算等
SOURCE_TYPES = {"official", "search", "user", "estimate", "general"}
# 节奏 -> (每日最大时间跨度(分钟), 每日最多非休息活动项数)
# validator 的 PACE_OVERLOAD / TIME_WINDOW 检查以此为准
PACE_LIMITS = {"relaxed": (600, 6), "balanced": (720, 8), "intensive": (840, 10)}

# 规范交通方式 token。guide.json 里的自由文本 mode 合法，但：
# - validator 对无法识别的 mode 给出 MODE_UNRECOGNIZED 警告
# - 所有逻辑（自驾统计、路线判断）都先经 normalize_mode 归一到这些 token，
#   中英文同义词行为一致
CANONICAL_MODES = ("drive", "walk", "bus", "metro", "train", "flight", "taxi", "bike", "boat", "cable_car", "shuttle")
# 同义词表：strip().lower() 后查表；中文词不需要 lower 但也无副作用
_MODE_ALIASES = {
    "drive": "drive", "driving": "drive", "car": "drive", "自驾": "drive", "租车自驾": "drive", "开车": "drive", "汽车": "drive",
    "walk": "walk", "walking": "walk", "步行": "walk", "徒步": "walk",
    "bus": "bus", "巴士": "bus", "公交": "bus", "公交车": "bus", "大巴": "bus",
    "metro": "metro", "地铁": "metro", "轨道交通": "metro", "subway": "metro",
    "train": "train", "rail": "train", "火车": "train", "高铁": "train", "动车": "train", "铁路": "train",
    "flight": "flight", "air": "flight", "plane": "flight", "飞机": "flight", "航班": "flight",
    "taxi": "taxi", "cab": "taxi", "出租车": "taxi", "打车": "taxi", "的士": "taxi", "网约车": "taxi",
    "bike": "bike", "bicycle": "bike", "骑行": "bike", "自行车": "bike",
    "boat": "boat", "ferry": "boat", "轮渡": "boat", "船": "boat", "游船": "boat",
    "cable_car": "cable_car", "缆车": "cable_car", "索道": "cable_car", "ropeway": "cable_car",
    "shuttle": "shuttle", "班车": "shuttle", "接驳车": "shuttle", "景区接驳": "shuttle",
}


def _issue(level, code, message, path):
    """构造一条诊断记录：level(error/warning)、code、message、JSON 路径。"""
    return {"level": level, "code": code, "message": message, "path": path}


def _valid_date(value):
    """解析 YYYY-MM-DD；非法返回 None（调用方据此决定报 error 还是跳过）。"""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _minutes(value):
    """把 "HH:MM" 转成自当天 0 点起的分钟数；格式非法返回 None。"""
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        return None
    hour, minute = (int(part) for part in value.split(":"))
    return hour * 60 + minute


def normalize_mode(mode):
    """把自由文本交通方式映射到规范 token；无法识别返回 None。"""
    if not isinstance(mode, str):
        return None
    return _MODE_ALIASES.get(mode.strip().lower())


def _is_drive(mode):
    """判断某段交通是否为自驾（先做同义词归一）。"""
    return normalize_mode(mode) == "drive"


def _leading_number(value):
    """从价格/合计字符串中提取第一个数字，如 "约 3000 元" -> 3000.0。

    用于预算一致性检查和 compare 的预算语义 diff；解析不出返回 None。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
        return float(match.group()) if match else None
    return None


def _coordinate_error(value):
    """校验 [经度, 纬度] 坐标；合法返回 None，否则返回中文错误说明。

    GeoJSON/KML 只输出通过校验的点，杜绝把错误坐标渲染进地图产物。
    """
    if not isinstance(value, list) or len(value) != 2:
        return "坐标必须是 [经度, 纬度]"
    longitude, latitude = value
    if any(isinstance(number, bool) or not isinstance(number, (int, float)) for number in value):
        return "经纬度必须是数值"
    if any(not math.isfinite(number) for number in value):
        return "经纬度必须是有限数值"
    if not (-180 <= longitude <= 180) or not (-90 <= latitude <= 90):
        return "经度范围为 -180 至 180，纬度范围为 -90 至 90"
    return None


def _reject_duplicate_keys(pairs):
    """json.loads 的 object_pairs_hook：出现重复键立即抛 ValueError。

    默认行为是静默覆盖，容易掩盖上游生成器的 bug（本项目的 schema 就踩过坑），
    因此所有 JSON 输入都走这条严格路径。
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON 对象存在重复键：{}".format(key))
        result[key] = value
    return result


def load_json_text(text):
    """严格解析 JSON 文本：重复键抛 ValueError 而不是静默覆盖。"""
    return json.loads(text, object_pairs_hook=_reject_duplicate_keys)


def load_json_file(path):
    """以 UTF-8 读取文件并严格解析（重复键报错）。"""
    return load_json_text(Path(path).read_text(encoding="utf-8"))


def _force_utf8_output():
    """把 stdout/stderr 切到 UTF-8，避免 Windows GBK 控制台打印中文 JSON 乱码。"""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass


def _print_json(payload):
    """以缩进 JSON 形式输出 CLI 结果（ensure_ascii=False 保留中文）。"""
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _source_map(guide):
    """sources 列表转 {id: source} 字典，供渲染时按 source_ids 反查标题/链接。"""
    return {source.get("id"): source for source in guide.get("sources", []) if isinstance(source, dict)}


def _atomic_write_many(artifacts):
    """批量原子写：全部暂存成功后统一替换；任一失败清理暂存并上抛。

    artifacts 为 (路径, 内容, 换行符) 列表；暂存文件与目标同目录
    （os.replace 同盘原子）。写完即 fsync，掉电也能保住已写内容。
    """
    import os
    import tempfile
    from pathlib import Path

    staged = []
    try:
        for path, content, newline in artifacts:
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=str(path.parent))
            staged.append((temporary_name, path))
            with os.fdopen(descriptor, "w", encoding="utf-8", newline=newline) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        # 全部暂存成功，才逐个原子替换
        for temporary_name, path in staged:
            os.replace(temporary_name, str(path))
    except Exception:
        # 失败清理：删除尚未替换的暂存文件，保持旧产物原样
        for temporary_name, _ in staged:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
        raise
