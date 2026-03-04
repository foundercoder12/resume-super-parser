from app.core.hashing import sha256_hex


def test_sha256_produces_64_char_hex():
    h = sha256_hex(b"hello world")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_same_input_same_hash():
    assert sha256_hex(b"data") == sha256_hex(b"data")


def test_different_input_different_hash():
    assert sha256_hex(b"a") != sha256_hex(b"b")
