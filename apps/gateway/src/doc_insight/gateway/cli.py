"""Serve HTTP inside the private network; TLS terminates at the reverse proxy."""

import argparse

import uvicorn
from doc_insight.gateway.settings import get_settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="di-gateway")
    parser.add_subparsers(dest="command", required=True).add_parser("serve")
    parser.parse_args()
    settings = get_settings()
    uvicorn.run(
        "doc_insight.gateway.main:app",
        host=settings.gateway_host,
        port=settings.gateway_port,
        access_log=False,
        proxy_headers=False,
    )
