import io

from tinyhttp import decode_chunked, parse_headers


def test_headers():
    assert parse_headers(b"Host: a\r\nX-A: 1\r\nX-A: 2") == {"host": ["a"], "x-a": ["1", "2"]}


def test_chunked():
    assert decode_chunked(io.BytesIO(b"3\r\nabc\r\n0\r\n\r\n")) == b"abc"
