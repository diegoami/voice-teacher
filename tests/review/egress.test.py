"""No network or provider credentials needed."""
import importlib.util
from pathlib import Path
import unittest
import socket
import tempfile
import threading
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("egress", Path(__file__).parents[2] / "tools/review/egress.py")
egress = importlib.util.module_from_spec(spec)
spec.loader.exec_module(egress)


class EgressTest(unittest.TestCase):
    def request(self, message):
        with tempfile.TemporaryDirectory() as directory:
            address = str(Path(directory) / 'proxy.sock')
            with egress.Server(address, egress.Tunnel) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                        client.settimeout(2)
                        client.connect(address)
                        client.sendall(message)
                        client.shutdown(socket.SHUT_WR)
                        return client.recv(4096)
                finally:
                    server.shutdown()
                    thread.join(timeout=2)

    def test_provider_and_catalogue_only(self):
        for host in ["api.minimax.io", "models.dev"]:
            self.assertEqual(egress.authority(f"CONNECT {host}:443 HTTP/1.1\r\n\r\n".encode()), host)

    def test_reject_publishing_local_services_and_malformed_targets(self):
        for line in ["CONNECT api.github.com:443 HTTP/1.1", "CONNECT localhost:49374 HTTP/1.1",
                     "CONNECT 127.0.0.1:443 HTTP/1.1", "CONNECT api.minimax.io:80 HTTP/1.1",
                     "CONNECT api.minimax.io.evil:443 HTTP/1.1", "GET https://api.minimax.io/ HTTP/1.1",
                     "CONNECT user@api.minimax.io:443 HTTP/1.1", "bad", "CONNECT api.minimax.io:443 HTTP/9"]:
            with self.subTest(line=line), self.assertRaises(ValueError):
                egress.authority((line + "\r\n\r\n").encode())

    def test_actual_broker_rejects_github_and_partial_requests(self):
        for message in [b'CONNECT api.github.com:443 HTTP/1.1\r\n\r\n', b'CONNE']:
            self.assertIn(b'403 Forbidden', self.request(message))

    def test_private_dns_result_is_denied_before_connect(self):
        address = [(socket.AF_INET, socket.SOCK_STREAM, 0, '', ('127.0.0.1', 443))]
        with patch.object(egress.socket, 'getaddrinfo', return_value=address):
            self.assertIn(b'403 Forbidden', self.request(b'CONNECT api.minimax.io:443 HTTP/1.1\r\n\r\n'))


if __name__ == "__main__":
    unittest.main()
