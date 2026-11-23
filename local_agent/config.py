from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
from ctypes import wintypes
from pathlib import Path

from platformdirs import user_config_dir

APP_NAME = "eSim ToolMate"
CONFIG_DIR = Path(user_config_dir(APP_NAME, "FOSSEE")) / "local-agent"
CONFIG_PATH = CONFIG_DIR / "agent.json"


def _protect_windows(value: str) -> str:
    if os.name != "nt":
        return value
    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    raw = value.encode("utf-8")
    source_buffer = ctypes.create_string_buffer(raw)
    source = DataBlob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    destination = DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DataBlob), wintypes.LPCWSTR, ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(ctypes.byref(source), "eSim ToolMate Local Agent", None, None, None, 0, ctypes.byref(destination)):
        raise OSError("Windows could not protect the Local Agent token with DPAPI")
    try:
        protected = ctypes.string_at(destination.pbData, destination.cbData)
        return "dpapi:" + base64.b64encode(protected).decode("ascii")
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
        ctypes.windll.kernel32.LocalFree(destination.pbData)


def _unprotect_windows(value: str) -> str:
    if os.name != "nt" or not value.startswith("dpapi:"):
        return value
    class DataBlob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    raw = base64.b64decode(value[6:], validate=True)
    source_buffer = ctypes.create_string_buffer(raw)
    source = DataBlob(len(raw), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte)))
    destination = DataBlob()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DataBlob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DataBlob), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DataBlob)]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(destination)):
        raise OSError("Windows could not unlock the Local Agent token with DPAPI")
    try:
        return ctypes.string_at(destination.pbData, destination.cbData).decode("utf-8")
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree.restype = ctypes.c_void_p
        ctypes.windll.kernel32.LocalFree(destination.pbData)


def load() -> dict:
    if not CONFIG_PATH.exists():
        return {"device_id": None, "access_token": None, "backend_url": None, "minimum_versions": {}}
    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    data["access_token"] = _unprotect_windows(data.get("access_token") or "") or None
    return data


def save(data: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass
    payload = dict(data)
    if payload.get("access_token"):
        payload["access_token"] = _protect_windows(payload["access_token"])
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(CONFIG_PATH)
    try:
        CONFIG_PATH.chmod(0o600)
    except OSError:
        pass


def ensure_secure_store() -> str:
    return "DPAPI-encrypted config on Windows" if platform.system() == "Windows" else "owner-only config permissions (0600)"
