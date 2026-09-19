"""Descifrado CryptoJS y recuperacion del passphrase a partir del bundle."""

from pathlib import Path

import pytest

from fragrantica.parsers.crypto import (
    DecryptError,
    bundle_path_from_html,
    decrypt_cryptojs,
    encrypt_cryptojs,
    encrypted_blobs_from_html,
    passphrase_from_host,
    recover_passphrase,
    unwrap_ajax_body,
)

FX = Path(__file__).parent / "fixtures"


def test_cryptojs_roundtrip():
    blob = encrypt_cryptojs('{"ok":true,"n":3}', "build-constant-pass", salt=b"12345678")
    assert set(blob) == {"ct", "iv", "s"}
    assert decrypt_cryptojs(blob, "build-constant-pass") == '{"ok":true,"n":3}'


def test_wrong_passphrase_raises():
    blob = encrypt_cryptojs("false", "right-key", salt=b"abcdefgh")
    with pytest.raises(DecryptError):
        decrypt_cryptojs(blob, "wrong-key")


def test_toabby_is_not_the_aes_passphrase():
    """Hallazgo: toAbby del HTML no abre los blobs de la misma pagina."""
    import base64
    import re

    html = (FX / "profile_quilter.html").read_text()
    blobs = encrypted_blobs_from_html(html)
    assert "favorite_shelf" in blobs
    raw = base64.b64decode(re.search(r'let toAbby = "([^"]+)"', html).group(1)).decode()
    hexpart = raw.split("validUntil=")[0]
    with pytest.raises(DecryptError):
        decrypt_cryptojs(blobs["favorite_shelf"], hexpart)
    with pytest.raises(DecryptError):
        decrypt_cryptojs(blobs["favorite_shelf"], raw)


def test_host_passphrase_opens_quilter_member_home():
    """Hallazgo de Bruno: _pd(www.fragrantica.com) abre los blobs reales."""
    import orjson

    html = (FX / "profile_quilter.html").read_text()
    blobs = encrypted_blobs_from_html(html)
    pw = passphrase_from_host("www.fragrantica.com")
    data = orjson.loads(decrypt_cryptojs(blobs["memberHomeData"], pw))
    assert data["user_id"] == 3158387
    with pytest.raises(DecryptError):
        decrypt_cryptojs(blobs["memberHomeData"], passphrase_from_host("fragrantica.com"))


def test_recover_passphrase_from_literals_near_pd():
    blob = encrypt_cryptojs("false", "the-real-passphrase")
    js = (
        'var x="decoy-string-here";'
        'window._pd=function(e){return CryptoJS.AES.decrypt(e,"the-real-passphrase")};'
        'var y="another-decoy-value";'
    )
    assert recover_passphrase(js, blob) == "the-real-passphrase"


def test_unwrap_ajax_encrypted_and_plain():
    payload = {"wardrobe": [{"parfem_id": 1, "relation": "have"}]}
    import orjson

    plain = orjson.dumps(payload).decode()
    assert unwrap_ajax_body(plain, "unused") == payload

    blob = encrypt_cryptojs(plain, "k")
    wrapped = orjson.dumps(blob).decode()
    assert unwrap_ajax_body(wrapped, "k") == payload


def test_fixture_has_named_blobs_and_bundle_src():
    html = (FX / "profile_quilter.html").read_text()
    blobs = encrypted_blobs_from_html(html)
    assert {"favorite_shelf", "memberHomeData", "memberFeedInitial"} <= blobs.keys()
    assert bundle_path_from_html(html).startswith("/new-js/mfga2-app.js")
