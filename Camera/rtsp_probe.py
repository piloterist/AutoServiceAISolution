"""Проба RTSP-сервера камеры БЕЗ пароля: отвечает ли сервер и какие пути существуют.

Ответ 401 на DESCRIBE означает «сервер жив, путь существует, нужна авторизация».
404 - такого пути нет. Пароль не нужен и не используется.
"""

import os
import socket
import sys

HOST = os.environ.get("CAMERA_IP", "192.168.31.209")
PORT = int(os.environ.get("CAMERA_RTSP_PORT", "554"))
PATHS = ["/stream1", "/stream2", "/h264/ch1/main/av_stream", "/Streaming/Channels/101", "/"]


def rtsp_request(method: str, url: str, cseq: int) -> str:
    request = f"{method} {url} RTSP/1.0\r\nCSeq: {cseq}\r\nUser-Agent: camera-probe\r\n\r\n"
    with socket.create_connection((HOST, PORT), timeout=5) as sock:
        sock.settimeout(5)
        sock.sendall(request.encode())
        return sock.recv(4096).decode(errors="replace")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"RTSP-проба {HOST}:{PORT}")
    try:
        reply = rtsp_request("OPTIONS", f"rtsp://{HOST}:{PORT}/", 1)
    except OSError as exc:
        print(f"НЕТ СОЕДИНЕНИЯ: {exc}")
        return 1
    print("OPTIONS ->", reply.splitlines()[0] if reply else "(пусто)")
    for line in reply.splitlines():
        if line.lower().startswith(("server:", "public:")):
            print("  ", line)
    for path in PATHS:
        try:
            reply = rtsp_request("DESCRIBE", f"rtsp://{HOST}:{PORT}{path}", 2)
        except OSError as exc:
            print(f"DESCRIBE {path} -> ошибка: {exc}")
            continue
        print(f"DESCRIBE {path} -> {reply.splitlines()[0] if reply else '(пусто)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
