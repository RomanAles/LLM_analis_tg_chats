import json
import unittest

from pre_relis import ModelResponseError, collect_purchases, extract_text, parse_purchase


class LegacyTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            {"id": 1, "type": "message", "from": "Синт_А", "text": "Купил тестовый диск за 100 руб."},
            {"id": 2, "type": "message", "from": "Синт_Б", "text": "Поздравляю!"},
        ]
        self.found = {"status": "found", "who": "Синт_А", "item": "тестовый диск", "price": "100 руб.",
                      "evidence_message_ids": [1]}

    def test_preserves_entities(self):
        self.assertEqual(extract_text({"text": ["Про ", {"type": "bold", "text": "NAS"}, " подробно"]}),
                         "Про NAS подробно")

    def test_invalid_response_is_not_empty_result(self):
        with self.assertRaises(ModelResponseError):
            parse_purchase("broken", self.messages)
        results, errors = collect_purchases(self.messages, lambda _: "broken")
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 2)

    def test_deduplicates_and_keeps_actual_evidence(self):
        results, errors = collect_purchases(self.messages, lambda _: json.dumps(self.found))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["evidence_message_ids"], [1])
        self.assertEqual(errors, [])

    def test_unknown_evidence_rejected(self):
        with self.assertRaises(ModelResponseError):
            parse_purchase(json.dumps({**self.found, "evidence_message_ids": [999]}), self.messages)

    def test_no_purchase_has_separate_status(self):
        self.assertEqual(parse_purchase('{"status":"not_found"}', self.messages),
                         {"status": "not_found"})


if __name__ == "__main__":
    unittest.main()
