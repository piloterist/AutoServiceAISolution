import unittest

import numpy as np

import plates
from bay_tracker import Detection
from gate_tracker import EMPTY, TRACK, GateConfig, GateTracker, MotionGate
from test_plates import probs_for

DT = 1 / 6
KNOWN = plates.KnownPlates({"Е560КС977": "ЗН-1"})


def det(width, cx=1300.0, text="E560KC977", sure=0.9, conf=0.8):
    return Detection(cx=cx, cy=900.0, width=width, conf=conf, probs=probs_for(text, sure))


def tracker(**kw):
    return GateTracker(GateConfig(**kw), known=KNOWN)


class Run:
    """Подаёт трекеру кадры с шагом DT и собирает события."""

    def __init__(self, tr):
        self.tracker, self.t, self.events = tr, 0.0, []

    def pass_by(self, widths, text="E560KC977", sure=0.9, conf=0.8, cx=1300.0):
        for width in widths:
            self.events += self.tracker.update(
                self.t, det(width, cx=cx, text=text, sure=sure, conf=conf), frame=f"w{width:.0f}"
            )
            self.t += DT

    def empty(self, seconds):
        for _ in range(round(seconds / DT)):
            self.events += self.tracker.update(self.t, None, frame="empty")
            self.t += DT


GROW = [90, 110, 140, 180, 230, 300, 380]  # едет к камере
SHRINK = GROW[::-1]  # уезжает


class GateTrackerTest(unittest.TestCase):
    def test_a_growing_plate_is_an_entry(self):
        run = Run(tracker())
        run.pass_by(GROW)
        self.assertEqual(run.events, [])  # пока след идёт, решения нет
        self.assertEqual(run.tracker.state, TRACK)
        run.empty(2)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed"])
        event = run.events[0]
        self.assertEqual((event.result.plate, event.result.matched), ("Е560КС977", True))
        self.assertEqual(event.result.work_order_number, "ЗН-1")
        self.assertEqual(event.frame, "w380")  # кадр с самым крупным номером
        self.assertEqual(run.tracker.state, EMPTY)

    def test_a_shrinking_plate_is_an_exit(self):
        run = Run(tracker())
        run.pass_by(SHRINK)
        run.empty(2)
        self.assertEqual([e.kind for e in run.events], ["exit_confirmed"])
        self.assertEqual(run.events[0].frame, "w380")

    def test_the_event_time_is_the_middle_of_the_pass(self):
        run = Run(tracker())
        run.pass_by(GROW)
        end = DT * (len(GROW) - 1)
        run.empty(2)
        self.assertAlmostEqual(run.events[0].t, end / 2)

    def test_two_cars_in_a_row_give_two_events(self):
        run = Run(tracker())
        run.pass_by(GROW, text="E560KC977")
        run.empty(2)  # разрыв больше gap_sec
        run.pass_by(SHRINK, text="T123YX199")
        run.empty(2)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed", "exit_confirmed"])
        self.assertEqual(run.events[0].result.plate, "Е560КС977")
        self.assertEqual(run.events[1].result.plate, "Т123УХ199")

    def test_a_car_right_behind_another_is_a_new_track_by_the_position_jump(self):
        run = Run(tracker())
        run.pass_by(GROW, text="E560KC977", cx=1300.0)  # без паузы между машинами
        run.pass_by([100, 130, 170, 220, 290], text="T123YX199", cx=300.0)
        run.empty(2)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed", "entry_confirmed"])
        self.assertEqual(run.events[0].result.plate, "Е560КС977")
        self.assertEqual(run.events[1].result.plate, "Т123УХ199")

    def test_a_width_jump_also_starts_a_new_track(self):
        run = Run(tracker())
        run.pass_by(GROW)  # закончилась на 380
        run.pass_by([100, 130, 170, 220])  # тут же 100: ширина упала больше чем вдвое
        run.empty(2)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed", "entry_confirmed"])

    def test_an_unclear_direction_gives_no_event_but_is_counted(self):
        run = Run(tracker())
        run.pass_by([200, 205, 195, 210, 200, 198])  # почти не меняется
        run.empty(2)
        self.assertEqual(run.events, [])
        self.assertEqual(run.tracker.unclear, 1)
        self.assertIn("без ясного направления", run.tracker.notes[-1])

    def test_too_few_detections_give_nothing(self):
        run = Run(tracker())
        run.pass_by([150, 200])
        run.empty(2)
        self.assertEqual(run.events, [])
        self.assertEqual(run.tracker.too_short, 1)

    def test_a_gap_inside_the_pass_splits_it_into_two_tracks(self):
        run = Run(tracker())
        run.pass_by([90, 110, 140])
        run.empty(2)  # разрыв больше gap_sec: первая часть закончилась
        run.pass_by([180, 230, 300])
        run.empty(2)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed", "entry_confirmed"])

    def test_an_unreadable_plate_still_gives_an_event_without_a_plate(self):
        run = Run(tracker())
        for width in GROW:
            run.events += run.tracker.update(
                run.t, Detection(cx=1300.0, cy=900.0, width=width, conf=0.8, probs=None), frame="f"
            )
            run.t += DT
        run.empty(2)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed"])
        self.assertIsNone(run.events[0].result.plate)
        self.assertFalse(run.events[0].result.reliable)

    def test_a_plate_not_in_known_is_read_as_is_and_may_be_unreliable(self):
        run = Run(tracker())
        run.pass_by(GROW, text="M777MM199", sure=0.9)
        run.empty(2)
        result = run.events[0].result
        self.assertEqual((result.plate, result.matched), ("М777ММ199", False))
        self.assertTrue(result.reliable)
        run = Run(tracker())
        run.pass_by(GROW, text="M777MM199", sure=0.2)  # шумное чтение
        run.empty(2)
        self.assertFalse(run.events[0].result.reliable)

    def test_tiny_or_unsure_detections_are_ignored(self):
        run = Run(tracker())
        run.pass_by([30, 40, 50, 55])  # мельче min_width
        run.empty(2)
        self.assertEqual(run.events, [])
        self.assertEqual(run.tracker.state, EMPTY)
        run.pass_by(GROW, conf=0.2)  # уверенность детектора ниже min_conf
        run.empty(2)
        self.assertEqual(run.events, [])

    def test_flush_finishes_a_pass_in_progress(self):
        run = Run(tracker())
        run.pass_by(GROW)
        events = run.tracker.flush()
        self.assertEqual([e.kind for e in events], ["entry_confirmed"])
        self.assertEqual(run.tracker.state, EMPTY)

    def test_known_plates_may_be_passed_as_a_plain_dict(self):
        run = Run(GateTracker(GateConfig(), known={"Е560КС977": "ЗН-1"}))
        run.pass_by(GROW)
        run.empty(2)
        self.assertEqual(run.events[0].result.work_order_number, "ЗН-1")


class MotionGateTest(unittest.TestCase):
    @staticmethod
    def frame(value):
        return np.full((360, 640, 3), value, np.uint8)

    def test_disabled_gate_is_always_active(self):
        gate = MotionGate(threshold=0)
        self.assertTrue(gate.active(0.0, self.frame(10)))
        self.assertTrue(gate.active(100.0, self.frame(10)))

    def test_a_still_scene_sleeps_and_motion_wakes_it_for_the_hold(self):
        gate = MotionGate(threshold=2.0, hold_sec=4.0)
        self.assertTrue(gate.active(0.0, self.frame(10)))  # первый кадр: сравнить не с чем
        self.assertFalse(gate.active(5.0, self.frame(10)))  # без изменений, hold прошёл
        self.assertTrue(gate.active(5.2, self.frame(120)))  # резкое изменение
        self.assertTrue(gate.active(8.0, self.frame(120)))  # изменений нет, но держим 4 с
        self.assertFalse(gate.active(10.0, self.frame(120)))

    def test_a_detection_keeps_it_awake(self):
        gate = MotionGate(threshold=2.0, hold_sec=4.0)
        gate.active(0.0, self.frame(10))
        gate.active(5.0, self.frame(10))
        gate.note_detection(5.0)
        self.assertTrue(gate.active(8.0, self.frame(10)))
        self.assertFalse(gate.active(9.5, self.frame(10)))

    def test_small_noise_does_not_wake_it(self):
        gate = MotionGate(threshold=2.0, hold_sec=1.0)
        base = self.frame(100)
        gate.active(0.0, base)
        noise = np.random.default_rng(1).integers(-1, 2, base.shape)
        noisy = np.clip(base.astype(np.int16) + noise, 0, 255).astype(np.uint8)
        self.assertFalse(gate.active(5.0, noisy))


if __name__ == "__main__":
    unittest.main()
