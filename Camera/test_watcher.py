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


class GateModeTest(unittest.TestCase):
    @staticmethod
    def gate_watcher(camera=None, detection=None) -> CameraWatcher:
        camera = {"id": "gate1", "mode": "gate", **(camera or {})}
        return CameraWatcher(camera, {"timezone": "Europe/Moscow"}, detection or {}, "http://x", {})

    def test_gate_camera_defaults_to_a_higher_frame_rate_and_ignores_the_global_one(self):
        self.assertTrue(self.gate_watcher().gate)
        self.assertEqual(self.gate_watcher().fps, 6.0)
        self.assertEqual(self.gate_watcher(detection={"fps": 3}).fps, 6.0)
        self.assertEqual(self.gate_watcher(camera={"fps": 8}).fps, 8.0)
        self.assertFalse(watcher().gate)
        self.assertEqual(watcher().fps, 3.0)

    def test_gate_fields_and_motion_threshold_come_from_the_detection_section(self):
        w = self.gate_watcher(detection={"gap_sec": 2.0, "grow_ratio": 1.6, "fps": 3, "motion_threshold": 2.5})
        self.assertEqual(w.gate_fields, {"gap_sec": 2.0, "grow_ratio": 1.6})
        self.assertEqual(w.motion_threshold, 2.5)
        self.assertEqual(self.gate_watcher().motion_threshold, 0.0)

    def _queued(self, w, kind, plate, reliable):
        import plates
        from pathlib import Path

        from bay_events import connect
        from bay_tracker import Event

        result = plates.PlateResult(plate, 0.95 if reliable else 0.3, False, summary="прочитано: x")
        w.bay_id = "bay"
        w._queue(Event(kind, at(2, 12), result, None), connect(Path(":memory:")))
        return w.outbox[-1]

    def test_gate_events_say_which_way_the_car_went(self):
        w = self.gate_watcher()
        entry = self._queued(w, "entry_confirmed", "А123ВС77", True)
        self.assertTrue(entry["note"].startswith("проезд ворот: въезд"))
        self.assertFalse(entry["needs_review"])
        exit_ = self._queued(w, "exit_confirmed", "А123ВС77", True)
        self.assertTrue(exit_["note"].startswith("проезд ворот: выезд"))
        self.assertNotIn("по треку", exit_["note"])

    def test_gate_events_with_a_weak_or_missing_plate_need_review_both_ways(self):
        w = self.gate_watcher()
        self.assertTrue(self._queued(w, "exit_confirmed", "А123ВС77", False)["needs_review"])
        self.assertTrue(self._queued(w, "entry_confirmed", None, False)["needs_review"])
        # у бокса выезд с ненадёжным номером на проверку не уходит (как раньше)
        bay = watcher()
        self.assertFalse(self._queued(bay, "exit_confirmed", "А123ВС77", False)["needs_review"])



class PresenceLoaderTest(unittest.TestCase):
    """Детектор машин готовится в фоне: долгое скачивание модели не должно задерживать узел
    (2026-11-19: узел 12 минут молчал, пока модель качалась по слабому каналу площадки)."""

    def test_a_slow_model_download_does_not_block_the_node(self):
        import threading

        import watcher as watcher_module

        gate = threading.Event()
        built = []

        class FakePresence:
            def __init__(self, model, **kwargs):
                built.append(model)

        original = (watcher_module.ensure_model, watcher_module.VehiclePresence)
        watcher_module.ensure_model = lambda: gate.wait(5) and "model.onnx"
        watcher_module.VehiclePresence = FakePresence
        try:
            w = watcher()
            started = time.monotonic()
            w._start_presence_loader()
            self.assertLess(time.monotonic() - started, 0.5)  # вернулось сразу, модель ещё "качается"
            self.assertIsNone(w.presence)
            gate.set()  # скачалась
            for _ in range(100):
                if w.presence is not None:
                    break
                time.sleep(0.02)
            self.assertIsInstance(w.presence, FakePresence)
            self.assertEqual(built, ["model.onnx"])
        finally:
            watcher_module.ensure_model, watcher_module.VehiclePresence = original

    def test_a_failed_download_retries_later_and_the_node_keeps_working(self):
        import watcher as watcher_module

        original = watcher_module.ensure_model
        watcher_module.ensure_model = lambda: None  # скачать не вышло
        try:
            w = watcher()
            w._start_presence_loader()
            time.sleep(0.2)
            self.assertIsNone(w.presence)  # без детектора: выезд только по номеру
            w.stop()  # поток повтора завершается по stop
        finally:
            watcher_module.ensure_model = original

    def test_the_presence_check_can_be_switched_off_in_the_settings(self):
        w = CameraWatcher({"id": "cam1"}, {"timezone": "Europe/Moscow"}, {"vehicle_check": False}, "http://x", {})
        w._start_presence_loader()
        self.assertIsNone(w.presence)


if __name__ == "__main__":
    unittest.main()
