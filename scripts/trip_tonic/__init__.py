"""TripTonic 包入口：校验结构化攻略数据并构建可携带的产物。

公开 API 统一从这里重导出，供 `from scripts.trip_tonic import ...`
调用（测试即按此方式导入）。入口脚本 scripts/trip_tonic.py 是兼容 shim，
包目录优先于同名文件，两种运行方式均可用。
"""

from .builder import build
from .cli import main
from .compare import compare_guides
from .common import normalize_mode
from .media import fetch_media
from .migrate import migrate_guide
from .normalize import normalized_guide
from .render_geojson import geojson_data
from .render_html import html_text
from .render_ics import ics_text
from .render_kml import kml_text
from .render_markdown import markdown_text
from .research import research_record_issues
from .stats import guide_stats
from .validator import validate_guide

__all__ = [
    "build",
    "compare_guides",
    "fetch_media",
    "geojson_data",
    "guide_stats",
    "html_text",
    "ics_text",
    "kml_text",
    "main",
    "markdown_text",
    "migrate_guide",
    "normalize_mode",
    "normalized_guide",
    "research_record_issues",
    "validate_guide",
]
