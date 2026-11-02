"""tinyhttp command line: parse a raw HTTP message from a file."""
import argparse
import io
import json
import sys

from .chunked import decode_chunked
from .headers import MAX_HEADERS, parse_headers


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tinyhttp")
    ap.add_argument("file")
    ap.add_argument("--max-headers", type=int, default=MAX_HEADERS)
    ap.add_argument("--chunked", action="store_true")
    a = ap.parse_args(argv)
    with open(a.file, "rb") as fh:
        raw = fh.read()
    head, _, body = raw.partition(b"\r\n\r\n")
    _, _, header_block = head.partition(b"\r\n")
    headers = parse_headers(header_block, max_headers=a.max_headers)
    if a.chunked:
        body = decode_chunked(io.BytesIO(body))
    json.dump({"headers": headers, "body_bytes": len(body)}, sys.stdout)
    return 0
