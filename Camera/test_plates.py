import unittest

import numpy as np

import plates


def probs_for(text: str, sure: float = 0.9) -> np.ndarray:
    """Матрица вероятностей, где каждая позиция уверена в своём символе на `sure`.

    `text` - 10 позиций латиницей, `_` = пусто (короткий номер дополняется пустыми)."""
    text = text.ljust(plates.SLOTS, "_")
    matrix = np.full((plates.SLOTS, len(plates.ALPHABET)), (1 - sure) / (len(plates.ALPHABET) - 1))
    for slot, char in enumerate(text):
        matrix[slot, plates.ALPHABET.index(char)] = sure
    return matrix


def reads_of(*items: tuple[np.ndarray, float]) -> plates.SlotReads:
    reads = plates.SlotReads()
    for matrix, weight in items:
        reads.add(matrix, weight)
    return reads


class DecodeTest(unittest.TestCase):
    def test_clean_read(self):
        text, confidences = plates.decode(probs_for("E560KC977"))
        self.assertEqual(text, "Е560КС977")
        self.assertGreater(min(confidences[:6]), 0.8)

    def test_two_digit_region(self):
        self.assertEqual(plates.decode(probs_for("E560KC77"))[0], "Е560КС77")

    def test_letter_slot_never_becomes_a_digit_and_a_dropped_letter_is_recovered(self):
        matrix = probs_for("E560K_977", sure=0.9)  # модель «потеряла» вторую букву
        matrix[5, plates.ALPHABET.index("C")] = 0.3  # но «С» у неё второй по вероятности
        self.assertEqual(plates.decode(matrix)[0], "Е560КС977")

    def test_digit_slot_ignores_a_letter_that_looks_like_a_digit(self):
        matrix = probs_for("E560KC977", sure=0.3)
        matrix[2, plates.ALPHABET.index("O")] = 0.6  # на месте цифры модель увидела «О»
        matrix[2, plates.ALPHABET.index("6")] = 0.3
        self.assertEqual(plates.decode(matrix)[0], "Е560КС977")

    def test_normalize_read(self):
        self.assertEqual(plates.normalize_read("e 560 kc 977"), "Е560КС977")


class ResolveTest(unittest.TestCase):
    KNOWN = {"Е560КС977": "ЗН-1", "А111АА77": "ЗН-2"}

    def test_known_plate_is_matched_even_when_the_read_drops_the_region_digit(self):
        reads = reads_of((probs_for("E560KC77"), 1.0), (probs_for("E560KC977"), 1.0))
        result = plates.resolve_plate(reads, plates.KnownPlates(self.KNOWN))
        self.assertTrue(result.matched)
        self.assertEqual((result.plate, result.work_order_number), ("Е560КС977", "ЗН-1"))
        self.assertTrue(result.reliable)

    def test_unknown_confident_plate_is_reliable_without_a_match(self):
        reads = reads_of((probs_for("T123YX199"), 3.0))
        result = plates.resolve_plate(reads, plates.KnownPlates(self.KNOWN))
        self.assertFalse(result.matched)
        self.assertEqual(result.plate, "Т123УХ199")
        self.assertTrue(result.reliable)

    def test_unsure_unknown_plate_needs_review(self):
        reads = reads_of((probs_for("T123YX199", sure=0.3), 3.0))
        result = plates.resolve_plate(reads, plates.KnownPlates(self.KNOWN))
        self.assertFalse(result.matched)
        self.assertFalse(result.reliable)

    def test_near_duplicate_known_plates_are_not_guessed_from_a_blurry_read(self):
        known = plates.KnownPlates({"Е560КС977": "ЗН-1", "Е560КС797": "ЗН-2"})
        blurry = probs_for("E560KC977", sure=0.2)
        self.assertFalse(plates.resolve_plate(reads_of((blurry, 1.0)), known).matched)

    def test_weights_favour_the_sharper_frames(self):
        good, bad = probs_for("E560KC977"), probs_for("E500KC977")
        reads = reads_of((good, 5.0), (bad, 1.0))
        self.assertEqual(plates.resolve_plate(reads).plate, "Е560КС977")

    def test_nothing_read(self):
        result = plates.resolve_plate(plates.SlotReads())
        self.assertIsNone(result.plate)
        self.assertFalse(result.reliable)

    def test_known_index_skips_malformed_plates(self):
        self.assertEqual(len(plates.KnownPlates({"Е560КС977": "1", "ABC": "2", "1234567": "3"})), 1)


if __name__ == "__main__":
    unittest.main()
