import copy
import json
import unittest
from pathlib import Path

from tg_chat_analyzer.importer import import_export
from tg_chat_analyzer.storage import Store

ROOT = Path(__file__).resolve().parents[1]


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.data = json.loads((ROOT / "examples/synthetic/dev.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.store.close()

    def test_idempotent_and_edits(self):
        first = import_export(self.store, self.data)
        second = import_export(self.store, self.data)
        self.assertEqual((first["inserted"], second["unchanged"]), (21, 21))
        self.data["messages"][0]["text"] = "Отредактировано синтетически"
        self.assertEqual(import_export(self.store, self.data)["updated"], 1)
        self.assertEqual(len(self.store.messages()), 21)

    def test_two_chats_same_message_id(self):
        import_export(self.store, self.data)
        another = copy.deepcopy(self.data)
        another["id"] = -990003
        import_export(self.store, another)
        self.assertEqual(len(self.store.messages()), 42)

    def test_partial_errors_are_visible(self):
        self.data["messages"].extend([None, {"type": "message", "id": 0}])
        report = import_export(self.store, self.data)
        self.assertEqual(len(report["errors"]), 2)
        self.assertEqual(report["attachments"], 1)
        self.assertEqual(report["service"], 1)
        self.assertTrue(report["warnings"])

    def test_entities_links_and_missing_author(self):
        import_export(self.store, self.data)
        messages = {m.id: m for m in self.store.messages()}
        self.assertIn("NAS", messages[5].text)
        self.assertEqual(messages[2].reply_to, 1)
        self.assertIsNone(messages[16].author_id)
        self.assertTrue(messages[1].date.endswith("+00:00"))

    def test_broken_export_rejected(self):
        with self.assertRaises(ValueError):
            import_export(self.store, {"messages": "bad"})

    def test_timezone_change_updates_normalized_dates(self):
        import_export(self.store, self.data, utc_offset_hours=7)
        before = self.store.messages()[0].date
        report = import_export(self.store, self.data, utc_offset_hours=0)
        self.assertEqual(report["updated"], 21)
        self.assertNotEqual(before, self.store.messages()[0].date)


if __name__ == "__main__":
    unittest.main()
