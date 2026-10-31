import json
import unittest
from pathlib import Path

from tg_chat_analyzer.analysis import ExtractiveAnalyzer
from tg_chat_analyzer.config import AnalysisConfig, Topic
from tg_chat_analyzer.importer import import_export
from tg_chat_analyzer.pipeline import analyze, get_report, save_feedback
from tg_chat_analyzer.report import render_html
from tg_chat_analyzer.storage import Store

ROOT = Path(__file__).resolve().parents[1]


class CountingAnalyzer(ExtractiveAnalyzer):
    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def analyze(self, fragment, topic):
        self.calls += 1
        if self.fail:
            raise ValueError("synthetic failure")
        return super().analyze(fragment, topic)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        import_export(self.store, ROOT / "examples/synthetic/dev.json")
        self.topic = Topic.load(ROOT / "examples/synthetic/topic_dev.json")
        self.config = AnalysisConfig()

    def tearDown(self):
        self.store.close()

    def test_resume_then_all_cached(self):
        backend = CountingAnalyzer()
        partial = analyze(self.store, self.topic, self.config, analyzer=backend, stop_after=1)
        self.assertEqual(partial["statistics"]["state"], "interrupted")
        resumed = analyze(self.store, self.topic, self.config, analyzer=backend)
        self.assertEqual(partial["run_id"], resumed["run_id"])
        self.assertEqual(resumed["statistics"]["cached_fragments"], 1)
        self.assertEqual(resumed["statistics"]["coverage_percent"], 100)
        calls = backend.calls
        repeated = analyze(self.store, self.topic, self.config, analyzer=backend)
        self.assertEqual(calls, backend.calls)
        self.assertEqual(repeated["statistics"]["cached_fragments"], repeated["statistics"]["selected_fragments"])

    def test_errors_retried(self):
        backend = CountingAnalyzer(fail=True)
        failed = analyze(self.store, self.topic, self.config, analyzer=backend)
        self.assertTrue(failed["errors"])
        backend.fail = False
        recovered = analyze(self.store, self.topic, self.config, analyzer=backend)
        self.assertEqual(recovered["errors"], [])
        self.assertEqual(recovered["statistics"]["coverage_percent"], 100)

    def test_topic_and_corpus_invalidate(self):
        first = analyze(self.store, self.topic, self.config)
        other = analyze(self.store, Topic("Другая тема"), self.config)
        self.assertNotEqual(first["run_id"], other["run_id"])
        data = json.loads((ROOT / "examples/synthetic/dev.json").read_text(encoding="utf-8"))
        data["messages"][0]["text"] += " Синтетическая правка"
        import_export(self.store, data)
        changed = analyze(self.store, self.topic, self.config)
        self.assertNotEqual(first["run_id"], changed["run_id"])

    def test_feedback_and_report_links(self):
        report = analyze(self.store, self.topic, self.config)
        finding = report["findings"][0]
        save_feedback(self.store, report["run_id"], finding["id"], "correct")
        self.assertEqual(get_report(self.store, report["run_id"])["run_id"], report["run_id"])
        html = render_html(report)
        for finding in report["findings"]:
            for item in finding["evidence"]:
                self.assertIn(f"id='{item['anchor']}'", html)
        self.assertFalse((ROOT / "hacked.txt").exists())

    def test_empty_period_is_explicit_error(self):
        with self.assertRaises(ValueError):
            analyze(self.store, self.topic, self.config, since="2099-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
