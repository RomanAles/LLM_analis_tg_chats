import unittest

from tg_chat_analyzer.config import Topic
from tg_chat_analyzer.context import build_fragments
from tg_chat_analyzer.local_api import LocalAPI
from tg_chat_analyzer.models import Message
from tg_chat_analyzer.search import rank_fragments, relevant_messages


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.messages = [Message("s", i, f"2026-01-01T10:0{i}:00+00:00", "Синт", "a", text, reply)
                         for i, text, reply in [(1, "NAS шумит", None), (2, "Да, у меня тоже", 1),
                                                (3, "Игры", None), (4, "Гонки NASCAR", None)]]
        self.topic = Topic("Хранилища", keywords=["NAS"], exclude_keywords=["NASCAR"])

    def test_reply_and_exclusion(self):
        self.assertEqual(set(relevant_messages(self.messages, self.topic)), {"s:1", "s:2"})

    def test_overview_never_drops_zero_score_fragments(self):
        fragments = build_fragments(self.messages)
        self.assertEqual(len(rank_fragments(fragments, self.topic)), len(fragments))
        self.assertEqual(len(rank_fragments(fragments, self.topic, "question", 1)), 1)

    def test_semantic_path_finds_no_keyword(self):
        topic = Topic("Неизвестная формулировка", keywords=["нетсовпадений"])
        fragments = build_fragments(self.messages)
        calls = []
        def embed(texts):
            calls.append(texts)
            return [[1., 0.] for _ in texts]
        self.assertEqual(len(rank_fragments(fragments, topic, "question", 1, embed)), 1)
        self.assertGreaterEqual(len(calls), 2)

    def test_external_endpoints_rejected(self):
        for url in ["https://example.com", "http://127.0.0.1.evil.com", "http://user:pass@localhost", "http://localhost/api"]:
            with self.assertRaises(ValueError):
                LocalAPI(url)

    def test_long_message_keeps_keyword_from_first_piece(self):
        from dataclasses import replace
        from tg_chat_analyzer.config import AnalysisConfig
        message = replace(self.messages[0], text="NAS " + "разный текст " * 100)
        fragments = build_fragments([message], AnalysisConfig(context_chars=256))
        self.assertTrue(rank_fragments(fragments, self.topic, "question", 1))


if __name__ == "__main__":
    unittest.main()
