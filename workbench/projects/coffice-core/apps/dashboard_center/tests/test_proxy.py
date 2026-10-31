from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

from apps.dashboard_center.proxy import DataEaseEmbedProxy


class _UpstreamHandler(BaseHTTPRequestHandler):
    seen_body = None
    seen_cookie = None

    def log_message(self, fmt, *args):
        return

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        type(self).seen_body = json.loads(body)
        type(self).seen_cookie = self.headers.get("Cookie", "")
        payload = json.dumps({"ok": True}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
        self.send_header("Set-Cookie", "de_session=abc; Domain=127.0.0.1; Secure; Path=/")
        self.end_headers()
        self.wfile.write(payload)


class DataEaseEmbedProxyTests(unittest.TestCase):
    def setUp(self):
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), _UpstreamHandler)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        upstream_port = self.upstream.server_address[1]
        self.proxy = DataEaseEmbedProxy(f"http://127.0.0.1:{upstream_port}", port=0)
        self.proxy.start()

    def tearDown(self):
        self.proxy.stop()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.upstream_thread.join(timeout=2)

    def test_proxy_rewrites_iframe_flag_headers_and_app_cookies(self):
        request = Request(
            f"http://127.0.0.1:{self.proxy.port}/de2api/share/proxyInfo",
            data=json.dumps({"inIframe": True, "resourceId": "demo"}).encode(),
            headers={
                "Content-Type": "application/json",
                "Cookie": "mocc_session=secret; mocc_csrf=secret; de_session=allowed",
            },
            method="POST",
        )
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)
            self.assertIsNone(response.headers.get("X-Frame-Options"))
            self.assertIsNone(response.headers.get("Content-Security-Policy"))
            cookie = response.headers.get("Set-Cookie")
            self.assertNotIn("Domain=", cookie)
            self.assertNotIn("Secure", cookie)
        self.assertIs(_UpstreamHandler.seen_body["inIframe"], False)
        self.assertNotIn("mocc_session", _UpstreamHandler.seen_cookie)
        self.assertNotIn("mocc_csrf", _UpstreamHandler.seen_cookie)
        self.assertIn("de_session=allowed", _UpstreamHandler.seen_cookie)

    def test_embed_location_keeps_public_share_fragment(self):
        location = self.proxy.embed_location(
            f"{self.proxy.target_origin}/#/de-link/I9O1mwdA"
        ).as_dict()
        self.assertEqual(location["proxy_port"], self.proxy.port)
        self.assertEqual(location["proxy_path"], "/#/de-link/I9O1mwdA")

    def test_embed_location_accepts_configured_public_origin(self):
        proxy = DataEaseEmbedProxy(
            "http://host.docker.internal:8100",
            public_origins="http://192.168.77.111:8100",
            port=0,
        )
        location = proxy.embed_location(
            "http://192.168.77.111:8100/#/de-link/I9O1mwdA"
        )
        self.assertEqual(location.proxy_path, "/#/de-link/I9O1mwdA")


if __name__ == "__main__":
    unittest.main()
