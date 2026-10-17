#!/usr/bin/env python3
import os, sys, re
from http.server import HTTPServer, SimpleHTTPRequestHandler

class RangeHandler(SimpleHTTPRequestHandler):
    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(404, "File not found")
            return None
        fs = os.fstat(f.fileno())
        size = fs.st_size
        range_header = self.headers.get('Range')
        if not range_header:
            self.send_response(200)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Length", str(size))
            self.send_header("Accept-Ranges", "bytes")
            self.end_headers()
            return f
        m = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if not m:
            self.send_error(416, "Requested Range Not Satisfiable")
            f.close()
            return None
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
        if start >= size:
            self.send_error(416, "Requested Range Not Satisfiable")
            f.close()
            return None
        length = end - start + 1
        f.seek(start)
        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        buf_size = 1024 * 1024
        range_header = self.headers.get('Range')
        if not range_header:
            super().copyfile(source, outputfile)
            return
        m = re.match(r'bytes=(\d+)-(\d*)', range_header)
        fs = os.fstat(source.fileno())
        size = fs.st_size
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
        remaining = end - start + 1
        while remaining > 0:
            chunk = source.read(min(remaining, buf_size))
            if not chunk:
                break
            try:
                outputfile.write(chunk)
            except (ConnectionResetError, BrokenPipeError):
                break
            remaining -= len(chunk)

print("Starting HTTP server with full Range / Multi-thread support on port 8000...")
server = HTTPServer(('0.0.0.0', 8000), RangeHandler)
server.serve_forever()
