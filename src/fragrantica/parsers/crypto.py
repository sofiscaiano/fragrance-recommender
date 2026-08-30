"""Descifrado CryptoJS (OpenSSL / EvpKDF-MD5) de los blobs {ct, iv, s}.

El sitio no sirve wardrobe ni votos en claro: el HTML embebe esos objetos
cifrados y el endpoint `/ajax.php?user_shelves` responde igual. El cliente
los abre con AES-256-CBC, clave e IV derivados del passphrase via EvpKDF-MD5
(1 iteracion, salt de 8 bytes). El `iv` del JSON es redundante: se rederiva
del passphrase + salt, igual que CryptoJS.AES.decrypt(json, passphrase).

El passphrase no esta en el HTML (se probo `toAbby` y el resto de secretos
inline contra los blobs del fixture de @quilter: PKCS7 no cierra). Vive en
el bundle `/new-js/mfga2-app.js`. Se recupera probando los string literals del
bundle contra un blob de la misma pagina, sin ejecutar JS.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from typing import Any

import orjson
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

_CT_OBJ = re.compile(
    r'\{\s*"ct"\s*:\s*"(?P<ct>[^"]+)"\s*,\s*"iv"\s*:\s*"(?P<iv>[^"]+)"\s*,\s*"s"\s*:\s*"(?P<s>[^"]+)"\s*\}'
)
_NAMED_BLOB = re.compile(
    r"(?:let|var|window\.)\s*(?P<name>[A-Za-z_][A-Za-z0-9_.]*)\s*=\s*"
    r'(\{\s*"ct"\s*:\s*"[^"]+"\s*,\s*"iv"\s*:\s*"[^"]+"\s*,\s*"s"\s*:\s*"[^"]+"\s*\})'
)
_STRING_LIT = re.compile(r'["\']([^"\']{8,128})["\']')
_DECRYPT_ANCHOR = re.compile(r"window\._pd|_pd\s*=|AES\.decrypt|\.decrypt\(")
_BUNDLE_SRC = re.compile(r'src="(/new-js/mfga2-app\.js[^"]*)"')


class DecryptError(ValueError):
    """El blob no se pudo abrir con ese passphrase."""


def evp_bytes_to_key(
    password: bytes,
    salt: bytes,
    key_len: int = 32,
    iv_len: int = 16,
) -> tuple[bytes, bytes]:
    """OpenSSL EVP_BytesToKey / CryptoJS OpenSSLKdf (MD5, 1 iteracion)."""
    derived = b""
    block = b""
    while len(derived) < key_len + iv_len:
        block = hashlib.md5(block + password + salt).digest()
        derived += block
    return derived[:key_len], derived[key_len : key_len + iv_len]


def decrypt_cryptojs(blob: dict[str, str], passphrase: str) -> str:
    """Descifra un objeto {ct, iv, s} y devuelve UTF-8.

    `iv` del JSON se ignora a proposito: CryptoJS en modo passphrase lo
    rederiva. Si se usara el iv almacenado con una clave cruda, los blobs
    del sitio no abren.
    """
    try:
        ct = base64.b64decode(blob["ct"])
        salt = bytes.fromhex(blob["s"])
    except (KeyError, ValueError) as exc:
        raise DecryptError("blob CryptoJS malformado") from exc
    if len(salt) != 8:
        raise DecryptError(f"salt inesperado ({len(salt)} bytes, se esperan 8)")

    key, iv = evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    try:
        pt = unpad(AES.new(key, AES.MODE_CBC, iv).decrypt(ct), 16)
    except ValueError as exc:
        raise DecryptError("padding PKCS7 invalido (passphrase incorrecto)") from exc
    try:
        return pt.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DecryptError("plaintext no es UTF-8") from exc


def encrypt_cryptojs(plaintext: str, passphrase: str, *, salt: bytes | None = None) -> dict[str, str]:
    """Solo para tests: produce el mismo formato que el sitio."""
    salt = salt if salt is not None else os.urandom(8)
    if len(salt) != 8:
        raise ValueError("salt debe ser de 8 bytes")
    key, iv = evp_bytes_to_key(passphrase.encode("utf-8"), salt)
    ct = AES.new(key, AES.MODE_CBC, iv).encrypt(pad(plaintext.encode("utf-8"), 16))
    return {"ct": base64.b64encode(ct).decode(), "iv": iv.hex(), "s": salt.hex()}


def parse_blob(raw: str) -> dict[str, str]:
    data = json.loads(raw)
    if not isinstance(data, dict) or not {"ct", "iv", "s"} <= data.keys():
        raise DecryptError("no es un blob CryptoJS")
    return {"ct": data["ct"], "iv": data["iv"], "s": data["s"]}


def encrypted_blobs_from_html(html: str) -> dict[str, dict[str, str]]:
    """Nombres (favorite_shelf, memberHomeData, ...) -> blob, desde el HTML."""
    out: dict[str, dict[str, str]] = {}
    for m in _NAMED_BLOB.finditer(html):
        name = m.group("name").split(".")[-1]
        try:
            out[name] = parse_blob(m.group(2))
        except DecryptError:
            continue
    return out


def bundle_path_from_html(html: str) -> str:
    m = _BUNDLE_SRC.search(html)
    return m.group(1) if m else "/new-js/mfga2-app.js"


def unwrap_ajax_body(body: str, passphrase: str) -> Any:
    """JSON en claro, o blob CryptoJS, o el objeto embebido en HTML de error."""
    text = body.strip()
    try:
        data = orjson.loads(text)
    except orjson.JSONDecodeError:
        m = _CT_OBJ.search(body)
        if not m:
            raise DecryptError("la respuesta ajax no es JSON ni un blob CryptoJS")
        data = parse_blob(m.group(0))

    if isinstance(data, dict) and {"ct", "iv", "s"} <= data.keys():
        pt = decrypt_cryptojs(data, passphrase)
        try:
            return orjson.loads(pt)
        except orjson.JSONDecodeError as exc:
            raise DecryptError("plaintext del ajax no es JSON") from exc
    return data


def recover_passphrase(js: str, sample: dict[str, str]) -> str:
    """Prueba string literals del bundle contra un blob conocido de la pagina.

    No hace falta entender `window._pd`: si el passphrase es una constante
    del build, aparece como literal y el canario (favorite_shelf, un bloque)
    lo confirma via PKCS7 + JSON valido.
    """
    seen: set[str] = set()
    ordered: list[str] = []

    def add(values: list[str]) -> None:
        for v in values:
            if v not in seen:
                seen.add(v)
                ordered.append(v)

    for m in _DECRYPT_ANCHOR.finditer(js):
        start = max(0, m.start() - 500)
        end = min(len(js), m.end() + 500)
        add(_STRING_LIT.findall(js[start:end]))
    add([s for s in _STRING_LIT.findall(js) if re.fullmatch(r"[0-9a-fA-F]{16,64}", s)])
    add(_STRING_LIT.findall(js))

    for pw in ordered:
        try:
            pt = decrypt_cryptojs(sample, pw)
            orjson.loads(pt)
        except (DecryptError, orjson.JSONDecodeError):
            continue
        return pw
    raise DecryptError("ningun literal del bundle abre el blob canario")
