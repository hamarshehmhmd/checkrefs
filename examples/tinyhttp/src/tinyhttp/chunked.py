"""Chunked transfer-encoding decoder."""
import io


def _read_chunk_size(line: bytes) -> int:
    size = line.strip()
    return int(size, 16)


def decode_chunked(stream: io.BufferedIOBase) -> bytes:
    """Decode a chunked body from a binary stream and return the payload."""
    out = bytearray()
    while True:
        line = stream.readline()
        if not line:
            raise ValueError("unexpected end of chunked body")
        size = _read_chunk_size(line)
        if size == 0:
            break
        out += stream.read(size)
        stream.read(2)  # CRLF after each chunk
    return bytes(out)
