import json
import unittest

from tg_chat_analyzer.analysis import ExtractiveAnalyzer, parse_result
from tg_chat_analyzer.config import Topic
from tg_chat_analyzer.context import build_fragments
from tg_chat_analyzer.legacy import ModelResponseError
from tg_chat_analyzer.models import Message
from tg_chat_analyzer.report import csv_safe, render_html


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.topic = Topic("NAS", keywords=["NAS"])
        self.message = Message("s", 1, "2026-01-01T00:00:00+00:00", "Синт", "s", "NAS шумит <script>bad()</script>")
        self.fragment = build_fragments([self.message])[0]
        self.response = {"status": "found", "findings": [{"type": "problem", "subtopic": "Шум",
            "claim": "Автор сообщает о шуме", "evidence": [{"key": "s:1", "quote": "NAS шумит"}]}]}

    def test_grounded_response(self):
        result = parse_result(json.dumps(self.response), self.fragment, self.topic)
        self.assertTrue(result["findings"][0]["evidence_validated"])
        self.assertEqual(result["findings"][0]["review_status"], "pending")

    def test_fabricated_quote_rejected(self):
        self.response["findings"][0]["evidence"][0]["quote"] = "NAS бесшумен"
        with self.assertRaises(ModelResponseError):
            parse_result(json.dumps(self.response), self.fragment, self.topic)

    def test_fabricated_key_rejected(self):
        self.response["findings"][0]["evidence"][0]["key"] = "other:1"
        with self.assertRaises(ModelResponseError):
            parse_result(json.dumps(self.response), self.fragment, self.topic)

    def test_extractive_is_labelled_and_does_not_execute_text(self):
        result = ExtractiveAnalyzer().analyze(self.fragment, self.topic)
        self.assertEqual(result["findings"][0]["type"], "excerpt")
        self.assertIn("<script>", result["findings"][0]["evidence"][0]["quote"])

    def test_csv_formula_neutralized(self):
        self.assertEqual(csv_safe("=1+1"), "'=1+1")


if __name__ == "__main__":
    unittest.main()
