# decode_chunked fails on chunk extensions

**Version:** 1.4.0

Chunk extensions are valid HTTP/1.1 (RFC 9112 section 7.1.1), but `decode_chunked()` passes the whole
size line to `int()`. The culprit is `_read_chunk_size` in `src/tinyhttp/chunked.py:7`, which
doesn't strip the `;name=value` part.

Repro:

```sh
printf 'POST /up HTTP/1.1\r\nHost: example.com\r\nTransfer-Encoding: chunked\r\n\r\n5;name=value\r\nhello\r\n0\r\n\r\n' > req.txt
tinyhttp req.txt --chunked --max-headers 50
```

```
Traceback (most recent call last):
  File "/home/sam/.venv/lib/python3.12/site-packages/tinyhttp/cli.py", line 23, in main
    body = decode_chunked(io.BytesIO(body))
  File "/home/sam/.venv/lib/python3.12/site-packages/tinyhttp/chunked.py", line 17, in decode_chunked
    size = _read_chunk_size(line)
  File "/home/sam/.venv/lib/python3.12/site-packages/tinyhttp/chunked.py", line 7, in _read_chunk_size
    return int(size, 16)
ValueError: invalid literal for int() with base 16: b'5;name=value'
```

Suggested fix: `size = line.split(b";", 1)[0].strip()`.
