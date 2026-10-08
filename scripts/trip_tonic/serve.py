"""本地预览服务：HTTP 提供构建产物，guide.json 变化时自动重建。

- 产物写盘走 build 的原子替换，服务期间文件始终一致
- 监视线程每秒比对 mtime+size，变化即重建（JSON 事件输出）
- Ctrl+C 优雅退出（设置停止事件、关服、收尾监视线程）
"""

import functools
import http.server
import threading
import time

from .common import _print_json, load_json_file
from .builder import build


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """静音版静态文件处理器：不打印每条访问日志。"""

    def log_message(self, format, *args):
        pass


def rebuild(guide_path, output_dir, media_root=None, strict=False, media_cache=None):
    """加载 guide.json 并构建一次；返回构建结果字典。"""
    guide = load_json_file(guide_path)
    return build(guide, output_dir, media_root=media_root, strict=strict, media_cache=media_cache)


def _watch_and_rebuild(guide_path, output_dir, media_root, strict, stop_event, media_cache=None):
    """监视线程：每秒检查 guide.json 的 (mtime, size) 签名，变化即重建。

    首次采样只记录签名不触发构建（初始构建由主线程完成）；
    文件暂时不可读（编辑器原子替换间隙）时跳过本轮。
    """
    last_signature = None
    while not stop_event.wait(1.0):
        try:
            stat = guide_path.stat()
        except OSError:
            continue
        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == last_signature:
            continue
        if last_signature is not None:
            result = rebuild(guide_path, output_dir, media_root=media_root, strict=strict, media_cache=media_cache)
            _print_json({"event": "rebuild", "status": result.get("status"), "files": result.get("files", [])})
        last_signature = signature


def serve_command(guide_path, output_dir, port=8000, media_root=None, strict=False, watch=True, media_cache=None):
    """启动预览服务；返回进程退出码（0 正常，1 初始构建失败）。"""
    # 先做一次初始构建：失败就不起服务，避免提供陈旧产物
    result = rebuild(guide_path, output_dir, media_root=media_root, strict=strict, media_cache=media_cache)
    if result.get("status") != "ok":
        _print_json({"status": "error", "message": "初始构建失败，未启动预览服务", "report": result.get("report")})
        return 1
    # ThreadingHTTPServer：并发请求不互相阻塞（浏览器多标签页场景）
    handler = functools.partial(_QuietHandler, directory=str(output_dir))
    server = http.server.ThreadingHTTPServer(("", port), handler)
    actual_port = server.server_address[1]
    stop_event = threading.Event()
    watcher = None
    if watch:
        watcher = threading.Thread(target=_watch_and_rebuild, args=(guide_path, output_dir, media_root, strict, stop_event, media_cache), daemon=True)
        watcher.start()
    url = "http://127.0.0.1:{}/guide.html".format(actual_port)
    _print_json({"status": "ok", "url": url, "port": actual_port, "watch": watch, "note": "Ctrl+C 停止预览；修改 guide.json 会自动重建"})
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # 收尾顺序：停监视线程 -> 关服务器 -> 等待监视线程退出
        stop_event.set()
        server.server_close()
        if watcher is not None:
            watcher.join(timeout=2.0)
    return 0
