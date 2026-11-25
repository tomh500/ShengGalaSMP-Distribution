#!/usr/bin/python3
import json
import os
import socketserver
import sys
import threading
from pathlib import Path

from topologyctl import read_bytes, read_varint, varint


class Status(socketserver.StreamRequestHandler):
    def handle(self):
        read_bytes(self.rfile, read_varint(self.rfile))
        if read_bytes(self.rfile, 2) != b"\x01\x00":
            return
        data = json.dumps({"version": {"name": "fixture"}, "players": {"online": 0}}).encode()
        response = b"\0" + varint(len(data)) + data
        self.wfile.write(varint(len(response)) + response)


if __name__ == "__main__":
    port = int(sys.argv[-1])
    with socketserver.ThreadingTCPServer(("127.0.0.1", port), Status) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        Path("pid").write_text(str(os.getpid()))
        for line in sys.stdin:
            if line.strip() in ("stop", "end"):
                Path("saved").write_text(line.strip())
                break
