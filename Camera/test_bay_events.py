import tempfile
import unittest
from pathlib import Path

import bay_events as be


class BayEventsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = be.connect(Path(self.tmp.name) / "e.sqlite")

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def rec(self, event_type, ts, plate=None, **kw):
        return be.record_event(
            self.conn, bay_id="bay1", camera_id="cam1", event_type=event_type, ts=ts,
            plate_normalized=plate, **kw,
        )  # fmt: skip

    def test_empty_bay_by_default(self):
        self.assertEqual(be.bay_state(self.conn, "bay1")["state"], "EMPTY")

    def test_entry_then_exit(self):
        self.rec("entry_confirmed", "2026-11-03T10:00:00+03:00", "А123ВС77")
        state = be.bay_state(self.conn, "bay1")
        self.assertEqual((state["state"], state["plate"]), ("OCCUPIED", "А123ВС77"))
        self.rec("exit_confirmed", "2026-11-03T11:00:00+03:00", "А123ВС77")
        self.assertEqual(be.bay_state(self.conn, "bay1")["state"], "EMPTY")

    def test_candidates_do_not_change_state(self):
        self.rec("entry_candidate", "2026-11-03T10:00:00+03:00", "А123ВС77")
        self.rec("plate_observed", "2026-11-03T10:00:05+03:00", "А123ВС77")
        self.assertEqual(be.bay_state(self.conn, "bay1")["state"], "EMPTY")
        self.rec("entry_confirmed", "2026-11-03T10:00:10+03:00", "А123ВС77")
        self.rec("exit_candidate", "2026-11-03T10:30:00+03:00", "А123ВС77")
        self.assertEqual(be.bay_state(self.conn, "bay1")["state"], "OCCUPIED")

    def test_same_plate_can_have_several_intervals(self):
        for hour in (9, 13):
            self.rec("entry_confirmed", f"2026-11-03T{hour:02d}:00:00+03:00", "А123ВС77")
            self.rec("exit_confirmed", f"2026-11-03T{hour:02d}:30:00+03:00", "А123ВС77")
        rows = self.conn.execute("SELECT * FROM occupancy WHERE ended_at IS NOT NULL").fetchall()
        self.assertEqual(len(rows), 2)

    def test_second_entry_without_exit_goes_to_review(self):
        self.rec("entry_confirmed", "2026-11-03T10:00:00+03:00", "А123ВС77")
        self.rec("entry_confirmed", "2026-11-03T10:05:00+03:00", "В777ОО77")
        self.assertEqual(be.bay_state(self.conn, "bay1")["state"], "REVIEW")

    def test_exit_without_open_interval_is_logged_only(self):
        self.rec("exit_confirmed", "2026-11-03T10:00:00+03:00")
        self.assertEqual(be.bay_state(self.conn, "bay1")["state"], "EMPTY")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)

    def test_duplicate_event_id_is_idempotent(self):
        self.rec("entry_confirmed", "2026-11-03T10:00:00+03:00", "А123ВС77", event_id="e1")
        self.rec("entry_confirmed", "2026-11-03T10:00:00+03:00", "А123ВС77", event_id="e1")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM occupancy").fetchone()[0], 1)

    def test_unknown_event_type_rejected(self):
        with self.assertRaises(ValueError):
            self.rec("teleport", "2026-11-03T10:00:00+03:00")

    def test_config_links_bay_to_existing_camera(self):
        cfg = be.load_config()
        cameras = {c["id"] for c in cfg["camera"]}
        for bay in cfg["bay"]:
            self.assertIn(bay["camera_id"], cameras)


if __name__ == "__main__":
    unittest.main()
