import tempfile
import unittest
from pathlib import Path

import numpy as np

import plates
import read_log
from bay_tracker import Detection
from test_plates import probs_for


class Result:  # то, что журналу нужно от plates.PlateResult
    plate, raw, matched, work_order_number = "Е560КС977", "Е560КС97", True, "ЗН-1"
    confidence, reliable = 0.9, True


class Event:
    kind, result = "entry_confirmed", Result()


class ReadLogTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.log = read_log.ReadLog("cam1", Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def _records(self):
        (path,) = Path(self.tmp.name).glob("*.jsonl")
        return read_log.load(path)

    def test_reads_are_logged_with_decode_and_top_candidates(self):
        det = Detection(1300, 900, 330, 0.9, probs_for("E560KC977"))
        self.log.read(1, "APPROACH", det)
        (record,) = self._records()
        self.assertEqual((record["text"], record["track"], record["state"]), ("Е560КС977", 1, "APPROACH"))
        self.assertEqual(len(record["top"]), plates.SLOTS)
        self.assertLessEqual(len(record["top"][0]), read_log.TOP_PER_SLOT)

    def test_a_read_without_ocr_is_still_logged(self):
        self.log.read(1, "EMPTY", Detection(1300, 900, 70, 0.6, None))
        self.assertIsNone(self._records()[0]["text"])

    def test_report_separates_the_models_reading_from_the_base_help(self):
        for width in (90, 140, 200, 330):
            self.log.read(1, "APPROACH", Detection(1300, 900, width, 0.9, probs_for("E560KC97")))
        self.log.decision(1, Event())
        text = read_log.report(self._records())
        self.assertIn("след 1", text)
        self.assertIn("прочитано без базы Е560КС97", text)
        self.assertIn("НОМЕР ИСПРАВЛЕН БАЗОЙ", text)
        for label in ("3 м", "5 м", "8 м", "12 м"):
            self.assertIn(label, text)

    def test_report_without_data(self):
        self.assertEqual(read_log.report([]), "Нет данных для отчёта.")

    def test_buckets(self):
        self.assertEqual(read_log.bucket(330)[:3], "3 м")
        self.assertEqual(read_log.bucket(86)[:4], "12 м")
        np.testing.assert_allclose(len(read_log.BUCKETS), 4)


if __name__ == "__main__":
    unittest.main()
