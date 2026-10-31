from __future__ import annotations

import csv
import io
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from urllib.parse import parse_qs, urlsplit

from .cli import config_from_dict, date_bound, demo_topic, load_demo
from .config import Topic
from .importer import import_export
from .local_api import LocalAPI
from .pipeline import analyze, ensure_job_tables, get_report, save_feedback
from .report import csv_safe, markdown, render_html
from .storage import Store

MAX_BODY = 32 * 1024 * 1024


class Application:
    def __init__(self, db):
        self.db = str(db)
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.state = {"status": "idle", "current": 0, "total": 0, "errors": 0}
        self.worker = None
        with Store(self.db) as store:
            ensure_job_tables(store)

    def status(self):
        with self.lock:
            return dict(self.state)

    def progress(self, state):
        with self.lock:
            self.state.update(state)

    def start(self, payload):
        topic = Topic.from_dict(payload.get("topic"))
        config = config_from_dict(payload.get("config", {}))
        chats = payload.get("chats") or None
        if chats is not None and (not isinstance(chats, list) or any(not isinstance(x, str) for x in chats)):
            raise ValueError("Некорректный список чатов")
        since, until = date_bound(payload.get("since")), date_bound(payload.get("until"), True)
        if since and until and since > until:
            raise ValueError("Начало периода позже окончания")
        with self.lock:
            if self.worker and self.worker.is_alive():
                raise ValueError("Анализ уже выполняется")
            self.cancel.clear()
            self.state = {"status": "running", "current": 0, "total": 0, "errors": 0}

            def work():
                try:
                    with Store(self.db) as store:
                        report = analyze(store, topic, config, chat_ids=chats, since=since, until=until,
                                         cancel=self.cancel, progress=self.progress)
                    self.progress({"status": report["statistics"]["state"], "run_id": report["run_id"],
                                   "statistics": report["statistics"]})
                except Exception as exc:
                    self.progress({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
            self.worker = threading.Thread(target=work, daemon=True, name="topic-analysis")
            self.worker.start()
        return {"status": "running"}


def make_handler(application):
    class Handler(BaseHTTPRequestHandler):
        def allowed(self):
            port = self.server.server_address[1]
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            origin = self.headers.get("Origin")
            return self.headers.get("Host") in hosts and (origin is None or origin in {"http://" + h for h in hosts})

        def reply(self, body, content_type="application/json; charset=utf-8", status=200, filename=None):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            elif isinstance(body, str):
                body = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                             "connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.allowed():
                return self.reply({"error": "Недопустимый источник запроса"}, status=403)
            parsed = urlsplit(self.path)
            params = parse_qs(parsed.query)
            try:
                if parsed.path in {"/", "/app.js", "/app.css"}:
                    name = "index.html" if parsed.path == "/" else parsed.path[1:]
                    mime = {"index.html": "text/html", "app.js": "text/javascript", "app.css": "text/css"}[name]
                    return self.reply(files("tg_chat_analyzer").joinpath("static", name).read_bytes(), mime + "; charset=utf-8")
                if parsed.path == "/api/status":
                    return self.reply(application.status())
                if parsed.path == "/api/models":
                    api = LocalAPI(params.get("base_url", ["http://127.0.0.1:11434"])[0], timeout=5)
                    return self.reply(api.request("/api/tags"))
                with Store(application.db) as store:
                    if parsed.path == "/api/chats":
                        return self.reply(store.list_chats())
                    if parsed.path == "/api/runs":
                        ensure_job_tables(store)
                        rows = store.connection.execute(
                            "SELECT id,status,request,updated_at FROM runs ORDER BY updated_at DESC LIMIT 20")
                        return self.reply([{**dict(row), "request": json.loads(row["request"])} for row in rows])
                    if parsed.path == "/api/report":
                        report = get_report(store, params.get("run", [""])[0])
                        kind = params.get("format", ["json"])[0]
                        if kind == "json":
                            return self.reply(report)
                        if kind == "html":
                            return self.reply(render_html(report), "text/html; charset=utf-8", filename="report.html")
                        if kind == "md":
                            return self.reply(markdown(report), "text/markdown; charset=utf-8", filename="report.md")
                        if kind == "csv":
                            stream = io.StringIO(newline="")
                            writer = csv.writer(stream)
                            writer.writerow(["finding_id", "type", "subtopic", "claim", "chat_id", "message_id", "quote"])
                            for finding in report["findings"]:
                                for source in finding["evidence"]:
                                    writer.writerow([csv_safe(x) for x in [finding["id"], finding["type"], finding["subtopic"],
                                        finding["claim"], source["chat_id"], source["message_id"], source["quote"]]])
                            return self.reply("\ufeff" + stream.getvalue(), "text/csv; charset=utf-8", filename="findings.csv")
                        raise ValueError("Неизвестный формат")
                self.reply({"error": "Не найдено"}, status=404)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                self.reply({"error": str(exc)}, status=400)

        def do_POST(self):
            if not self.allowed():
                return self.reply({"error": "Недопустимый источник запроса"}, status=403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self.reply({"error": "JSON-запрос должен быть не больше 32 MB"}, status=413)
                if self.headers.get_content_type() != "application/json":
                    raise ValueError("Нужен Content-Type application/json")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("Нужен JSON-объект")
                if self.path == "/api/analyze":
                    return self.reply(application.start(payload), status=202)
                if self.path == "/api/cancel":
                    application.cancel.set()
                    return self.reply({"status": "cancel_requested"})
                with Store(application.db) as store:
                    if self.path == "/api/demo":
                        report = load_demo(store)
                        return self.reply({"imports": [report], "topic": demo_topic().to_dict()})
                    if self.path == "/api/import":
                        exports = payload.get("exports")
                        if not isinstance(exports, list) or not 1 <= len(exports) <= 20:
                            raise ValueError("Выберите от 1 до 20 экспортов")
                        reports = [import_export(store, item["data"], source_name=str(item.get("name", "uploaded.json")))
                                   for item in exports]
                        return self.reply({"imports": reports})
                    if self.path == "/api/feedback":
                        save_feedback(store, payload.get("run_id"), payload.get("finding_id", ""),
                                      payload.get("verdict"), payload.get("comment", ""))
                        return self.reply({"status": "saved"})
                self.reply({"error": "Не найдено"}, status=404)
            except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
                self.reply({"error": str(exc)}, status=400)

        def log_message(self, *_args):
            pass
    return Handler


def create_server(db, port=8765):
    if type(port) is not int or not 0 <= port <= 65535:
        raise ValueError("Некорректный порт")
    application = Application(db)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(application))
    server.daemon_threads = True
    server.application = application
    return server


def serve(db, port=8765, open_browser=False):
    server = create_server(db, port)
    url = f"http://127.0.0.1:{server.server_address[1]}"
    print(f"Откройте {url} · Ctrl+C для остановки", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.application.cancel.set()
        server.server_close()
