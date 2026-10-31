import unittest
from dataclasses import replace

from tg_chat_analyzer.config import AnalysisConfig
from tg_chat_analyzer.context import build_fragments
from tg_chat_analyzer.models import Message


def msg(i, text="Синтетическое сообщение", reply=None, chat="test", thread=None):
    return Message(chat, i, f"2026-01-10T10:{i:02}:00+00:00", "Синт", "s1", text, reply, thread)


class ContextTests(unittest.TestCase):
    def test_interleaved_replies_do_not_mix(self):
        messages = [msg(1, "NAS"), msg(2, "Игра"), msg(3, "У меня тоже", 1), msg(4, "Да", 2)]
        sets = [{m.id for m in f.messages} for f in build_fragments(messages)]
        self.assertIn({1, 3}, sets)
        self.assertIn({2, 4}, sets)

    def test_full_coverage_and_budget(self):
        messages = [msg(1, "А" * 1400), msg(2, "Б" * 100), msg(3, "Ответ", 1)]
        fragments = build_fragments(messages, AnalysisConfig(context_chars=256, max_messages=2))
        self.assertEqual({key for f in fragments for key in f.target_keys}, {m.key for m in messages})
        pieces = [m.text for f in fragments for m in f.messages if m.id == 1 and m.key in f.target_keys]
        self.assertEqual("".join(pieces), messages[0].text)
        self.assertTrue(all(len(f.text) <= 256 for f in fragments))

    def test_cycles_and_missing_parent_do_not_hang(self):
        fragments = build_fragments([msg(1, reply=2), msg(2, reply=1), msg(3, reply=999)])
        self.assertEqual({k for f in fragments for k in f.target_keys}, {"test:1", "test:2", "test:3"})
        self.assertTrue(any(f.truncated for f in fragments))

    def test_threads_and_chats_are_separate(self):
        fragments = build_fragments([msg(1, thread=10), msg(2, thread=20), msg(1, chat="other", thread=10)])
        self.assertEqual(len(fragments), 3)


if __name__ == "__main__":
    unittest.main()
