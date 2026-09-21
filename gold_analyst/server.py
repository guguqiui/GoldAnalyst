"""仅监听本机的小型网页服务。后台运行调查，页面轮询获取进度。"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
import time
from urllib.parse import urlparse

from .agent import investigate, safe_error
from .config import ROOT, public_settings
from .demo import demonstrate
from .models import RunState
from .multi_agent import investigate_multi
from .prompts import STRATEGIES
from .storage import now, save_run, markdown
from .server_state import blank_run

RUNS = {}
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1)


def new_run(mode: str, task: str, strategy: str) -> RunState:
    return blank_run(mode, task, strategy)


def execute(run):
    started = time.monotonic()

    def emit(stage, message, details=None):
        with LOCK:
            run["events"].append({"time": now(), "stage": stage, "message": message, "details": details})
    try:
        worker = demonstrate if run["mode"] == "demo" else investigate_multi if run["mode"] == "multi" else investigate
        worker(run, emit)
        run["status"] = "completed"
        emit("完成", "核验报告与证据已整理")
    except Exception as exc:
        run["status"] = "failed"
        run["error"] = safe_error(exc)
        emit("未完成", run["error"])
    finally:
        run["duration_seconds"] = round(time.monotonic() - started, 1)
        try:
            save_run(run)
        except OSError:
            run["save_error"] = "无法写入 reports 文件夹，请检查磁盘权限。页面仍保留本次结果。"
    return run


def load_run(run_id):
    if not re.fullmatch(r"[0-9a-f]{16}", run_id):
        return None
    if run_id in RUNS:
        return RUNS[run_id]
    path = ROOT / "reports" / f"{run_id}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, data, content_type="application/json; charset=utf-8"):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        elif isinstance(data, str):
            data = data.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def local_request(self):
        allowed = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in allowed or (origin and origin not in {"http://" + h for h in allowed}):
            self.send(403, {"error": "仅支持本机页面访问"})
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        path = urlparse(self.path).path
        if path in {"/", "/app.js", "/style.css"}:
            name = "index.html" if path == "/" else path[1:]
            mime = {"index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css"}[name]
            return self.send(200, (ROOT / "web" / name).read_bytes(), mime + "; charset=utf-8")
        if path == "/api/config":
            return self.send(200, {**public_settings(), "strategies": STRATEGIES})
        if path == "/api/runs":
            summaries = []
            for file in sorted((ROOT / "reports").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:12]:
                try:
                    run = json.loads(file.read_text(encoding="utf-8"))
                    summaries.append({k: run.get(k) for k in ("id", "mode", "created_at", "status", "input")})
                except (OSError, ValueError):
                    continue
            return self.send(200, summaries)
        match = re.fullmatch(r"/api/runs/([0-9a-f]{16})(/markdown)?", path)
        if match:
            run = load_run(match[1])
            if run:
                if match[2]:
                    return self.send(200, markdown(run), "text/markdown; charset=utf-8")
                with LOCK:
                    return self.send(200, run)
        self.send(404, {"error": "内容不存在"})

    def do_POST(self):
        if not self.local_request():
            return
        if self.path != "/api/runs":
            return self.send(404, {"error": "接口不存在"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            if not 0 < length <= 16000:
                raise ValueError("输入过长或为空")
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                raise ValueError("需要 JSON 请求")
            data = json.loads(self.rfile.read(length))
            mode, task, strategy = data.get("mode"), data.get("input", ""), data.get("strategy", "source_first")
            if mode not in {"demo", "live", "multi"} or strategy not in STRATEGIES:
                raise ValueError("请选择有效模式与策略")
            if not isinstance(task, str) or len(task) > 4000 or (mode in {"live", "multi"} and not task.strip()):
                raise ValueError("请输入新闻链接或不超过 4000 字的待核验说法")
            if mode in {"live", "multi"} and not public_settings()["model_ready"]:
                raise ValueError("请在本地 .env 配置 OpenAI Key 后重启服务，或先体验教学演示。")
            with LOCK:
                if any(r["status"] == "running" for r in RUNS.values()):
                    return self.send(409, {"error": "已有调查进行中，请等待完成。"})
                run = new_run(mode, task.strip(), strategy)
                RUNS[run["id"]] = run
            POOL.submit(execute, run)
            self.send(202, {"id": run["id"]})
        except (ValueError, TypeError, AttributeError) as exc:
            self.send(400, {"error": str(exc)})


def serve(port=8765):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"\nGold Analyst 已启动 → http://127.0.0.1:{port}\n按 Ctrl+C 停止。\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务。")
    finally:
        server.server_close()
