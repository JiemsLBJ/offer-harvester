"""本机求职进度控制台：SQLite API + Sites 前端一键启动。

用法：
  cd automation
  python -m apply_bot.dashboard
  python -m apply_bot.dashboard --api-only

服务只绑定 127.0.0.1，不向局域网或公网暴露个人求职数据。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from . import application_store, config, form_learning, source_monitor, tracker


TRACKER_STATUSES = {
    "drafted", "applied", "interview", "offer", "hired", "rejected",
    "no_response", "offer_declined", "withdrawn",
}


def _sync_tracker(app: dict[str, Any]) -> None:
    status = app["status"] if app["status"] in TRACKER_STATUSES else "drafted"
    tracker.upsert(
        app["company"], app["title"], portal=app["portal"], url=app["url"],
        cv_file=app.get("resume", ""), fit_rating=app.get("fit_rating", ""),
        status=status, deadline=app.get("deadline", ""), sector=app.get("sector", ""),
        role_type=app.get("role_type", ""),
    )


def _dashboard_payload() -> dict[str, Any]:
    payload = application_store.dashboard_payload()
    payload.update(source_monitor.source_payload())
    return payload


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "JobDashboard/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} {fmt % args}")

    def _origin(self) -> str | None:
        origin = self.headers.get("Origin", "")
        if origin.startswith("http://127.0.0.1:") or origin.startswith("http://localhost:"):
            return origin
        return None

    def _send(self, status: int, payload: Any) -> None:
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        origin = self._origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(raw)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("请求体过大")
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        origin = self._origin()
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Vary", "Origin")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            self._send(200, {"ok": True, "local_only": True})
            return
        if path == "/api/dashboard":
            self._send(200, _dashboard_payload())
            return
        if path.startswith("/api/applications/"):
            app = application_store.get_application(path.rsplit("/", 1)[-1])
            self._send(200, app) if app else self._send(404, {"error": "岗位不存在"})
            return
        self._send(404, {"error": "接口不存在"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/sync":
            imported = application_store.import_existing_sources()
            learned = form_learning.import_historical_snapshots()
            self._send(200, {"ok": True, "imported": imported, "learned": learned, "data": _dashboard_payload()})
            return
        self._send(404, {"error": "接口不存在"})

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            payload = self._read_json()
            if path.startswith("/api/applications/"):
                app_id = path.rsplit("/", 1)[-1]
                app = application_store.update_application(app_id, payload)
                if app is None:
                    self._send(404, {"error": "岗位不存在"})
                    return
                _sync_tracker(app)
                self._send(200, {"ok": True, "application": app})
                return
            if path.startswith("/api/requirements/"):
                requirement_id = path.rsplit("/", 1)[-1]
                item = form_learning.resolve_requirement(
                    requirement_id, str(payload.get("action") or ""),
                    profile_path=str(payload.get("profile_path") or ""), value=payload.get("value"),
                )
                self._send(200, {"ok": True, "requirement": item})
                return
            self._send(404, {"error": "接口不存在"})
        except (ValueError, json.JSONDecodeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"本机数据操作失败: {e}"})


def _wait_for_frontend(url: str, timeout_s: int = 60) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                return response.status == 200
        except Exception:
            time.sleep(1)
    return False


def run(api_port: int = 8765, frontend_port: int = 4173, *, api_only: bool = False,
        open_browser: bool = True) -> int:
    config.ensure_dirs()
    imported = application_store.import_existing_sources()
    learned = form_learning.import_historical_snapshots()
    server = ThreadingHTTPServer(("127.0.0.1", api_port), DashboardHandler)
    print(
        f"数据已同步：seen_jobs {imported['seen_jobs']} 条，"
        f"apply_log {imported['apply_log']} 条，tracker {imported['tracker']} 条"
    )
    print(f"表单学习：历史运行 {learned['runs']} 次，字段 {learned['fields']} 项")
    print(f"本机 API: http://127.0.0.1:{api_port}/api/dashboard")
    if api_only:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return 0

    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        print("未找到 npm，无法启动网页；可先用 --api-only 检查数据层")
        return 2
    dashboard_dir = config.AUTOMATION_DIR / "dashboard"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    frontend_url = f"http://127.0.0.1:{frontend_port}/"
    process = subprocess.Popen(
        [npm, "run", "dev", "--", "--host", "127.0.0.1", "--port", str(frontend_port)],
        cwd=dashboard_dir,
    )
    try:
        if _wait_for_frontend(frontend_url):
            print(f"求职进度中心: {frontend_url}")
            if open_browser:
                webbrowser.open(frontend_url)
        else:
            print("网页启动超时，请查看上方前端输出")
            return 3
        return process.wait()
    except KeyboardInterrupt:
        return 0
    finally:
        process.terminate()
        server.shutdown()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="启动本机求职进度与表单学习控制台")
    parser.add_argument("--api-port", type=int, default=8765)
    parser.add_argument("--frontend-port", type=int, default=4173)
    parser.add_argument("--api-only", action="store_true")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args(argv)
    return run(args.api_port, args.frontend_port, api_only=args.api_only, open_browser=not args.no_open)


if __name__ == "__main__":
    sys.exit(main())
