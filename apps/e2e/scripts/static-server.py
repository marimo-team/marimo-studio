"""Serve exported test artifacts through concurrent browser module imports."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class StaticHandler(SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"


class StaticServer(ThreadingHTTPServer):
    # Notebook and native-renderer module graphs arrive as one request burst.
    request_queue_size = 128


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", type=int)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--directory", required=True)
    arguments = parser.parse_args()
    handler = partial(StaticHandler, directory=arguments.directory)
    with StaticServer((arguments.bind, arguments.port), handler) as server:
        server.serve_forever()


if __name__ == "__main__":
    main()
