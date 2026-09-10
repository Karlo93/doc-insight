"""Start the internal query service."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(prog="di-query")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    uvicorn.run("doc_insight.query.main:app", host=args.host, port=args.port)
