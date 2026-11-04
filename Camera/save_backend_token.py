"""Один раз сохраняет токен API бэкенда ESP в Диспетчер учётных данных Windows.

    .venv\\Scripts\\python.exe save_backend_token.py

Токен - значение API_TOKEN того бэкенда, к которому подключается узел (для TEST - из
.env.test). Ввод скрыт, токен нигде не печатается. Удалить: --delete.
"""

import argparse
import getpass
import sys

import keyring

from site_node import BACKEND_KEYRING_SERVICE, BACKEND_KEYRING_USER


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--delete", action="store_true")
    args = parser.parse_args()
    if args.delete:
        try:
            keyring.delete_password(BACKEND_KEYRING_SERVICE, BACKEND_KEYRING_USER)
            print("Токен удалён.")
        except keyring.errors.PasswordDeleteError:
            print("Сохранённого токена нет.")
        return 0
    token = getpass.getpass("API_TOKEN бэкенда (ввод скрыт): ").strip()
    if not token:
        print("Пустой токен, ничего не сохранено.")
        return 2
    keyring.set_password(BACKEND_KEYRING_SERVICE, BACKEND_KEYRING_USER, token)
    print("Сохранено в Диспетчер учётных данных Windows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
