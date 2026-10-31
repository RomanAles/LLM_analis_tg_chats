import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from tg_chat_analyzer.server import create_server


class ServerTests(unittest.TestCase):
    def setUp(self):
        temp_root = Path(__file__).resolve().parents[1] / ".tmp"
        temp_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=temp_root)
        self.server = create_server(Path(self.temp.name) / "test.sqlite", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.client = build_opener(ProxyHandler({}))

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temp.cleanup()

    def request(self, path, data=None, headers=None):
        payload = json.dumps(data).encode("utf-8") if data is not None else None
        request = Request(self.url + path, data=payload,
                          headers={"Content-Type": "application/json", **(headers or {})})
        with self.client.open(request, timeout=10) as response:
            return response.status, response.read(), response.headers

    def test_demo_analysis_download_feedback(self):
        status, content, _ = self.request("/api/demo", {})
        self.assertEqual(status, 200)
        topic = json.loads(content)["topic"]
        self.request("/api/analyze", {"topic": topic, "config": {}, "chats": ["-990001"]})
        for _ in range(100):
            state = json.loads(self.request("/api/status")[1])
            if state["status"] != "running":
                break
            time.sleep(.02)
        self.assertEqual(state["status"], "complete")
        report = json.loads(self.request("/api/report?run=" + state["run_id"])[1])
        self.assertEqual(report["statistics"]["coverage_percent"], 100)
        for format in ("html", "md", "csv"):
            status, body, headers = self.request(f"/api/report?run={state['run_id']}&format={format}")
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertIn("attachment", headers["Content-Disposition"])
        self.assertEqual(self.request("/api/feedback", {"run_id": state["run_id"],
            "finding_id": report["findings"][0]["id"], "verdict": "correct"})[0], 200)

    def test_cross_origin_and_bad_import_rejected(self):
        with self.assertRaises(HTTPError) as error:
            self.request("/api/demo", {}, {"Origin": "https://example.com"})
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            self.request("/api/import", {"exports": []})
        self.assertEqual(error.exception.code, 400)

    def test_static_page(self):
        status, content, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("Тема".encode("utf-8"), content)
        self.assertIn("script-src 'self'", headers["Content-Security-Policy"])


if __name__ == "__main__":
    unittest.main()
