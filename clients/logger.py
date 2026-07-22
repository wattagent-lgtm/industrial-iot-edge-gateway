"""Lightweight console logger; no flash writes are performed."""


def info(message):
    print("[INFO] " + str(message))


def warning(message):
    print("[WARNING] " + str(message))


def error(message):
    print("[ERROR] " + str(message))

