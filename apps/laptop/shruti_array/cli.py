"""SHRUTI laptop processor CLI.

Top-level entry point. The four real subcommands are:
  - `run-radar`     start the WebSocket server + the radar/toggle UI
  - `synth-corpus`  generate a deterministic synthetic corpus
  - `harness`       run the regression harness
  - `audit`         analyze a directory of phone captures

Everything else is a thin wrapper around a single Python module; we
keep this CLI minimal so the team has one mental model of how to launch
the laptop.
"""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="shruti-array", description="SHRUTI laptop array processor.")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run-radar", help="Start the WebSocket server and the radar/toggle UI.")
    r.add_argument("--host", type=str, default=None)
    r.add_argument("--port", type=int, default=None)

    sub.add_parser("synth-corpus", help="Generate a deterministic synthetic corpus.")

    h = sub.add_parser("harness", help="Run the regression harness.")
    h.add_argument("--scenes", type=int, default=5)
    h.add_argument("--duration-s", type=float, default=2.0)
    h.add_argument("--out", type=str, default="data/regression_runs/report.json")
    h.add_argument("--require-mvdr-gain-db", type=float, default=0.0)

    a = sub.add_parser("audit", help="Analyze a directory of phone captures.")
    a.add_argument("--captures", type=str, default="data/captures")
    a.add_argument("--out", type=str, default="data/audit/report.json")

    args = p.parse_args(argv)
    if args.cmd == "run-radar":
        from .ingest.websocket_server import PacketServer
        from .config import ServerConfig
        cfg = ServerConfig(
            host=args.host or ServerConfig().host,
            port=args.port or ServerConfig().port,
        )
        import asyncio
        asyncio.run(PacketServer(cfg).start())
    elif args.cmd == "synth-corpus":
        from .tools.corpus import main as corpus_main
        return corpus_main(["--out", "data/corpus/synth"])
    elif args.cmd == "harness":
        from .harness.regression import main as harness_main
        return harness_main([
            "--scenes", str(args.scenes),
            "--duration-s", str(args.duration_s),
            "--out", args.out,
            "--require-mvdr-gain-db", str(args.require_mvdr_gain_db),
        ])
    elif args.cmd == "audit":
        from .tools.audit import main as audit_main
        return audit_main(["--captures", args.captures, "--out", args.out])
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
