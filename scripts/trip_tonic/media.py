"""媒体抓取与本地缓存：把 sources[].media 的远端链接下载为本地文件。

设计要点：
- guide.json 保持"研究数据"纯度：只存原始 URL，不回写本地路径；
  本地缓存状态记录在缓存目录的 media-cache.json 清单里，
  build 时按 URL 反查清单解析本地文件
- 文件名 = URL 的 sha256 前 16 位 + 按魔数判定的扩展名，
  完全由程序生成，杜绝路径注入
- 下载后同时校验声明类型与文件魔数（图片 PNG/JPEG/GIF/WebP，
  视频 MP4/WebM），大小超限直接拒绝，防止把 HTML 错误页当图片嵌入
- 小红书签名链接通常需要登录态，本工具不携带 Cookie；
  下载失败（如 403）属预期情况：保留链接卡片回退，不视为整体失败
"""

import base64
import hashlib
import json
import shutil
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from .common import _atomic_write_many, load_json_text

# 缓存清单文件名（位于缓存目录内）
CACHE_MANIFEST = "media-cache.json"

# 图片魔数签名（与 render_html 的本地图片白名单一致）
_IMAGE_SIGNATURES = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}
# 视频魔数签名：MP4 的 ftyp 盒在偏移 4，WebM 以 EBML 头开始
_VIDEO_SIGNATURES = {
    "video/mp4": lambda data: len(data) >= 8 and data[4:8] == b"ftyp",
    "video/webm": lambda data: data[:4] == b"\x1a\x45\xdf\xa3",
}
_IMAGE_EXTENSION = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
_VIDEO_EXTENSION = {"video/mp4": "mp4", "video/webm": "webm"}

# 大小上限：图片 10MB（内嵌 data URI 后约 13MB），视频 200MB（拷贝不内嵌）
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 200 * 1024 * 1024

# 请求头：带常规 UA，降低被 CDN 直接拒绝的概率
_USER_AGENT = "Mozilla/5.0 (compatible; TripTonic/1.0; media-fetch)"


def sniff_media(data):
    """按文件头判断 (类型, MIME)；无法识别返回 None。

    data 只需文件前若干字节（图片魔数在前 12 字节内，
    MP4 的 ftyp 在偏移 4，WebM 魔数在前 4 字节）。
    """
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp"
    for mime, signatures in _IMAGE_SIGNATURES.items():
        if any(data.startswith(signature) for signature in signatures):
            if mime == "image/webp":
                # RIFF 容器还可能是 WAV 等；必须看到 WEBP 标记（上面已排除）
                continue
            return "image", mime
    for mime, check in _VIDEO_SIGNATURES.items():
        if check(data):
            return "video", mime
    return None


def _iter_media_entries(guide):
    """遍历 guide 里全部合法媒体条目，产出 (来源, 条目, url, 声明类型)。"""
    for source in guide.get("sources", []) if isinstance(guide.get("sources"), list) else []:
        if not isinstance(source, dict) or not isinstance(source.get("media"), list):
            continue
        for entry in source["media"]:
            if not isinstance(entry, dict) or not entry.get("url"):
                continue
            declared = entry.get("type")
            if declared not in ("image", "video"):
                continue
            url = str(entry["url"])
            if not url.startswith(("https://", "http://")):
                continue
            yield source, entry, url, declared


def _cache_manifest_path(cache_dir):
    return Path(cache_dir) / CACHE_MANIFEST


def load_media_cache(cache_dir):
    """读取缓存清单 {url: {file, type, mime, bytes, fetched_at}}；缺失/损坏返回空表。

    清单损坏时按"无缓存"处理（渲染回退为链接卡片），不中断构建。
    """
    path = _cache_manifest_path(cache_dir)
    if not path.is_file():
        return {}
    try:
        manifest = load_json_text(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    entries = manifest.get("entries") if isinstance(manifest, dict) else None
    return entries if isinstance(entries, dict) else {}


def _write_manifest(cache_dir, entries):
    payload = {
        "version": 1,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "entries": entries,
    }
    _atomic_write_many([(_cache_manifest_path(cache_dir), json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "\n")])


def _download(url, kind, timeout):
    """下载单个文件；返回 (bytes, mime) 或抛带原因的 ValueError。"""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        limit = MAX_IMAGE_BYTES if kind == "image" else MAX_VIDEO_BYTES
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("文件超过大小上限（{} 字节）".format(limit))
    sniffed = sniff_media(data)
    if sniffed is None:
        raise ValueError("文件内容不是可识别的图片/视频（Content-Type: {}，疑似 HTML 错误页或空文件）".format(content_type or "未知"))
    sniffed_kind, sniffed_mime = sniffed
    # 声明类型与实际内容必须一致；声明 image 实为 video（或相反）一律拒绝
    if sniffed_kind != kind:
        raise ValueError("声明为 {}，实际内容为 {}（{}）".format(kind, sniffed_kind, sniffed_mime))
    return data, sniffed_mime


def fetch_media(guide, cache_dir, timeout=30):
    """把 guide 中全部媒体链接下载到 cache_dir，返回结果字典。

    幂等：URL 已在清单且文件存在时跳过。失败逐条记录原因
    （网络错误/类型不符/超限），不影响其余下载；整体状态：
    ok（无失败）/ partial（部分失败）/ ok（无可下载条目）。
    """
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)
    entries = load_media_cache(cache)
    downloaded, skipped, failed = 0, 0, []
    for _, _, url, declared in _iter_media_entries(guide):
        cached = entries.get(url)
        if isinstance(cached, dict) and cached.get("file") and (cache / cached["file"]).is_file():
            skipped += 1
            continue
        try:
            data, mime = _download(url, declared, timeout)
        except urllib.error.HTTPError as error:
            failed.append({"url": url, "reason": "HTTP {}（小红书签名链接可能需要登录态，或已过期）".format(error.code)})
            continue
        except (urllib.error.URLError, OSError, ValueError) as error:
            failed.append({"url": url, "reason": str(error)})
            continue
        extension = (_IMAGE_EXTENSION if declared == "image" else _VIDEO_EXTENSION).get(mime, "bin")
        filename = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + "." + extension
        (cache / filename).write_bytes(data)
        entries[url] = {
            "file": filename,
            "type": declared,
            "mime": mime,
            "bytes": len(data),
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        downloaded += 1
    _write_manifest(cache, entries)
    total = downloaded + skipped + len(failed)
    status = "ok"
    if failed:
        status = "partial" if (downloaded or skipped) else "error"
    return {
        "status": status,
        "cache_dir": str(cache),
        "total": total,
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
        "note": "媒体版权归原作者，缓存仅供个人离线参考；签名链接下载失败时攻略回退为链接卡片",
    }


def resolve_media(guide, cache_dir, output_dir):
    """把缓存清单解析为渲染可用的本地媒体映射。

    返回 {url: {kind, src, file}}：
    - 图片：src 为 data URI（内嵌单文件 HTML，永久离线可用）
    - 视频：src 为产物目录下的相对路径 media/<file>（文件已拷贝，
      需连同 guide.html 所在目录一起保存）
    缓存缺失/文件损坏/魔数不符的条目不进映射，渲染回退链接卡片。
    """
    if not cache_dir:
        return {}
    cache = load_media_cache(cache_dir)
    if not cache:
        return {}
    resolved = {}
    media_out = Path(output_dir) / "media"
    for _, _, url, _ in _iter_media_entries(guide):
        cached = cache.get(url)
        if not isinstance(cached, dict) or not cached.get("file"):
            continue
        path = Path(cache_dir) / cached["file"]
        if not path.is_file():
            continue
        with open(path, "rb") as stream:
            head = stream.read(32)
        sniffed = sniff_media(head)
        if sniffed is None:
            continue
        kind, mime = sniffed
        if kind == "image":
            with open(path, "rb") as stream:
                data = stream.read(MAX_IMAGE_BYTES + 1)
            if len(data) > MAX_IMAGE_BYTES:
                continue
            encoded = base64.b64encode(data).decode("ascii")
            resolved[url] = {"kind": "image", "src": "data:{};base64,{}".format(mime, encoded), "file": cached["file"]}
        else:
            # 视频：拷贝进产物目录，HTML 以相对路径引用
            media_out.mkdir(parents=True, exist_ok=True)
            destination = media_out / cached["file"]
            shutil.copyfile(path, destination)
            resolved[url] = {"kind": "video", "src": "media/" + cached["file"], "file": cached["file"]}
    return resolved
