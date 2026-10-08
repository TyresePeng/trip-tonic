"""命令行入口：validate / build / init / compare / migrate / serve / lint-research。

所有命令输出单行 JSON（stdout 强制 UTF-8），便于上层 Agent 解析。
退出码约定：0 成功；1 校验失败/参数值非法/IO 错误。
"""

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

from .common import REPO_ROOT, _force_utf8_output, _print_json, _valid_date, load_json_file
from .compare import _daily, _stops, _budgets, _summary, compare_guides
from .migrate import KNOWN_VERSIONS, MigrateError, migrate_guide
from .research import research_record_issues
from .serve import serve_command
from .builder import _atomic_write_many
from .validator import validate_guide

import json

# 节奏偏好可选值（与 common.PACE_LIMITS 对应）
PACE_CHOICES = ("relaxed", "balanced", "intensive")


def _cmd_init(args):
    """init：从模板生成 guide.json 脚手架（按天数复制模板日并改编号/日期）。"""
    template_path = REPO_ROOT / "examples" / "guide-template.json"
    start = _valid_date(args.start_date)
    if args.start_date and not start:
        _print_json({"status": "error", "message": "--start-date 格式必须为 YYYY-MM-DD"})
        return 1
    if start is None:
        start = date.today()
    if args.days < 1:
        _print_json({"status": "error", "message": "--days 至少为 1"})
        return 1
    # pace 由 argparse choices 把关，此处仅兜底
    if args.pace not in PACE_CHOICES:
        _print_json({"status": "error", "message": "--pace 必须为 {}".format("/".join(PACE_CHOICES))})
        return 1
    if args.travelers < 1:
        _print_json({"status": "error", "message": "--travelers 至少为 1"})
        return 1
    guide = load_json_file(template_path)
    guide["meta"]["start_date"] = start.isoformat()
    guide["meta"]["days"] = args.days
    if args.title:
        guide["meta"]["title"] = args.title
    if args.destination:
        guide["meta"]["destination"] = args.destination
    if args.origin:
        guide["meta"]["origin"] = args.origin
    guide["meta"]["travelers"] = args.travelers
    guide["preferences"]["pace"] = args.pace
    # 以模板首日为蓝本复制出 N 天（深拷贝防共享引用），改编号与日期
    template_day = guide["days"][0]
    guide["days"] = []
    for index in range(args.days):
        day = json.loads(json.dumps(template_day))
        day["day"] = index + 1
        day["date"] = (start + timedelta(days=index)).isoformat()
        guide["days"].append(day)
    # 明确标注这是脚手架，占位值必须替换
    guide["meta"]["assumptions"] = ["由 init 脚手架生成；模板占位值必须替换为真实研究内容"]
    output = Path(args.directory) / "guide.json"
    if output.exists() and not args.force:
        _print_json({"status": "error", "message": "{} 已存在；确认后可使用 --force 覆盖".format(output)})
        return 1
    _atomic_write_many([(output, json.dumps(guide, ensure_ascii=False, indent=2) + "\n", "\n")])
    _print_json({"status": "ok", "file": str(output), "start_date": start.isoformat(), "days": args.days, "note": "模板占位值必须替换为真实研究内容后才能构建"})
    return 0


def _cmd_compare(args):
    """compare：对比两份攻略的结构差异、语义变化与取舍摘要。"""
    left_guide = load_json_file(args.left)
    right_guide = load_json_file(args.right)
    comparison = compare_guides(left_guide, right_guide)
    _print_json({
        "status": "ok",
        "left": {"file": args.left, **_summary(left_guide)},
        "right": {"file": args.right, **_summary(right_guide)},
        "differences": comparison["differences"],
        "semantic": comparison["semantic"],
        "tradeoffs": comparison["tradeoffs"],
        "note": "对比为结构摘要与逐项变化，不代表两份行程的研究质量差异",
    })
    return 0


def _cmd_migrate(args):
    """migrate：升级 schema_version；写回前先通过目标版本校验。"""
    guide_path = Path(args.input)
    guide = load_json_file(guide_path)
    try:
        changed, applied = migrate_guide(guide, target=args.target)
    except MigrateError as error:
        _print_json({"status": "error", "changed": False, "message": str(error)})
        return 1
    if not changed:
        _print_json({"status": "ok", "changed": False, "message": "schema_version 已是 {}，无需迁移".format(args.target)})
        return 0
    # 迁移后先校验：不通过就不写回，避免产出无效文件
    report = validate_guide(guide)
    if not report["valid"]:
        _print_json({"status": "error", "changed": False, "message": "补齐 {} 必需字段后再迁移".format(args.target), "report": report})
        return 1
    _atomic_write_many([(guide_path, json.dumps(guide, ensure_ascii=False, indent=2) + "\n", "\n")])
    _print_json({"status": "ok", "changed": True, "message": "已将 schema_version 升级为 {}{}".format(args.target, "（路径：{}）".format(" → ".join(applied)) if len(applied) > 1 else ""), "file": str(guide_path)})
    return 0


def _cmd_lint_research(args):
    """lint-research：校验研究记录；--strict 下覆盖度警告也视为失败。"""
    record = load_json_file(args.input)
    result = research_record_issues(record)
    _print_json(result)
    clean = result["valid"]
    return 0 if clean and not (args.strict and result["warnings"]) else 1


def _cmd_fetch_media(args):
    """fetch-media：把 sources[].media 的远端链接下载到本地缓存目录。

    失败（如签名链接 403）逐条记录不中断；幂等，已缓存的 URL 跳过。
    """
    guide = load_json_file(args.input)
    from .media import fetch_media

    result = fetch_media(guide, args.cache_dir or str(Path(args.input).parent / "media-cache"), timeout=args.timeout)
    _print_json(result)
    return 0 if result["status"] in ("ok", "partial") else 1


def _cmd_serve(args):
    """serve：启动本地预览（媒体根目录默认取 guide JSON 所在目录）。"""
    return serve_command(
        Path(args.input),
        Path(args.output_dir),
        port=args.port,
        media_root=args.media_root or Path(args.input).parent,
        strict=args.strict,
        watch=not args.no_watch,
        media_cache=args.media_cache,
    )


def main(argv=None):
    """解析子命令并分发；返回进程退出码。"""
    parser = argparse.ArgumentParser(description="TripTonic 结构化攻略校验与构建工具")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="校验 guide JSON")
    validate_parser.add_argument("input")
    validate_parser.add_argument("--today", help="覆盖校验用的当前日期（YYYY-MM-DD），便于测试时效规则")
    validate_parser.add_argument("--strict", action="store_true", help="存在警告时同样返回失败")
    build_parser = subparsers.add_parser("build", help="校验并生成 HTML/Markdown/ICS/GeoJSON/KML")
    build_parser.add_argument("input")
    build_parser.add_argument("--output-dir", required=True)
    build_parser.add_argument("--media-root", help="图片素材根目录，默认取 guide JSON 所在目录")
    build_parser.add_argument("--today", help="覆盖校验用的当前日期（YYYY-MM-DD）")
    build_parser.add_argument("--strict", action="store_true", help="存在未解决警告时拒绝构建")
    build_parser.add_argument("--online-map", action="store_true", help="在 HTML 中嵌入 Leaflet 在线地图（默认保持完全离线）")
    build_parser.add_argument("--media-cache", help="fetch-media 的缓存目录；命中缓存的媒体渲染为相册（图片内嵌、视频拷贝到产物 media/ 目录）")
    init_parser = subparsers.add_parser("init", help="从空白模板生成 guide.json 脚手架")
    init_parser.add_argument("directory")
    init_parser.add_argument("--start-date", help="行程开始日期（默认今天）")
    init_parser.add_argument("--days", type=int, default=1, help="行程天数（默认 1）")
    init_parser.add_argument("--title", help="行程标题（替换模板占位）")
    init_parser.add_argument("--destination", help="目的地（替换模板占位）")
    init_parser.add_argument("--origin", help="出发地（替换模板占位）")
    init_parser.add_argument("--travelers", type=int, default=1, help="同行人数（默认 1）")
    init_parser.add_argument("--pace", default="balanced", choices=PACE_CHOICES, help="节奏偏好（默认 balanced）")
    init_parser.add_argument("--force", action="store_true", help="覆盖已存在的 guide.json")
    compare_parser = subparsers.add_parser("compare", help="结构化对比两份 guide JSON（含语义变化与取舍摘要）")
    compare_parser.add_argument("left")
    compare_parser.add_argument("right")
    migrate_parser = subparsers.add_parser("migrate", help="将旧版 schema_version 升级到目标版本")
    migrate_parser.add_argument("input")
    migrate_parser.add_argument("--target", default="1.0", help="目标 schema_version（默认 1.0；可用：{}）".format("/".join(KNOWN_VERSIONS)))
    serve_parser = subparsers.add_parser("serve", help="本地预览构建产物，guide.json 变更时自动重建")
    serve_parser.add_argument("input")
    serve_parser.add_argument("--output-dir", required=True)
    serve_parser.add_argument("--port", type=int, default=8000, help="预览端口（默认 8000，传 0 自动分配）")
    serve_parser.add_argument("--media-root", help="图片素材根目录，默认取 guide JSON 所在目录")
    serve_parser.add_argument("--strict", action="store_true", help="存在未解决警告时拒绝构建")
    serve_parser.add_argument("--no-watch", action="store_true", help="禁用自动重建，仅静态预览")
    serve_parser.add_argument("--media-cache", help="fetch-media 的缓存目录；命中缓存的媒体渲染为相册")
    fetch_media_parser = subparsers.add_parser("fetch-media", help="下载 sources[].media 的图片/视频到本地缓存（幂等，可重复执行）")
    fetch_media_parser.add_argument("input")
    fetch_media_parser.add_argument("--cache-dir", help="缓存目录（默认取 guide JSON 所在目录下的 media-cache）")
    fetch_media_parser.add_argument("--timeout", type=int, default=30, help="单个文件下载超时秒数（默认 30）")
    lint_research_parser = subparsers.add_parser("lint-research", help="校验研究记录 JSON 的结构与覆盖度")
    lint_research_parser.add_argument("input")
    lint_research_parser.add_argument("--strict", action="store_true", help="存在覆盖度警告时同样返回失败")
    args = parser.parse_args(argv)
    # Windows 控制台默认 GBK：强制 stdout/stderr 切 UTF-8，保证 JSON 中文不乱码
    _force_utf8_output()
    try:
        # ---- 独立子命令先行分发 ----
        if args.command == "init":
            return _cmd_init(args)
        if args.command == "compare":
            return _cmd_compare(args)
        if args.command == "migrate":
            return _cmd_migrate(args)
        if args.command == "lint-research":
            return _cmd_lint_research(args)
        if args.command == "fetch-media":
            return _cmd_fetch_media(args)
        if args.command == "serve":
            return _cmd_serve(args)
        # ---- validate / build 共享加载与 --today 解析 ----
        guide_path = Path(args.input)
        guide = load_json_file(guide_path)
        today = None
        if getattr(args, "today", None):
            today = _valid_date(args.today)
            if today is None:
                _print_json({"status": "error", "message": "--today 格式必须为 YYYY-MM-DD"})
                return 1
        if args.command == "validate":
            result = validate_guide(guide, today=today)
            _print_json(result)
            clean = result["valid"] and not result["conflicts"]
            return 0 if clean and not (args.strict and result["warnings"]) else 1
        # 剩余命令即 build；延迟导入避免与 serve 循环依赖
        from .builder import build

        result = build(guide, args.output_dir, media_root=args.media_root or guide_path.parent, today=today, strict=args.strict, online_map=args.online_map, media_cache=args.media_cache)
        _print_json(result)
        return 0 if result["status"] == "ok" else 1
    except (OSError, ValueError) as error:
        # 文件不存在/JSON 损坏等统一转为 JSON 错误输出
        _print_json({"status": "error", "message": str(error)})
        return 1


if __name__ == "__main__":
    sys.exit(main())
