"""Supervised Unix-socket CONNECT broker; no HTTP requests or arbitrary destinations.

Run outside the review namespace. The only exposed host socket is this broker.
No provider or GitHub credentials are read by this process.
"""
import ipaddress
import select
import socket
import socketserver
import sys
import time
import threading

ALLOWED = {"api.minimax.io:443", "models.dev:443"}


def authority(header):
    line = header.split(b"\r\n", 1)[0].decode("ascii", errors="strict")
    method, target, version = line.split(" ")
    if method != "CONNECT" or target not in ALLOWED or version not in {"HTTP/1.0", "HTTP/1.1"}:
        raise ValueError("Destination denied")
    return target.rsplit(":", 1)[0]


class Tunnel(socketserver.BaseRequestHandler):
    def handle(self):
        client = self.request
        client.settimeout(10)
        try:
            header = b""
            while b"\r\n\r\n" not in header:
                part = client.recv(1)
                if not part:
                    raise ValueError("Incomplete request")
                header += part
                if len(header) > 8192:
                    raise ValueError("Invalid request")
            host = authority(header)
            addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
                raise ValueError("Nonpublic address denied")
            af, kind, proto, _, addr = addresses[0]
            with socket.socket(af, kind, proto) as upstream:
                upstream.settimeout(15)
                upstream.connect(addr)
                client.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                deadline = time.monotonic() + 600
                while time.monotonic() < deadline:
                    ready, _, _ = select.select([client, upstream], [], [], 5)
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (upstream if source is client else client).sendall(data)
        except (OSError, ValueError, UnicodeError):
            try:
                client.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            except OSError:
                pass


class Server(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    request_queue_size = 8
    slots = threading.BoundedSemaphore(8)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


if __name__ == "__main__":
    # The operator creates a fresh private parent directory. Never unlink a live socket.
    import os
    os.umask(0o077)
    with Server(sys.argv[1], Tunnel) as server:
        print("egress broker ready", flush=True)
        server.serve_forever()
