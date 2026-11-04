"""Ручной ввод и просмотр журнала событий боксов (до появления автоматического распознавания).

    events_cli.py state
    events_cli.py list [--bay bay1] [--limit 20]
    events_cli.py add --bay bay1 --type entry_confirmed --plate А123ВС77 [--snapshot] [--note "..."]

--snapshot снимает кадр с камеры бокса и прикладывает его к событию
(captures/events/<бокс>/<дата>/<id>.jpg).
Ручные события помечаются source=manual, review_status=confirmed.
"""

import argparse
import sys
import uuid
from datetime import datetime

import bay_events as be
from stream_check import KEYRING_SERVICE, build_url, cv2, get_password, open_capture  # noqa: F401


def take_snapshot(camera: dict, bay_id: str, event_id: str) -> str | None:
    password = get_password(camera["user"])
    url = build_url(
        camera["ip"], str(camera["rtsp_port"]), camera["user"], password, camera["stream_path"],
        mask=False,
    )  # fmt: skip
    cap = open_capture(url)
    frame = None
    try:
        for _ in range(30):  # первые кадры после подключения могут быть битыми
            ok, candidate = cap.read()
            if ok and candidate is not None:
                frame = candidate
    finally:
        cap.release()
    if frame is None:
        return None
    folder = be.ROOT / "captures" / "events" / bay_id / datetime.now().strftime("%Y-%m-%d")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{event_id}.jpg"
    cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return str(path.relative_to(be.ROOT))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("state")
    p_list = sub.add_parser("list")
    p_list.add_argument("--bay")
    p_list.add_argument("--limit", type=int, default=20)
    p_add = sub.add_parser("add")
    p_add.add_argument("--bay", required=True)
    p_add.add_argument("--type", required=True, choices=sorted(be.EVENT_TYPES))
    p_add.add_argument("--plate")
    p_add.add_argument("--note")
    p_add.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()

    config = be.load_config()
    bays = {b["id"]: b for b in config["bay"]}
    cameras = {c["id"]: c for c in config["camera"]}
    conn = be.connect()

    if args.cmd == "state":
        for bay in bays.values():
            s = be.bay_state(conn, bay["id"])
            extra = f"  номер {s['plate']}, с {s['since']}" if s["state"] != "EMPTY" else ""
            print(f"{bay['name']} ({bay['id']}): {s['state']}{extra}")
    elif args.cmd == "list":
        query = "SELECT * FROM events"
        params: list = []
        if args.bay:
            query += " WHERE bay_id = ?"
            params.append(args.bay)
        rows = conn.execute(query + " ORDER BY ts DESC LIMIT ?", (*params, args.limit)).fetchall()
        for r in rows:
            print(
                f"{r['ts']}  {r['bay_id']}  {r['event_type']:<17} {r['plate_normalized'] or '-':<10}"
                f" {r['review_status']:<12} {r['source']:<6} {r['snapshot_path'] or ''}"
            )
    else:
        if args.bay not in bays:
            print(f"Нет бокса {args.bay!r} в bays.toml. Есть: {', '.join(bays)}")
            return 2
        camera = cameras[bays[args.bay]["camera_id"]]
        event_id = str(uuid.uuid4())
        snapshot = take_snapshot(camera, args.bay, event_id) if args.snapshot else None
        if args.snapshot and snapshot is None:
            print("Снимок не получен, событие записано без снимка.")
        be.record_event(
            conn, bay_id=args.bay, camera_id=camera["id"], event_type=args.type,
            plate_raw=args.plate, plate_normalized=args.plate, snapshot_path=snapshot,
            review_status="confirmed", source="manual", note=args.note, event_id=event_id,
        )  # fmt: skip
        print(f"Записано {args.type} для {args.bay}, id {event_id}")
        print(be.bay_state(conn, args.bay))
    return 0


if __name__ == "__main__":
    sys.exit(main())
