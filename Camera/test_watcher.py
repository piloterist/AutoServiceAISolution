import time
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from watcher import CAMERA_STALE_SEC, CameraWatcher

MSK = ZoneInfo("Europe/Moscow")
SCHEDULE = {"work_start": "08:00:00", "work_end": "20:00:00", "work_days": [0, 1, 2, 3, 4]}


def watcher() -> CameraWatcher:
    return CameraWatcher({"id": "cam1"}, {"timezone": "Europe/Moscow"}, {}, "http://x", {})


def at(day: int, hour: int, minute: int = 0) -> float:
    # 2026-11-02 - понедельник
    return datetime(2026, 11, day, hour, minute, tzinfo=MSK).timestamp()


class WorkHoursTest(unittest.TestCase):
    def test_no_schedule_means_always(self):
        self.assertTrue(watcher().in_work_hours(at(2, 3)))

    def test_inside_hours_and_margin(self):
        w = watcher()
        w.schedule = SCHEDULE
        self.assertTrue(w.in_work_hours(at(2, 12)))
        self.assertTrue(w.in_work_hours(at(2, 7, 40)))  # за полчаса до начала
        self.assertTrue(w.in_work_hours(at(2, 20, 20)))
        self.assertFalse(w.in_work_hours(at(2, 7, 20)))
        self.assertFalse(w.in_work_hours(at(2, 21)))

    def test_days_off(self):
        w = watcher()
        w.schedule = SCHEDULE
        self.assertFalse(w.in_work_hours(at(7, 12)))  # суббота


class CameraStatusTest(unittest.TestCase):
    class Reader:
        def __init__(self, age: float, alive: bool = True):
            self.alive, self.last_grab = alive, time.time() - age

    def test_camera_is_ok_only_while_frames_keep_coming(self):
        w = watcher()
        self.assertFalse(w.camera_ok)  # потока ещё нет
        w.reader = self.Reader(1)
        self.assertTrue(w.camera_ok)
        w.reader = self.Reader(CAMERA_STALE_SEC + 5)
        self.assertFalse(w.camera_ok)
        w.reader = self.Reader(1, alive=False)
        self.assertFalse(w.camera_ok)


if __name__ == "__main__":
    unittest.main()
