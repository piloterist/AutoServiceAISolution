import unittest

import numpy as np

import vehicle_presence as vp

MODEL = vp.ensure_model(download=False)


@unittest.skipIf(MODEL is None, "модель детектора не скачана")
class VehiclePresenceTest(unittest.TestCase):
    def test_a_black_frame_does_not_prove_an_empty_bay(self):
        presence = vp.VehiclePresence(MODEL).check(np.zeros((1080, 1920, 3), np.uint8))
        self.assertTrue(presence.present and presence.dark)

    def test_a_lit_frame_without_a_car_is_empty(self):
        frame = np.full((1080, 1920, 3), 120, np.uint8)
        presence = vp.VehiclePresence(MODEL).check(frame)
        self.assertFalse(presence.present or presence.dark)


if __name__ == "__main__":
    unittest.main()
