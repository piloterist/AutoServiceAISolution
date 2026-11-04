"""Один раз сохраняет пароль камеры в Диспетчер учётных данных Windows (скрытый ввод).

    .venv\\Scripts\\python.exe save_password.py

После этого остальные скрипты берут пароль оттуда сами. Удалить:
    .venv\\Scripts\\python.exe save_password.py --delete
"""

import argparse
import getpass
import os
import sys

import keyring
from dotenv import load_dotenv

from stream_check import KEYRING_SERVICE, ROOT


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()
    user = os.environ.get("CAMERA_USER", "admin")

    if args.delete:
        try:
            keyring.delete_password(KEYRING_SERVICE, user)
            print("Пароль удалён из хранилища.")
        except keyring.errors.PasswordDeleteError:
            print("Сохранённого пароля нет.")
        return 0

    password = getpass.getpass(f"Пароль камеры для {user} (ввод скрыт): ")
    if not password:
        print("Пустой пароль, ничего не сохранено.")
        return 2
    keyring.set_password(KEYRING_SERVICE, user, password)
    print(f"Сохранено в Диспетчер учётных данных Windows (служба {KEYRING_SERVICE}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
