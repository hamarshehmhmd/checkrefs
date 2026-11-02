"""Header block parsing."""

MAX_HEADER_BYTES = 8192
MAX_HEADERS = 100


class HeaderTooLarge(ValueError):
    """Raised when a header block exceeds the configured limits."""


def parse_headers(data: bytes, max_bytes: int = MAX_HEADER_BYTES, max_headers: int = MAX_HEADERS) -> dict:
    """Parse a raw header block (without the request line) into a dict of lists."""
    if len(data) > max_bytes:
        raise HeaderTooLarge("header block is %d bytes, limit is %d" % (len(data), max_bytes))
    headers = {}
    count = 0
    for raw in data.split(b"\r\n"):
        if not raw:
            continue
        count += 1
        if count > max_headers:
            raise HeaderTooLarge("more than %d headers" % max_headers)
        name, sep, value = raw.partition(b":")
        if not sep:
            raise ValueError("malformed header line: %r" % raw[:40])
        key = name.strip().decode("latin-1").lower()
        headers.setdefault(key, []).append(value.strip().decode("latin-1"))
    return headers
