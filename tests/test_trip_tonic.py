from html.parser import HTMLParser
import functools
import http.server
import io
import json
import base64
import tempfile
import threading
import unittest
import urllib.request
from contextlib import redirect_stdout
from datetime import date, datetime, timezone
from unittest.mock import patch
from pathlib import Path

from scripts.trip_tonic import (
    build,
    compare_guides,
    geojson_data,
    guide_stats,
    ics_text,
    kml_text,
    main,
    normalized_guide,
    normalize_mode,
    research_record_issues,
    validate_guide,
)
from scripts.trip_tonic.common import load_json_text
from scripts.trip_tonic.schema import SchemaCorruptError
from scripts.trip_tonic.serve import rebuild as serve_rebuild
from scripts.trip_tonic import serve as serve_module


def sample_guide():
    """最小合法攻略：单日两行程项（含自驾接驳/坐标/来源），供各测试改写。"""
    return {
        "schema_version": "1.0",
        "meta": {"title": "测试旅行", "destination": "测试地", "language": "zh-CN", "start_date": "2026-09-23", "days": 1, "travelers": 2},
        "preferences": {"pace": "balanced"},
        "sources": [{"id": "xhs-1", "title": "真实体验笔记", "url": "https://example.com/note", "type": "user", "checked_at": "2026-09-22"}],
        "route": {
            "overview": "A往返B的示意路线",
            "stops": [{"name": "A"}, {"name": "B"}],
            "legs": [{"from": "A", "to": "B", "mode": "drive", "duration_min": 30, "estimated": True, "source_ids": ["xhs-1"]}],
        },
        "businesses": [{"name": "商家甲", "category": "餐厅", "reason": "示例推荐", "source_ids": ["xhs-1"]}],
        "days": [{"day": 1, "date": "2026-09-23", "title": "轻松游", "items": [
            {"name": "地点A", "type": "spot", "start": "09:00", "end": "10:00", "coords": [91.1, 29.6], "source_ids": ["xhs-1"]},
            {"name": "地点B", "type": "meal", "start": "10:30", "end": "11:30", "route_from_previous": {"duration_min": 20, "estimated": True, "mode": "drive"}},
        ]}],
    }


def multi_day_guide():
    """两日攻略：深拷贝首日为 Day2（改编号/日期），内容与首日相同。"""
    guide = sample_guide()
    guide["meta"]["days"] = 2
    second_day = json.loads(json.dumps(guide["days"][0]))
    second_day["day"] = 2
    second_day["date"] = "2026-09-24"
    guide["days"].append(second_day)
    return guide


class TripTonicTests(unittest.TestCase):
    def test_valid_guide(self):
        report = validate_guide(sample_guide(), today=__import__("datetime").date(2026, 9, 23))
        self.assertTrue(report["valid"])
        self.assertEqual(report["conflicts"], [])

    def test_detects_time_overlap_and_short_transfer(self):
        guide = sample_guide()
        guide["days"][0]["items"][1]["start"] = "09:45"
        guide["days"][0]["items"][1]["route_from_previous"]["duration_min"] = 25
        report = validate_guide(guide)
        codes = {issue["code"] for issue in report["conflicts"]}
        self.assertIn("TIME_OVERLAP", codes)
        self.assertIn("TRANSIT_TOO_SHORT", codes)

    def test_detects_missing_source_reference_as_warning(self):
        guide = sample_guide()
        guide["days"][0]["items"][0]["source_ids"] = ["missing"]
        report = validate_guide(guide)
        self.assertIn("SOURCE_MISSING", {issue["code"] for issue in report["warnings"]})

    def test_geojson_uses_verified_coordinates_only(self):
        data = geojson_data(sample_guide())
        self.assertEqual(len(data["features"]), 1)
        self.assertEqual(data["features"][0]["geometry"]["coordinates"], [91.1, 29.6])
        guide = sample_guide()
        guide["days"][0]["items"][0]["coords"] = [91.1, 190]
        report = validate_guide(guide)
        self.assertIn("COORDINATES", {issue["code"] for issue in report["errors"]})
        data = geojson_data(guide)
        self.assertEqual(data["features"], [])
        guide["days"][0]["items"][0]["coords"] = ["91.1", 29.6]
        self.assertIn("COORDINATES", {issue["code"] for issue in validate_guide(guide)["errors"]})

    def test_malformed_nested_data_returns_validation_errors(self):
        guide = sample_guide()
        guide["route"]["stops"] = [None]
        guide["route"]["legs"] = ["bad leg"]
        guide["hotels"] = [None]
        report = validate_guide(guide)
        self.assertFalse(report["valid"])
        self.assertIn("ROUTE_STOP", {issue["code"] for issue in report["errors"]})
        self.assertIn("ROUTE_LEG", {issue["code"] for issue in report["errors"]})
        self.assertIn("RECORD", {issue["code"] for issue in report["errors"]})

    def test_schema_detects_required_fields_and_bad_types(self):
        guide = sample_guide()
        guide["days"][0]["items"][0]["start"] = 23
        report = validate_guide(guide)
        codes = {issue["code"] for issue in report["errors"]}
        self.assertIn("SCHEMA_TYPE", codes)
        self.assertIn("ITEM_TIME", codes)

    def test_ics_uses_floating_local_datetime_and_folds_long_lines(self):
        from scripts.trip_tonic import ics_text

        guide = sample_guide()
        guide["days"][0]["items"][0]["name"] = "很长的行程名称" * 20
        text = ics_text(guide)
        self.assertIn("DTSTART:20260923T090000", text)
        self.assertNotIn("DTSTART;TZID=", text)
        physical_lines = text.split("\r\n")
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in physical_lines))
        self.assertTrue(any(line.startswith(" ") for line in physical_lines))

    def test_build_does_not_replace_existing_files_when_rendering_fails(self):
        guide = sample_guide()
        with tempfile.TemporaryDirectory() as directory:
            existing = Path(directory) / "guide.md"
            existing.write_text("keep existing", encoding="utf-8")
            with patch("scripts.trip_tonic.builder.html_text", side_effect=OSError("render failed")):
                with self.assertRaises(OSError):
                    build(guide, directory)
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep existing")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_template_validates_with_expected_missing_recommendation_warnings(self):
        template_path = Path(__file__).resolve().parent.parent / "examples" / "guide-template.json"
        guide = json.loads(template_path.read_text(encoding="utf-8"))
        report = validate_guide(guide)
        self.assertTrue(report["valid"])
        self.assertEqual(report["errors"], [])

    def test_route_duration_validation_and_markdown_overview(self):
        from scripts.trip_tonic import markdown_text

        guide = sample_guide()
        text = markdown_text(guide)
        self.assertIn("## 总体路线", text)
        self.assertIn("路线顺序（非比例）：A → B", text)
        self.assertIn("约30分钟", text)
        guide["route"]["legs"][0]["duration_text"] = "约30-45分钟"
        self.assertIn("约30-45分钟", markdown_text(guide))
        self.assertIn("## 餐饮店铺推荐", text)
        guide["route"]["legs"][0]["duration_min"] = -5
        self.assertIn("ROUTE_DURATION", {issue["code"] for issue in validate_guide(guide)["errors"]})

    def test_missing_visuals_recommendations_and_drive_details_are_reported(self):
        from scripts.trip_tonic import markdown_text

        guide = sample_guide()
        guide["route"]["legs"][0]["mode"] = "自驾"
        guide["route"]["legs"][0].pop("duration_min")
        guide["route"]["legs"][0].pop("duration_text", None)
        guide["sources"][0]["media"] = [{"type": "image", "url": "https://example.com/note.jpg", "description": "山谷公路与远处雪山"}]
        guide["hotels"] = [{"name": "旅店甲", "area": "市区", "reason": "方便休息", "source_ids": ["xhs-1"]}]
        guide["foods"] = [{"name": "餐馆甲", "shop": "招牌菜", "reason": "有来源的体验推荐", "source_ids": ["xhs-1"]}]
        guide["businesses"] = [{"name": "租车服务甲", "category": "租车", "reason": "提供车型信息", "source_ids": ["xhs-1"]}]
        guide["days"][0]["items"][1]["route_from_previous"]["mode"] = "自驾"
        report = validate_guide(guide)
        codes = {issue["code"] for issue in report["warnings"]}
        self.assertIn("DRIVE_DURATION_MISSING", codes)
        self.assertIn("DRIVE_DISTANCE_MISSING", codes)
        self.assertNotIn("RECOMMENDATIONS_MISSING", codes)
        self.assertNotIn("FOOD_SHOP_MISSING", codes)
        self.assertNotIn("VISUALS_MISSING", codes)
        text = markdown_text(guide)
        self.assertIn("## 旅行影像", text)
        self.assertIn("山谷公路与远处雪山", text)
        self.assertIn("(https://example.com/note.jpg)", text)
        self.assertIn("里程待核实", text)

    def test_build_renders_suggestions_and_missing_data_warnings(self):
        guide = sample_guide()
        guide["route"]["legs"][0]["mode"] = "自驾"
        guide["route"]["legs"][0].pop("duration_min")
        guide["route"]["legs"][0].pop("duration_text", None)
        guide["days"][0]["items"][1]["route_from_previous"]["mode"] = "自驾"
        with tempfile.TemporaryDirectory() as directory:
            result = build(guide, directory)
            rendered = (Path(directory) / "guide.html").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "ok")
        # 视觉层已收敛为本地图片+媒体相册：无素材时纯文字，不再生成插画区
        self.assertNotIn("图片示例", rendered)
        self.assertNotIn('<svg class="illustration"', rendered)
        self.assertNotIn("旅行影像", rendered)
        self.assertIn("VISUALS_MISSING", rendered)
        self.assertIn("DRIVE_DURATION_MISSING", rendered)
        self.assertIn("RECOMMENDATIONS_MISSING", rendered)
        self.assertIn("前序接驳：自驾", rendered)
        self.assertIn("约 20 分钟 · 里程待核实", rendered)
        self.assertIn("餐饮店铺推荐", rendered)

    def test_build_embeds_local_image_and_rejects_path_escape(self):
        from scripts.trip_tonic import html_text

        guide = sample_guide()
        with tempfile.TemporaryDirectory() as directory:
            image_path = Path(directory) / "photo.png"
            png_header = b"\x89PNG\r\n\x1a\n"
            image_path.write_bytes(png_header)
            guide["images"] = [{"title": "风景", "path": "photo.png", "alt": "山景", "source_ids": ["xhs-1"]}]
            rendered = html_text(guide, validate_guide(guide), media_root=directory)
            expected = base64.b64encode(png_header).decode("ascii")
            self.assertIn("data:image/png;base64," + expected, rendered)
            guide["images"][0]["path"] = "../outside.png"
            escaped = html_text(guide, validate_guide(guide), media_root=directory)
            self.assertIn("图片素材缺失或格式不支持", escaped)

    def test_ics_and_build_outputs(self):
        guide = sample_guide()
        self.assertIn("BEGIN:VCALENDAR", ics_text(guide))
        with tempfile.TemporaryDirectory() as directory:
            result = build(guide, directory)
            self.assertEqual(result["status"], "ok")
            for filename in ("guide.html", "guide.md", "guide.ics", "guide.geojson", "guide.kml", "guide.normalized.json", "validation.json"):
                self.assertTrue((Path(directory) / filename).is_file(), filename)
            normalized = json.loads((Path(directory) / "guide.normalized.json").read_text(encoding="utf-8"))
            self.assertEqual(normalized["meta"]["destination"], "测试地")
            class DocumentParser(HTMLParser):
                def __init__(self):
                    super().__init__()
                    self.errors = []

                def error(self, message):
                    self.errors.append(message)

            parser = DocumentParser()
            parser.feed((Path(directory) / "guide.html").read_text(encoding="utf-8"))
            parser.close()
            self.assertEqual(parser.errors, [])
            self.assertIn("总体路线", (Path(directory) / "guide.html").read_text(encoding="utf-8"))
            self.assertIn('aria-label="总体路线顺序示意，非比例"', (Path(directory) / "guide.html").read_text(encoding="utf-8"))

    def test_html_escapes_untrusted_text(self):
        guide = sample_guide()
        guide["meta"]["title"] = "Trip <script>alert(1)</script>"
        with tempfile.TemporaryDirectory() as directory:
            result = build(guide, directory)
            self.assertEqual(result["status"], "ok")
            rendered = (Path(directory) / "guide.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_build_refuses_material_conflicts(self):
        guide = sample_guide()
        guide["days"][0]["items"][1]["start"] = "09:30"
        with tempfile.TemporaryDirectory() as directory:
            result = build(guide, directory)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["files"], [])

    def test_pace_and_time_window_warnings(self):
        guide = sample_guide()
        guide["preferences"]["pace"] = "relaxed"
        guide["preferences"]["earliest_start"] = "09:00"
        guide["days"][0]["items"][0]["start"] = "08:00"
        guide["days"][0]["items"].append({"name": "晚场活动", "type": "activity", "start": "18:30", "end": "19:30", "route_from_previous": {"mode": "步行", "duration_min": 10}})
        report = validate_guide(guide, today=date(2026, 9, 23))
        codes = {issue["code"] for issue in report["warnings"]}
        self.assertIn("PACE_OVERLOAD", codes)
        self.assertIn("TIME_WINDOW", codes)

    def test_day_start_transfer_and_lodging_continuity(self):
        guide = multi_day_guide()
        report = validate_guide(guide, today=date(2026, 9, 23))
        codes = {issue["code"] for issue in report["warnings"]}
        self.assertIn("DAY_START_TRANSFER_MISSING", codes)
        self.assertIn("LODGING_PLAN_MISSING", codes)
        guide["days"][1]["items"][0]["route_from_previous"] = {"mode": "步行", "duration_min": 10}
        guide["days"][0]["items"].append({"name": "入住酒店", "type": "hotel", "start": "20:00", "end": "21:00"})
        codes = {issue["code"] for issue in validate_guide(guide, today=date(2026, 9, 23))["warnings"]}
        self.assertNotIn("DAY_START_TRANSFER_MISSING", codes)
        self.assertNotIn("LODGING_PLAN_MISSING", codes)

    def test_drive_fatigue_warnings(self):
        guide = sample_guide()
        guide["days"][0]["items"][1]["start"] = "16:00"
        guide["days"][0]["items"][1]["end"] = "17:00"
        guide["days"][0]["items"][1]["route_from_previous"] = {"mode": "自驾", "duration_min": 400, "distance_km": 200}
        guide["route"]["legs"][0]["duration_min"] = 320
        report = validate_guide(guide, today=date(2026, 9, 23))
        fatigue_messages = [issue["message"] for issue in report["warnings"] if issue["code"] == "DRIVE_FATIGUE"]
        # 三条疲劳警告（单段/当日合计/城际段）都必须格式化出具体分钟数，不允许残留 {} 占位符
        self.assertEqual(len(fatigue_messages), 3)
        joined = " ".join(fatigue_messages)
        self.assertNotIn("{}", joined)
        self.assertIn("单段自驾约 400 分钟", joined)
        self.assertIn("当日自驾合计约 400 分钟", joined)
        self.assertIn("城际自驾路段约 320 分钟", joined)

    def test_budget_mismatch_warning(self):
        guide = sample_guide()
        guide["budget"] = {"profiles": {"balanced": {"total": "100 元", "categories": {"住宿": "80 元", "餐饮": "30 元"}}}}
        report = validate_guide(guide, today=date(2026, 9, 23))
        self.assertIn("BUDGET_MISMATCH", {issue["code"] for issue in report["warnings"]})
        guide["budget"]["profiles"]["balanced"]["total"] = "110 元"
        self.assertNotIn("BUDGET_MISMATCH", {issue["code"] for issue in validate_guide(guide, today=date(2026, 9, 23))["warnings"]})

    def test_hotels_and_foods_staleness_warnings(self):
        guide = sample_guide()
        guide["hotels"] = [{"name": "旅店甲", "area": "市区", "checked_at": "2026-08-01", "source_ids": ["xhs-1"]}]
        guide["foods"] = [{"name": "餐馆甲", "shop": "招牌菜", "checked_at": "2026-08-01", "source_ids": ["xhs-1"]}]
        codes = {issue["code"] for issue in validate_guide(guide, today=date(2026, 9, 23))["warnings"]}
        self.assertIn("LODGING_STALE", codes)
        self.assertIn("FOOD_STALE", codes)

    def test_checklist_and_evidence_structure_validation(self):
        guide = sample_guide()
        guide["checklist"] = [{"detail": "缺少标题"}, {"title": "确认预约", "date": "not-a-date"}]
        guide["evidence"] = [{"checked_at": "bad"}]
        report = validate_guide(guide, today=date(2026, 9, 23))
        codes = {issue["code"] for issue in report["errors"]}
        self.assertIn("CHECKLIST_TITLE", codes)
        self.assertIn("CHECKLIST_DATE", codes)
        self.assertIn("EVIDENCE_FIELD", codes)
        self.assertIn("EVIDENCE_DATE", codes)

    def test_backup_checklist_evidence_rendering(self):
        from scripts.trip_tonic import html_text, markdown_text

        guide = sample_guide()
        guide["days"][0]["backup"] = [{"condition": "雨天", "plan": "改为室内活动"}]
        guide["days"][0]["items"][0]["backup"] = [{"condition": "闭馆", "plan": "改去备选展馆"}]
        guide["checklist"] = [{"title": "确认预约", "detail": "出发前一周", "date": "2026-09-20"}]
        guide["evidence"] = [{"claim": "首日应留白适应", "summary": "多位旅行者首日安排休息", "confidence": "medium", "source_ids": ["xhs-1"]}]
        text = markdown_text(guide)
        self.assertIn("- 备选（雨天）：改为室内活动", text)
        self.assertIn("  - 备选（闭馆）：改去备选展馆", text)
        self.assertIn("## 行前清单", text)
        self.assertIn("- [ ] 确认预约（限 2026-09-20）：出发前一周", text)
        self.assertIn("## 证据卡", text)
        self.assertIn("首日应留白适应", text)
        rendered = html_text(guide, validate_guide(guide))
        self.assertIn("备选方案", rendered)
        self.assertIn("改去备选展馆", rendered)
        self.assertIn("改为室内活动", rendered)
        self.assertIn("行前清单", rendered)
        self.assertIn("确认预约", rendered)
        self.assertIn("证据卡", rendered)

    def test_backup_structure_validation(self):
        guide = sample_guide()
        guide["days"][0]["items"][0]["backup"] = ["仅字符串，缺少 plan"]
        guide["days"][0]["backup"] = [{"condition": "雨天"}]
        report = validate_guide(guide, today=date(2026, 9, 23))
        self.assertIn("BACKUP_FIELD", {issue["code"] for issue in report["errors"]})

    def test_ics_dtstamp_alarm_geo_and_checklist_events(self):
        guide = sample_guide()
        guide["days"][0]["items"][1]["type"] = "transport"
        guide["checklist"] = [{"title": "确认预约", "detail": "官方渠道", "date": "2026-09-22"}]
        text = ics_text(guide, now=datetime(2026, 9, 23, 8, 0, 0, tzinfo=timezone.utc))
        self.assertIn("DTSTAMP:20260923T080000Z", text)
        self.assertIn("GEO:29.60000;91.10000", text)
        self.assertIn("LOCATION:地点A", text)
        self.assertIn("BEGIN:VALARM", text)
        self.assertIn("DTSTART;VALUE=DATE:20260922", text)
        self.assertIn("DTEND;VALUE=DATE:20260923", text)
        self.assertIn("SUMMARY:清单：确认预约", text)
        physical_lines = text.split("\r\n")
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in physical_lines))

    def test_geojson_includes_route_stops_line_and_bbox(self):
        guide = sample_guide()
        guide["route"]["stops"] = [{"name": "A", "coords": [100.0, 25.0]}, {"name": "B", "coords": [101.0, 26.0]}]
        data = geojson_data(guide)
        types = [feature["properties"].get("type") for feature in data["features"]]
        self.assertIn("stop", types)
        self.assertIn("route", types)
        line = next(feature for feature in data["features"] if feature["properties"].get("type") == "route")
        self.assertEqual(line["geometry"]["coordinates"], [[100.0, 25.0], [101.0, 26.0]])
        self.assertEqual(data["bbox"], [91.1, 25.0, 101.0, 29.6])

    def test_scaled_route_map_when_all_stops_have_coords(self):
        from scripts.trip_tonic import html_text

        guide = sample_guide()
        guide["route"]["stops"] = [{"name": "A", "coords": [100.0, 25.0]}, {"name": "B", "coords": [101.0, 26.0]}]
        rendered = html_text(guide, validate_guide(guide))
        self.assertIn('aria-label="总体路线位置示意，按坐标比例，非导航"', rendered)
        self.assertIn("<polyline", rendered)
        self.assertNotIn("路线示意 · 非比例 · 非导航", rendered)

    def test_normalized_guide_orders_keys_and_fills_defaults(self):
        guide = sample_guide()
        guide["zzz_custom"] = 1
        guide["meta"].pop("days", None)
        guide["days"][0].pop("day", None)
        result = normalized_guide(guide)
        self.assertEqual(list(result.keys()), ["schema_version", "meta", "preferences", "sources", "route", "days", "businesses", "zzz_custom"])
        self.assertEqual(result["meta"]["days"], 1)
        self.assertEqual(result["days"][0]["day"], 1)
        self.assertNotIn("days", guide["meta"])
        self.assertNotIn("day", guide["days"][0])

    def test_text_artifacts_use_lf_newlines(self):
        guide = sample_guide()
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(build(guide, directory)["status"], "ok")
            for name in ("guide.md", "guide.html", "guide.normalized.json", "guide.geojson", "validation.json"):
                content = (Path(directory) / name).read_bytes()
                self.assertNotIn(b"\r", content, name)

    def test_cli_init_compare_strict_and_migrate(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(main(["init", directory, "--start-date", "2026-10-01", "--days", "3"]), 0)
            scaffold = json.loads((Path(directory) / "guide.json").read_text(encoding="utf-8"))
            self.assertEqual(scaffold["meta"]["days"], 3)
            self.assertEqual(scaffold["days"][2]["date"], "2026-10-03")
            self.assertEqual(main(["init", directory]), 1)
            variant = json.loads(json.dumps(scaffold))
            variant["meta"]["days"] = 2
            variant["days"].append(json.loads(json.dumps(scaffold["days"][0])))
            variant_path = Path(directory) / "variant.json"
            variant_path.write_text(json.dumps(variant, ensure_ascii=False), encoding="utf-8")
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                self.assertEqual(main(["compare", str(Path(directory) / "guide.json"), str(variant_path)]), 0)
            payload = json.loads(buffer.getvalue())
            self.assertIn("days", payload["differences"])
            legacy = json.loads(json.dumps(scaffold))
            legacy.pop("schema_version")
            legacy_path = Path(directory) / "legacy.json"
            legacy_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(main(["migrate", str(legacy_path)]), 0)
            self.assertEqual(json.loads(legacy_path.read_text(encoding="utf-8"))["schema_version"], "1.0")
            self.assertEqual(main(["migrate", str(Path(directory) / "guide.json")]), 0)

    def test_cli_validate_strict_and_today_flags(self):
        template = Path(__file__).resolve().parent.parent / "examples" / "guide-template.json"
        self.assertEqual(main(["validate", str(template)]), 0)
        self.assertEqual(main(["validate", str(template), "--strict"]), 1)
        self.assertEqual(main(["validate", str(template), "--today", "not-a-date"]), 1)

    def test_strict_json_rejects_duplicate_keys(self):
        with self.assertRaises(ValueError):
            load_json_text('{"a": 1, "a": 2}')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "guide.json"
            path.write_text('{"schema_version": "1.0", "schema_version": "1.0"}', encoding="utf-8")
            self.assertEqual(main(["validate", str(path)]), 1)

    def test_corrupt_schema_is_a_hard_error_not_a_silent_fallback(self):
        guide = sample_guide()
        with patch("scripts.trip_tonic.validator.load_guide_schema", side_effect=SchemaCorruptError("schema 坏了")):
            report = validate_guide(guide)
        self.assertIn("SCHEMA_CORRUPT", {issue["code"] for issue in report["errors"]})
        self.assertFalse(report["valid"])

    def test_mode_normalization_and_unknown_mode_warning(self):
        self.assertEqual(normalize_mode("自驾"), "drive")
        self.assertEqual(normalize_mode("Driving"), "drive")
        self.assertEqual(normalize_mode("地铁"), "metro")
        self.assertIsNone(normalize_mode("马背骑行"))
        guide = sample_guide()
        guide["route"]["legs"][0]["mode"] = "马背骑行"
        report = validate_guide(guide)
        self.assertIn("MODE_UNRECOGNIZED", {issue["code"] for issue in report["warnings"]})
        guide["route"]["legs"][0]["mode"] = "火车"
        self.assertNotIn("MODE_UNRECOGNIZED", {issue["code"] for issue in validate_guide(guide)["warnings"]})

    def test_full_body_i18n_for_en_guides(self):
        from scripts.trip_tonic import html_text, markdown_text

        guide = sample_guide()
        guide["meta"]["language"] = "en-US"
        guide["days"][0]["items"][1]["type"] = "transport"
        guide["days"][0]["items"][1]["route_from_previous"]["mode"] = "drive"
        guide["days"][0]["items"][1]["route_from_previous"]["distance_km"] = 12
        guide["checklist"] = [{"title": "Confirm booking", "detail": "official channel", "date": "2026-09-22"}]
        text = markdown_text(guide)
        self.assertIn("## Overall Route", text)
        self.assertIn("## Trip Statistics", text)
        self.assertIn("## Pre-trip Checklist", text)
        self.assertIn("~20 min", text)
        rendered = html_text(guide, validate_guide(guide))
        self.assertIn("Trip Statistics", rendered)
        self.assertIn("Transfer: drive", rendered)
        calendar = ics_text(guide)
        self.assertIn("Checklist: Confirm booking", calendar)
        self.assertIn("Reminder: leave 30 minutes early", calendar)

    def test_guide_stats_totals_and_pace(self):
        guide = multi_day_guide()
        guide["days"][1]["items"][0]["route_from_previous"] = {"mode": "自驾", "duration_min": 90, "distance_km": 60}
        guide["sources"][0]["media"] = [{"type": "image", "url": "https://img.example.com/a.jpg"}, {"type": "video", "url": "https://video.example.com/b.mp4"}]
        stats = guide_stats(guide)
        self.assertEqual(stats["totals"]["days"], 2)
        self.assertEqual(stats["totals"]["items"], 4)
        self.assertEqual(stats["totals"]["drive_minutes"], 130)
        self.assertEqual(stats["totals"]["drive_km"], 60)
        self.assertEqual(stats["totals"]["media"], 2)
        self.assertEqual(stats["longest_leg"]["duration_min"], 30)
        self.assertEqual(stats["pace"], "ok")

    def test_media_links_rendered_in_html_and_markdown(self):
        from scripts.trip_tonic import html_text, markdown_text

        guide = sample_guide()
        guide["sources"][0]["url"] = "https://www.xiaohongshu.com/note/demo"
        guide["sources"][0]["media"] = [
            {"type": "image", "url": "https://sns-img.example.com/park.jpg", "description": "湖边清晨"},
            {"type": "video", "url": "https://sns-video.example.com/arrival.mp4"},
        ]
        rendered = html_text(guide, validate_guide(guide))
        self.assertIn("旅行影像", rendered)
        self.assertIn("sns-img.example.com/park.jpg", rendered)
        self.assertIn("sns-video.example.com/arrival.mp4", rendered)
        self.assertIn("湖边清晨", rendered)
        self.assertIn("media-kind video", rendered)
        self.assertIn("www.xiaohongshu.com/note/demo", rendered)
        self.assertIn("媒体链接", rendered.split("</table>")[0])
        text = markdown_text(guide)
        self.assertIn("## 旅行影像", text)
        self.assertIn("](https://sns-img.example.com/park.jpg)", text)
        self.assertIn("](https://sns-video.example.com/arrival.mp4)", text)
        self.assertIn("- **[图片]** 湖边清晨", text)
        guide["meta"]["language"] = "en-US"
        self.assertIn("Travel Photos &amp; Videos", html_text(guide, validate_guide(guide)))
        self.assertIn("## Travel Photos & Videos", markdown_text(guide))

    def test_album_folding_markup(self):
        """媒体多时相册两级折叠：分区默认显示前 3 组、组内默认显示
        前 4 张，各级带 查看更多/收起 按钮；组网格用 auto-fill，
        单张图片不再被拉伸占满整行。"""
        from scripts.trip_tonic import html_text

        guide = sample_guide()
        resolved = {}
        for i in range(5):
            guide["sources"].append({
                "id": "xhs-%d" % (i + 2), "title": "笔记%d" % (i + 1),
                "url": "https://www.xiaohongshu.com/note/%d" % (i + 1),
                "type": "user", "checked_at": "2026-09-22",
                "media": [{"type": "image", "url": "https://img.example.com/%d-%d.jpg" % (i, j), "description": "图 %d" % j} for j in range(5)],
            })
            for j in range(5):
                resolved["https://img.example.com/%d-%d.jpg" % (i, j)] = {"kind": "image", "src": "data:image/png;base64,AAAA"}
        rendered = html_text(guide, validate_guide(guide), media_resolved=resolved)
        # 概览行（含头部切换按钮）
        self.assertIn('class="media-summary"', rendered)
        self.assertIn("共 5 篇笔记 · 25 项", rendered)
        # 分区级折叠：5 组 > 3，默认收起后 2 组；头部与底部各一个切换按钮
        self.assertIn('class="media-groups media-folded"', rendered)
        self.assertIn("查看更多（还有 2 篇）", rendered)
        self.assertIn('class="media-toggle media-toggle-end"', rendered)
        self.assertIn("收起", rendered)
        # 组内折叠：每组 5 张 > 4，均有展开按钮（文案在 data-more 属性与按钮文本各出现一次）
        self.assertEqual(rendered.count('class="media-more"'), 5)
        self.assertEqual(rendered.count("查看全部 5 项"), 10)
        # 折叠样式与脚本
        self.assertIn(".media-groups.folded .media-group:nth-child(n+4){display:none}", rendered)
        self.assertIn(".media-group.folded .media-thumb:nth-child(n+5){display:none}", rendered)
        self.assertIn(".media-groups.media-folded~.media-toggle-end{display:none}", rendered)
        self.assertIn(".media-group.folded", rendered.split("</style>")[0])
        # 组网格 auto-fill：单图不整行拉伸
        self.assertIn("grid-template-columns:repeat(auto-fill,minmax(200px,1fr))", rendered)
        # 折叠脚本就位（分区级按钮批量绑定）
        self.assertIn('document.querySelectorAll(".media-toggle")', rendered)

    def test_item_source_links_render_as_real_anchors(self):
        from scripts.trip_tonic import html_text

        guide = sample_guide()
        rendered = html_text(guide, validate_guide(guide))
        # 行程项"来源："行必须是真实 <a> 锚点；曾因 _esc 包住 .format 整行被转义成纯文本
        self.assertIn('来源：<a href="https://example.com/note" target="_blank" rel="noopener">真实体验笔记</a>', rendered)
        self.assertNotIn("&lt;a href=", rendered)
        # 统计区上下布局：指标表在上、甘特图通栏在下（不再左右分栏）
        self.assertIn("grid-template-columns:1fr", rendered)
        self.assertNotIn("repeat(auto-fit,minmax(300px,1fr))", rendered)

    def test_validator_flags_invalid_and_stale_media(self):
        today = date(2026, 10, 8)
        guide = sample_guide()
        guide["sources"][0]["media"] = [{"type": "photo", "url": "https://img.example.com/a.jpg"}]
        report = validate_guide(guide, today)
        self.assertIn("MEDIA_TYPE", {issue["code"] for issue in report["errors"]})
        guide["sources"][0]["media"] = [{"type": "image", "url": "ftp://img.example.com/a.jpg"}]
        self.assertIn("MEDIA_URL", {issue["code"] for issue in validate_guide(guide, today)["errors"]})
        guide["sources"][0]["media"] = "not-a-list"
        self.assertIn("MEDIA_INVALID", {issue["code"] for issue in validate_guide(guide, today)["errors"]})
        guide["sources"][0]["media"] = [{"type": "image", "url": "https://img.example.com/a.jpg"}]
        guide["sources"][0]["checked_at"] = "2026-09-01"
        self.assertIn("MEDIA_STALE", {issue["code"] for issue in validate_guide(guide, today)["warnings"]})
        guide["sources"][0]["checked_at"] = "2026-10-01"
        self.assertNotIn("MEDIA_STALE", {issue["code"] for issue in validate_guide(guide, today)["warnings"]})

    def test_media_survives_normalization(self):
        guide = sample_guide()
        guide["sources"][0]["media"] = [{"type": "image", "url": "https://img.example.com/a.jpg", "description": "封面"}]
        normalized = normalized_guide(guide)
        self.assertEqual(normalized["sources"][0]["media"][0]["description"], "封面")
        self.assertEqual(list(normalized["sources"][0]["media"][0].keys()), ["type", "url", "description"])

    def test_fetch_media_cache_and_album_rendering(self):
        """端到端：本地 HTTP 服务器供假 PNG/MP4/坏文件，验证下载缓存、
        幂等重跑、相册灯箱渲染、视频拷贝与失败条目的链接回退。"""
        from scripts.trip_tonic import fetch_media

        png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24  # 魔数即可通过校验
        mp4_bytes = b"\x00\x00\x00\x20ftypisom" + b"\x00" * 24
        files = {"/ok.png": (png_bytes, "image/png"), "/ok.mp4": (mp4_bytes, "video/mp4"), "/bad.html": (b"<html>error</html>", "text/html")}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body, content_type = files.get(self.path, (b"missing", "application/octet-stream"))
                self.send_response(200 if self.path in files else 404)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        guide = sample_guide()
        with tempfile.TemporaryDirectory() as directory:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            base = "http://127.0.0.1:{}".format(server.server_address[1])
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                guide["sources"][0]["media"] = [
                    {"type": "image", "url": base + "/ok.png", "description": "湖景"},
                    {"type": "video", "url": base + "/ok.mp4", "description": "实拍"},
                    {"type": "image", "url": base + "/bad.html", "description": "坏文件"},
                ]
                cache_dir = str(Path(directory) / "media-cache")
                first = fetch_media(guide, cache_dir, timeout=10)
                self.assertEqual(first["status"], "partial")
                self.assertEqual(first["downloaded"], 2)
                self.assertEqual(len(first["failed"]), 1)
                manifest = json.loads((Path(cache_dir) / "media-cache.json").read_text(encoding="utf-8"))
                self.assertEqual(set(manifest["entries"]), {base + "/ok.png", base + "/ok.mp4"})
                # 幂等：清单命中的 URL 跳过、不重复下载
                second = fetch_media(guide, cache_dir, timeout=10)
                self.assertEqual(second["skipped"], 2)
                self.assertEqual(second["downloaded"], 0)
                result = build(guide, directory, media_cache=cache_dir)
                html = (Path(directory) / "guide.html").read_text(encoding="utf-8")
                markdown = (Path(directory) / "guide.md").read_text(encoding="utf-8")
                # 目录仍存活时收集视频拷贝（TemporaryDirectory 退出即删除）
                copied = list((Path(directory) / "media").glob("*.mp4"))
            finally:
                server.shutdown()
                server.server_close()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["media_resolved"], 2)
        # 分组相册缩略图 + 分组灯箱数据脚本 + 样式
        self.assertIn('class="media-thumb"', html)
        self.assertIn('data-group="0" data-index="0"', html)
        self.assertIn("data:image/png;base64,", html)
        self.assertIn("var groups = [", html)
        self.assertIn(".lightbox{", html)
        self.assertIn('class="media-group-head"', html)
        # 坏文件不在缓存清单，有相册时回退为紧凑链接列表
        self.assertIn(base + "/bad.html", html)
        # 视频拷进产物 media/ 目录；HTML/MD 均以相对路径引用
        self.assertEqual(len(copied), 1)
        self.assertIn('<video src="media/' + copied[0].name + '"', html)
        self.assertIn("本地缓存视频](media/" + copied[0].name + ")", markdown)

    def test_html_contains_gantt_chart_and_budget_pie(self):
        from scripts.trip_tonic import html_text

        guide = sample_guide()
        guide["budget"] = {"profiles": {"balanced": {"total": "130 元", "categories": {"住宿": "80 元", "餐饮": "30 元", "交通": "20 元"}}}}
        rendered = html_text(guide, validate_guide(guide))
        self.assertIn('svg class="gantt"', rendered)
        self.assertIn("gantt-bar", rendered)
        self.assertIn("行程统计", rendered)
        self.assertIn("svg class=\"pie\"", rendered)
        self.assertIn("住宿", rendered)

    def test_pie_explicit_size_and_hover_cursors(self):
        """饼图必须有显式宽高（只带 viewBox 会被浏览器拉伸过大）、
        扇区悬停 title 提示，甘特条与饼图扇区悬停显示手型光标。"""
        from scripts.trip_tonic import html_text

        guide = sample_guide()
        guide["budget"] = {"profiles": {"balanced": {"total": "130 元", "categories": {"住宿": "80 元", "餐饮": "30 元", "交通": "20 元"}}}}
        rendered = html_text(guide, validate_guide(guide))
        self.assertIn('viewBox="0 0 180 180" width="180" height="180"', rendered)
        self.assertIn(".pie path,.pie circle{cursor:pointer}", rendered)
        self.assertIn(".gantt-bar{stroke:#fff;stroke-width:1;cursor:pointer}", rendered)
        # 扇区悬停显示分类明细（数值经 stats 解析为数字）
        self.assertIn("<title>住宿 · 80.0 · 62%</title>", rendered)

    def test_avoid_renders_name_reason_style_and_warns_when_empty(self):
        """避坑条目兼容 name/reason 写法（渲染出内容而非只剩链接）；
        两种字段都缺时校验给出 AVOID_STRUCTURE 警告。"""
        from scripts.trip_tonic import html_text, markdown_text

        guide = sample_guide()
        guide["avoid"] = [
            {"name": "小心假停车费", "reason": "只走官方停车场，或路边免费停车带", "source_ids": ["xhs-1"], "checked_at": "2026-09-22"},
            {"wrong": "夜路赶路", "right": "白天抵达，夜间活动就近安排", "source_ids": ["xhs-1"]},
            {"source_ids": ["xhs-1"]},
        ]
        rendered = html_text(guide, validate_guide(guide))
        self.assertIn("小心假停车费", rendered)
        self.assertIn("只走官方停车场，或路边免费停车带", rendered)
        self.assertIn("夜路赶路", rendered)
        markdown = markdown_text(guide, validate_guide(guide))
        self.assertIn("- 避免：小心假停车费；建议：只走官方停车场，或路边免费停车带", markdown)
        self.assertIn("- 避免：夜路赶路；建议：白天抵达，夜间活动就近安排", markdown)
        codes = {issue["code"] for issue in validate_guide(guide)["warnings"]}
        self.assertIn("AVOID_STRUCTURE", codes)
        guide["avoid"] = guide["avoid"][:2]
        self.assertNotIn("AVOID_STRUCTURE", {issue["code"] for issue in validate_guide(guide)["warnings"]})
        # 规范化键序包含兼容字段，diff 稳定
        normalized = normalized_guide(guide)
        self.assertEqual(list(normalized["avoid"][0].keys()), ["name", "reason", "source_ids", "checked_at"])

    def test_kml_export_contains_points_and_route(self):
        guide = sample_guide()
        guide["route"]["stops"] = [{"name": "A", "coords": [100.0, 25.0]}, {"name": "B", "coords": [101.0, 26.0]}]
        text = kml_text(guide)
        self.assertIn("<Document>", text)
        self.assertIn("100.0,25.0,0", text)
        self.assertIn("<LineString>", text)
        guide["days"][0]["items"][0]["name"] = "地点A&B"
        self.assertIn("地点A&amp;B", kml_text(guide))

    def test_compare_reports_semantic_changes_and_tradeoffs(self):
        left = multi_day_guide()
        right = json.loads(json.dumps(left))
        right["days"][1]["items"][1]["start"] = "11:00"
        right["days"][1]["items"].append({"name": "新增活动", "type": "activity", "start": "16:00", "end": "17:00"})
        comparison = compare_guides(left, right)
        day_changes = comparison["semantic"]["days"]
        self.assertEqual(day_changes[0]["day"], 2)
        self.assertEqual(day_changes[0]["added"], ["新增活动"])
        self.assertEqual(day_changes[0]["time_changes"][0]["name"], "地点B")
        self.assertTrue(comparison["tradeoffs"])
        self.assertIn("days", comparison["differences"])

    def test_migrate_supports_explicit_target_and_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as directory:
            legacy = json.loads(json.dumps(sample_guide()))
            legacy.pop("schema_version")
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(main(["migrate", str(path), "--target", "1.0"]), 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], "1.0")
            self.assertEqual(main(["migrate", str(path), "--target", "9.9"]), 1)
            self.assertEqual(main(["migrate", str(path)]), 0)

    def test_lint_research_validates_structure_and_coverage(self):
        example = Path(__file__).resolve().parent.parent / "examples" / "research-record.example.json"
        record = json.loads(example.read_text(encoding="utf-8"))
        result = research_record_issues(record)
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["coverage"]["searches"], 7)
        self.assertEqual(result["coverage"]["notes_inspected"], 9)
        self.assertEqual(result["coverage"]["comment_threads"], 5)
        self.assertEqual(result["coverage"]["trip_days"], 7)
        self.assertEqual(len(result["coverage"]["topics_covered"]), 7)
        self.assertEqual(main(["lint-research", str(example)]), 0)
        self.assertEqual(main(["lint-research", str(example), "--strict"]), 0)
        thin = {"meta": {"destination": "某地", "created_at": "2026-09-20"}, "searches": [], "notes": []}
        result = research_record_issues(thin)
        codes = {issue["code"] for issue in result["warnings"]}
        self.assertIn("RESEARCH_SEARCH_COVERAGE", codes)
        self.assertIn("RESEARCH_NOTE_COVERAGE", codes)
        self.assertIn("RESEARCH_COMMENT_COVERAGE", codes)
        self.assertIn("RESEARCH_GAPS_MISSING", codes)
        broken = json.loads(json.dumps(record))
        broken["notes"][0]["inspection"] = "skimmed_it"
        broken["notes"][1]["source_id"] = broken["notes"][0]["source_id"]
        codes = {issue["code"] for issue in research_record_issues(broken)["errors"]}
        self.assertIn("RESEARCH_INSPECTION", codes)
        self.assertIn("RESEARCH_DUPLICATE_ID", codes)
        broken_media = json.loads(json.dumps(record))
        broken_media["notes"][0]["media"] = [{"type": "photo", "url": "https://img.example.com/a.jpg"}]
        self.assertIn("RESEARCH_MEDIA", {issue["code"] for issue in research_record_issues(broken_media)["errors"]})

    def test_lint_research_topic_axis_and_recency_checks(self):
        example = Path(__file__).resolve().parent.parent / "examples" / "research-record.example.json"
        record = json.loads(example.read_text(encoding="utf-8"))
        no_topic = json.loads(json.dumps(record))
        no_topic["searches"][0].pop("topic")
        no_topic["searches"][1]["topic"] = "weather"
        codes = {issue["code"] for issue in research_record_issues(no_topic)["errors"]}
        self.assertIn("RESEARCH_TOPIC", codes)
        no_filters = json.loads(json.dumps(record))
        for search in no_filters["searches"]:
            search.pop("filters", None)
        codes = {issue["code"] for issue in research_record_issues(no_filters)["warnings"]}
        self.assertIn("RESEARCH_RECENCY", codes)
        narrow = json.loads(json.dumps(record))
        for search in narrow["searches"]:
            search["topic"] = "food"
        codes = {issue["code"] for issue in research_record_issues(narrow)["warnings"]}
        self.assertIn("RESEARCH_TOPIC_COVERAGE", codes)

    def test_lint_research_coverage_tiers_scale_with_trip_days(self):
        example = Path(__file__).resolve().parent.parent / "examples" / "research-record.example.json"
        record = json.loads(example.read_text(encoding="utf-8"))
        long_trip = json.loads(json.dumps(record))
        long_trip["meta"]["trip_days"] = 10
        codes = {issue["code"] for issue in research_record_issues(long_trip)["warnings"]}
        self.assertIn("RESEARCH_SEARCH_COVERAGE", codes)
        self.assertIn("RESEARCH_NOTE_COVERAGE", codes)
        short_trip = json.loads(json.dumps(record))
        short_trip["meta"]["trip_days"] = 1
        result = research_record_issues(short_trip)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["coverage"]["trip_days"], 1)
        no_days = json.loads(json.dumps(record))
        no_days["meta"].pop("trip_days")
        result = research_record_issues(no_days)
        self.assertEqual(result["warnings"], [])
        self.assertIsNone(result["coverage"]["trip_days"])

    def test_init_flags_fill_profile_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            arguments = ["init", directory, "--days", "2", "--title", "测试行程", "--destination", "测试地", "--origin", "出发地", "--travelers", "3", "--pace", "relaxed", "--start-date", "2026-10-01"]
            self.assertEqual(main(arguments), 0)
            scaffold = json.loads((Path(directory) / "guide.json").read_text(encoding="utf-8"))
            self.assertEqual(scaffold["meta"]["title"], "测试行程")
            self.assertEqual(scaffold["meta"]["destination"], "测试地")
            self.assertEqual(scaffold["meta"]["origin"], "出发地")
            self.assertEqual(scaffold["meta"]["travelers"], 3)
            self.assertEqual(scaffold["preferences"]["pace"], "relaxed")
            self.assertEqual(main(["init", str(Path(directory) / "sub"), "--travelers", "0"]), 1)

    def test_build_online_map_flag_adds_leaflet_only_when_requested(self):
        guide = sample_guide()
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(build(guide, directory, online_map=True)["status"], "ok")
            with_map = (Path(directory) / "guide.html").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(build(guide, directory)["status"], "ok")
            without_map = (Path(directory) / "guide.html").read_text(encoding="utf-8")
        self.assertIn("L.map", with_map)
        self.assertIn("unpkg.com/leaflet", with_map)
        self.assertNotIn("leaflet", without_map)

    def test_serve_rebuild_and_http_delivery(self):
        guide = sample_guide()
        with tempfile.TemporaryDirectory() as directory:
            guide_path = Path(directory) / "guide.json"
            guide_path.write_text(json.dumps(guide, ensure_ascii=False), encoding="utf-8")
            output = Path(directory) / "out"
            self.assertEqual(serve_rebuild(guide_path, output)["status"], "ok")
            handler = functools.partial(serve_module._QuietHandler, directory=str(output))
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen("http://127.0.0.1:{}/guide.html".format(server.server_address[1]), timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("测试旅行", response.read().decode("utf-8"))
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
