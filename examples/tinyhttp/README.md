# tinyhttp (example)

A tiny, deliberately imperfect HTTP/1.1 parser used to demo checkrefs. `decode_chunked` has a real bug:
it doesn't handle chunk extensions (`5;name=value`), which is what `../reports/real-bug.md` reports.
