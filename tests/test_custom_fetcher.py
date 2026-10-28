import json
import http.server
import socketserver
import threading
import re
import zlib
from unittest import TestCase
from src.app import create_app
from src.custom_fetcher import is_allowed_url

ALLOWED_PORT = 8002
FORBIDDEN_PORT = 8003
CONTENT = b"ASSET-CONTENT"


class AssetHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(CONTENT)

    def log_message(self, *args):
        pass


def embedded_streams(pdf):
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf, re.S):
        try:
            yield zlib.decompress(match.group(1))
        except zlib.error:
            yield match.group(1)


class TestIsAllowedUrl(TestCase):
    BASE = "https://www.mes-demarches.gov.pf"

    def test_accepte_le_domaine_de_base(self):
        self.assertTrue(
            is_allowed_url(f"{self.BASE}/assets/attestation.css", self.BASE)
        )

    def test_accepte_les_data_uri(self):
        self.assertTrue(is_allowed_url("data:image/png;base64,iVBORw0KGgo=", self.BASE))

    def test_refuse_file(self):
        self.assertFalse(is_allowed_url("file:///tmp/x", self.BASE))

    def test_refuse_une_ip(self):
        self.assertFalse(is_allowed_url("http://10.0.0.1/", self.BASE))

    def test_refuse_une_autre_ip(self):
        self.assertFalse(is_allowed_url("http://192.0.2.10/x", self.BASE))

    def test_refuse_un_autre_port_du_meme_hote(self):
        self.assertFalse(
            is_allowed_url("https://www.mes-demarches.gov.pf:8443/", self.BASE)
        )

    def test_refuse_un_hote_qui_prefixe_le_domaine(self):
        self.assertFalse(
            is_allowed_url(
                "https://www.mes-demarches.gov.pf.attacker.example/", self.BASE
            )
        )

    def test_refuse_sans_base_url(self):
        self.assertFalse(is_allowed_url(f"{self.BASE}/x", None))


class TestOriginRestriction(TestCase):
    @classmethod
    def setUpClass(cls):
        socketserver.TCPServer.allow_reuse_address = True
        cls.servers = []
        for port in (ALLOWED_PORT, FORBIDDEN_PORT):
            httpd = socketserver.TCPServer(("127.0.0.1", port), AssetHandler)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            cls.servers.append((httpd, thread))

        cls.app = create_app(
            {"BASE_URL": f"http://127.0.0.1:{ALLOWED_PORT}/"}
        ).test_client()

    @classmethod
    def tearDownClass(cls):
        for httpd, thread in cls.servers:
            httpd.shutdown()
            httpd.server_close()
            thread.join()

    def post_pdf(self, html):
        return self.app.post(
            "/pdf", data=json.dumps({"html": html}), content_type="application/json"
        )

    def assert_content_absent(self, response):
        self.assertEqual(response.status_code, 200)
        self.assertFalse(any(CONTENT in s for s in embedded_streams(response.data)))

    def test_piece_jointe_autre_origine_non_embarquee(self):
        html = f'<p><a rel="attachment" href="http://127.0.0.1:{FORBIDDEN_PORT}/x">pj</a></p>'
        self.assert_content_absent(self.post_pdf(html))

    def test_piece_jointe_hors_http_non_embarquee(self):
        html = '<p><a rel="attachment" href="file:///tmp/x">pj</a></p>'
        response = self.post_pdf(html)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"/EmbeddedFile", response.data)

    def test_image_autre_origine_ignoree_sans_erreur(self):
        html = f'<p><img src="http://127.0.0.1:{FORBIDDEN_PORT}/x.png">texte</p>'
        self.assertEqual(self.post_pdf(html).status_code, 200)

    def test_piece_jointe_du_domaine_autorise_toujours_embarquee(self):
        html = f'<p><a rel="attachment" href="http://127.0.0.1:{ALLOWED_PORT}/ok">pj</a></p>'
        response = self.post_pdf(html)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(CONTENT in s for s in embedded_streams(response.data)))
