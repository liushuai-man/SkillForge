"""Local service reuse and runtime validation for the graphical launcher."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from skillforge_vm.cli import gui
from skillforge_vm.cli.client import CliError


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com:8756",
        "http://example.com:8756",
        "http://127.0.0.1:8756/not-root",
        "http://user:pass@127.0.0.1:8756",
    ],
)
def test_launcher_rejects_nonlocal_or_nonroot_runtime_urls(url):
    with pytest.raises(CliError):
        gui._local_url(url)


def test_gui_reuses_a_live_service_without_starting_another_writer(tmp_path, monkeypatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            is_health = self.path == "/api/health"
            self.send_header("Content-Type", "application/json" if is_health else "text/html")
            self.end_headers()
            self.wfile.write(
                b'{"ok":true,"data":{"status":"ok"}}' if is_health else b"<html>GUI</html>"
            )

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    (tmp_path / "runtime.json").write_text(json.dumps({"base_url": url, "pid": 1}))
    monkeypatch.setattr(gui, "_prepare_assets", lambda: None)

    def fail_spawn(*_args, **_kwargs):
        pytest.fail("Reusing a live service must not create a second process")

    monkeypatch.setattr(gui.subprocess, "Popen", fail_spawn)
    try:
        assert gui.launch(tmp_path, open_browser=False) == url
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
