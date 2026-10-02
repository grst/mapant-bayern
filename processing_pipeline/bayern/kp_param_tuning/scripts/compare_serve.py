#!/usr/bin/env python3
"""
Serve the comparison app with HTTP range requests (PMTiles reads the archives in ranges, which
`python -m http.server` does not support). Standard library only, so the folder can be copied
anywhere:

    python3 serve.py [port]      # then open http://localhost:8765/
"""

from __future__ import annotations

import functools
import http.server
import os
import sys
from pathlib import Path


class RangeHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def end_headers(self):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_head(self):
        rng = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not rng or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        start, _, end = rng.removeprefix("bytes=").partition("-")
        if not start:  # suffix range: the last n bytes
            start, end = max(size - int(end), 0), size - 1
        start = int(start)
        end = min(int(end) if end else size - 1, size - 1)
        f = open(path, "rb")
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        self._remaining = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        n = getattr(self, "_remaining", None)
        if n is None:
            return super().copyfile(source, outputfile)
        while n > 0:
            buf = source.read(min(n, 1 << 20))
            if not buf:
                break
            outputfile.write(buf)
            n -= len(buf)
        self._remaining = None


def serve(directory: Path, port: int = 8765) -> None:
    handler = functools.partial(RangeHandler, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"serving {directory} on http://localhost:{port}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    serve(Path(__file__).resolve().parent, int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
