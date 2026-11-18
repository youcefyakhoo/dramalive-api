"""Cifrado de Drama Live: AES-128-CBC con clave fija embebida en la app.

Formato en el cable:  base64(cifrado) + ":" + base64(iv)
Relleno PKCS#7. La clave aparece en main.dart.js dentro de c0() y dJ().
"""
import base64
import os

from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

KEY = b"43fc9b1a3f854049"


def encrypt(plain: str) -> str:
    iv = os.urandom(16)
    c = AES.new(KEY, AES.MODE_CBC, iv).encrypt(pad(plain.encode(), 16))
    return base64.b64encode(c).decode() + ":" + base64.b64encode(iv).decode()


def decrypt(payload: str) -> str:
    c, iv = payload.strip().split(":")
    raw = AES.new(KEY, AES.MODE_CBC, base64.b64decode(iv)).decrypt(base64.b64decode(c))
    try:
        return unpad(raw, 16).decode()
    except ValueError:
        return raw.decode("utf-8", "replace")
