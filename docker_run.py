"""Local Docker launcher. Keep the upstream loopback checks unchanged."""

import importlib
import logging
import os
import signal
import socket
import socketserver
import threading

from werkzeug.exceptions import NotFound
from werkzeug.middleware.http_proxy import ProxyMiddleware
from werkzeug.serving import make_server


def main():
    variant = os.environ.get("TICKETORACLE_VARIANT", "app")
    if variant not in {"app", "app_hardened"}:
        raise SystemExit("TICKETORACLE_VARIANT must be app or app_hardened")
    request_mode = os.environ.get("TICKETORACLE_REQUEST_MODE", "get")
    if request_mode not in {"get", "structured"}:
        raise SystemExit("TICKETORACLE_REQUEST_MODE must be get or structured")

    # OpenAI's client requires a nonempty key even when only browsing pages.
    # Never send the placeholder to OpenRouter: the hook below blocks chat.
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    os.environ["OPENROUTER_API_KEY"] = key or "docker-ui-only"
    module = importlib.import_module(variant)
    application = module.app

    if not key:
        from flask import jsonify, request

        @application.before_request
        def require_chat_key():
            if request.path == "/chat" and request.method == "POST":
                return jsonify(error=(
                    "AI chat is disabled. Set OPENROUTER_API_KEY in .env "
                    "and run docker compose up -d again."
                )), 503

        logging.warning("No OpenRouter key configured; AI chat is disabled.")

    # The original app and its agent still use 127.0.0.1:8000. A local proxy
    # on 8080 preserves browser access to the localhost-only admin pages.
    # Compose publishes only the proxy, and only on the PC's loopback address.
    backend = make_server("127.0.0.1", 8000, application, threaded=True)
    proxy = ProxyMiddleware(
        NotFound(),
        {"/_container/": {"target": "http://127.0.0.1:8000/", "remove_prefix": True}},
        timeout=600,
    )

    def forward(environ, start_response):
        # ProxyMiddleware expects a named prefix. Add it internally so that
        # root, static assets, and API routes keep their original browser URLs.
        environ["PATH_INFO"] = "/_container" + environ["PATH_INFO"]
        return proxy(environ, start_response)

    frontend = make_server("0.0.0.0", 8080, forward, threaded=True)
    background_servers = [backend]

    if request_mode == "structured":
        from structured_lab import make_internal_app

        # A separate listener keeps the POST target off the published UI proxy.
        # It shares the event dictionary so the normal event page shows changes.
        background_servers.append(make_server(
            "127.0.0.1", 9001, make_internal_app(module.EVENTS), threaded=True
        ))

    if os.environ.get("TICKETORACLE_PORT22_TEST", "0") == "1":
        class SSHBannerHandler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.sendall(b"SSH-2.0-TicketOracleLab_1.0\r\n")
                # Consume the client's first line before closing so an HTTP
                # probe sees the banner instead of a TCP reset.
                self.request.settimeout(0.5)
                try:
                    self.request.recv(4096)
                except (socket.timeout, OSError):
                    pass

        class SSHBannerServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

        # Banner-only test target: no SSH authentication, file or shell access.
        # It is reachable only inside this container's loopback interface.
        background_servers.append(
            SSHBannerServer(("127.0.0.1", 22), SSHBannerHandler)
        )

    workers = [
        threading.Thread(target=server.serve_forever, daemon=True)
        for server in background_servers
    ]
    for worker in workers:
        worker.start()

    def stop(_signum, _frame):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop)
    try:
        frontend.serve_forever()
    finally:
        frontend.server_close()
        for server in background_servers:
            server.shutdown()
            server.server_close()
        for worker in workers:
            worker.join(timeout=5)


if __name__ == "__main__":
    main()
