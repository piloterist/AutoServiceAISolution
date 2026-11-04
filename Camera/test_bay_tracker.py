import unittest

import plates
from bay_tracker import EMPTY, LEAVING, PARKED, BayTracker, Detection, TrackerConfig
from test_plates import probs_for

DT = 0.33
KNOWN = plates.KnownPlates({"Е560КС977": "ЗН-1"})


def det(width, cx=1300.0, text="E560KC977", sure=0.9, conf=0.8):
    return Detection(cx=cx, cy=900.0, width=width, conf=conf, probs=probs_for(text, sure))


class Run:
    """Подаёт трекеру кадры с шагом DT и собирает события."""

    def __init__(self, tracker):
        self.tracker, self.t, self.events = tracker, 0.0, []

    def feed(self, seconds, detection=None, width=None, **kw):
        for _ in range(round(seconds / DT)):
            d = detection if detection is not None else (det(width, **kw) if width else None)
            frame = f"w{width}" if width else "empty"
            self.events += self.tracker.update(self.t, d, frame=frame)
            self.t += DT

    def approach(self, start=110, end=330, seconds=5, text="T123YX199"):
        """Едет к месту: номер растёт и смещается; пока едет, OCR читает мусор (смазано)."""
        steps = round(seconds / DT)
        for i in range(steps):
            width = start + (end - start) * i / steps
            self.events += self.tracker.update(
                self.t, det(width, cx=1300 + (steps - i) * 60, text=text, sure=0.5), frame=f"w{width:.0f}"
            )
            self.t += DT


def tracker(**kw):
    return BayTracker(TrackerConfig(**kw), known=KNOWN)


def parked(run, seconds=8, width=330, **kw):
    run.approach()
    run.feed(seconds, width=width, **kw)


class BayTrackerTest(unittest.TestCase):
    def test_entry_is_confirmed_once_the_car_stands_still_close_enough(self):
        run = Run(tracker())
        run.approach()
        self.assertEqual(run.events, [])  # ещё едет
        run.feed(8, width=330)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed"])
        event = run.events[0]
        self.assertEqual((event.result.plate, event.result.matched), ("Е560КС977", True))
        self.assertEqual(event.result.work_order_number, "ЗН-1")
        self.assertEqual(event.frame, "w330")
        self.assertEqual(run.tracker.state, PARKED)

    def test_the_plate_is_read_from_the_standing_car_not_from_the_moving_one(self):
        run = Run(tracker())
        run.approach(text="T123YX199")  # пока едет, читается другое
        run.feed(8, width=330)
        self.assertEqual(run.events[0].result.plate, "Е560КС977")

    def test_far_parked_car_is_not_an_entry(self):
        run = Run(tracker())
        run.feed(30, width=120)
        self.assertEqual(run.events, [])

    def test_drive_by_gives_no_events(self):
        run = Run(tracker())
        for i in range(30):
            run.events += run.tracker.update(run.t, det(140, cx=400 + i * 60), frame=None)
            run.t += DT
        run.feed(10)  # пусто
        self.assertEqual(run.events, [])
        self.assertEqual(run.tracker.state, EMPTY)

    def test_unsure_reading_waits_for_more_frames_then_flags_the_entry(self):
        run = Run(tracker())
        run.approach()
        run.feed(6, width=330, text="T123YX199", sure=0.3)  # номер читается плохо
        self.assertEqual(run.events, [])  # ждём ещё кадров
        run.feed(8, width=330, text="T123YX199", sure=0.3)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed"])
        self.assertFalse(run.events[0].result.reliable)

    def test_occluded_plate_is_not_an_exit(self):
        run = Run(tracker())
        parked(run)
        run.feed(120)  # номер не виден минуты две
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed"])
        self.assertEqual(run.tracker.state, PARKED)

    def test_lift_moving_the_plate_up_is_not_leaving(self):
        run = Run(tracker())
        parked(run)
        for _ in range(30):
            moved = Detection(1300, 500.0, 330, 0.8, probs_for("E560KC977"))
            run.events += run.tracker.update(run.t, moved)
            run.t += DT
        self.assertEqual(run.tracker.state, PARKED)

    def test_exit_needs_the_car_to_leave_and_then_disappear(self):
        run = Run(tracker())
        parked(run)
        for width in (300, 250, 200, 150, 110, 90):  # машина уезжает, номер мельчает
            run.feed(1.0, width=width)
        self.assertEqual(run.tracker.state, LEAVING)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed"])
        run.feed(25)  # ушла из кадра
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed", "exit_confirmed"])
        exit_event = run.events[1]
        self.assertEqual(exit_event.result.plate, "Е560КС977")  # номер не перечитывается
        self.assertEqual(run.tracker.state, EMPTY)

    def test_the_exit_frame_is_the_farthest_one(self):
        run = Run(tracker())
        parked(run)
        for width in (300, 250, 200, 150, 110, 90):
            run.feed(1.0, width=width)
        run.feed(25)
        self.assertEqual(run.events[1].frame, "w90")

    def test_car_that_comes_back_before_the_hold_is_not_an_exit(self):
        run = Run(tracker())
        parked(run)
        for width in (250, 200, 150):
            run.feed(1.0, width=width)
        run.feed(10)
        run.approach(start=150, end=330, seconds=4)
        run.feed(8, width=330)
        self.assertEqual([e.kind for e in run.events], ["entry_confirmed"])
        self.assertEqual(run.tracker.state, PARKED)

    def test_other_car_after_leaving_gives_exit_and_entry(self):
        run = Run(tracker())
        parked(run)
        for width in (250, 200, 150):
            run.feed(1.0, width=width)
        run.feed(14, width=330, text="T123YX199")
        self.assertEqual(
            [e.kind for e in run.events], ["entry_confirmed", "exit_confirmed", "entry_confirmed"]
        )
        self.assertEqual(run.events[1].result.plate, "Е560КС977")
        self.assertFalse(run.events[2].result.matched)
        self.assertEqual(run.events[2].result.plate, "Т123УХ199")

    def test_restart_with_occupied_bay_does_not_repeat_the_entry(self):
        run = Run(BayTracker(TrackerConfig(), known=KNOWN, occupied_plate="Е560КС977"))
        run.feed(15, width=330)
        self.assertEqual(run.events, [])
        for width in (250, 200, 150):
            run.feed(1.0, width=width)
        run.feed(25)
        self.assertEqual([e.kind for e in run.events], ["exit_confirmed"])

    def test_known_plates_may_be_passed_as_a_plain_dict(self):
        run = Run(BayTracker(TrackerConfig(), known={"Е560КС977": "ЗН-1"}))
        parked(run)
        self.assertEqual(run.events[0].result.work_order_number, "ЗН-1")


if __name__ == "__main__":
    unittest.main()
