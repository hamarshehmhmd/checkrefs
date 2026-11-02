"""tinyhttp: a tiny HTTP/1.1 message parser (demo project for checkrefs)."""
from .chunked import decode_chunked
from .headers import HeaderTooLarge, parse_headers

__version__ = "1.4.0"
__all__ = ["decode_chunked", "parse_headers", "HeaderTooLarge"]
