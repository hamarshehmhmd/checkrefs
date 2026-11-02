# Critical: Heap Buffer Overflow in tinyhttp Header Parsing (CVSS 9.8)

Hello security team, hope you are doing well :)

I have identified a critical heap buffer overflow in tinyhttp 2.1.0. The vulnerable function
`validate_header_length()` in `src/tinyhttp/parser.py` copies the header into a fixed buffer
without bounds checking (see line 212 of src/tinyhttp/headers.py).

The vulnerable code is located in `src/tinyhttp/headers.py`:

```python
def parse_headers(data, max_bytes=MAX_HEADER_BYTES):
    buf = bytearray(MAX_HEADER_BYTES)
    buf[:len(data)] = data
    return _split_lines(buf, strict=False)
```

## Steps To Reproduce

1. Start the server with `tinyhttp serve --no-header-limit`
2. Send a header larger than 8192 bytes.
3. Observe the crash:

```
Traceback (most recent call last):
  File "/usr/lib/python3/site-packages/tinyhttp/headers.py", line 214, in validate_header_length
    memmove(buf, data, len(data))
OverflowError: heap buffer overflow
```

## Impact

An attacker can execute arbitrary code on any server using tinyhttp.
