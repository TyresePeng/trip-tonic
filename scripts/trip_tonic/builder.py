"""产物构建器：先校验、全部在内存渲染，再原子替换输出文件。

设计要点：
- 任何渲染失败都不会污染旧产物（先暂存后统一 os.replace）
- 文本产物统一 LF 换行，跨平台字节级稳定（ICS 例外，
  按 RFC 5545 用 CRLF）
- 结构错误/行程冲突/strict 下的警告都会拒绝构建
- media_cache（可选）：把 fetch-media 下载的本地缓存解析进产物，
  图片内嵌 data URI，视频拷贝到产物目录 media/ 下相对引用
"""

import json
from pathlib import Path

from .common import _atomic_write_many  # noqa: F401  （cli 从 builder 导入此名，保持兼容）

from .media import resolve_media
from .normalize import normalized_guide
from .render_geojson import geojson_data
from .render_html import html_text
from .render_ics import ics_text
from .render_kml import kml_text
from .render_markdown import markdown_text
from .stats import guide_stats
from .validator import validate_guide


def build(guide, output_dir, media_root=None, today=None, strict=False, online_map=False, media_cache=None):
    """校验并渲染 7 个产物到 output_dir，返回结果字典。

    拒绝条件：结构错误、行程冲突、（strict 模式下）存在警告。
    media_cache：fetch-media 的缓存目录；命中缓存的媒体进相册
    （图片内嵌、视频拷到 output/media/），未命中保持链接卡片。
    """
    report = validate_guide(guide, today=today)
    if not report["valid"] or report["conflicts"]:
        return {"status": "error", "message": "结构错误或行程冲突未解决", "report": report, "files": []}
    if strict and report["warnings"]:
        return {"status": "error", "message": "存在未解决的警告（--strict 模式拒绝构建）", "report": report, "files": []}
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    # 媒体缓存解析：视频文件此时拷入 output/media/（渲染前完成，失败即整体回退）
    media_resolved = resolve_media(guide, media_cache, output) if media_cache else {}
    normalized = output / "guide.normalized.json"
    markdown = output / "guide.md"
    html_file = output / "guide.html"
    calendar = output / "guide.ics"
    geojson = output / "guide.geojson"
    kml = output / "guide.kml"
    validation = output / "validation.json"
    stats = guide_stats(guide)
    # 全部产物先在内存渲染，之后才替换既有输出；文本产物统一 LF 换行
    # 保证跨平台字节稳定（ICS 按 RFC 5545 保留 CRLF，newline=""）。
    artifacts = [
        (normalized, json.dumps(normalized_guide(guide), ensure_ascii=False, indent=2) + "\n", "\n"),
        (markdown, markdown_text(guide, report, media_resolved=media_resolved), "\n"),
        (html_file, html_text(guide, report, media_root=media_root, online_map=online_map, media_resolved=media_resolved), "\n"),
        (calendar, ics_text(guide), ""),
        (geojson, json.dumps(geojson_data(guide), ensure_ascii=False, indent=2) + "\n", "\n"),
        (kml, kml_text(guide), "\n"),
        (validation, json.dumps(report, ensure_ascii=False, indent=2) + "\n", "\n"),
    ]
    _atomic_write_many(artifacts)
    return {
        "status": "ok",
        "report": report,
        "stats": stats,
        "media_resolved": len(media_resolved),
        "files": [str(path) for path in (html_file, markdown, calendar, geojson, kml, normalized, validation)],
    }
