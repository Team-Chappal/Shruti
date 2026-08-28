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

    t = sub.add_parser(
        "text-radar",
        help="Print a text-based radar to stdout. Useful for headless "
        "verification and over SSH; does not need the WebSocket server.",
    )
    t.add_argument("--hz", type=float, default=2.0, help="Refresh rate")
    t.add_argument("--seconds", type=float, default=0.0,
                   help="Exit after this many seconds; 0 means run until interrupted.")

    sub.add_parser("synth-corpus", help="Generate a deterministic synthetic corpus.")

    demo_p = sub.add_parser(
        "demo",
        help="Run the end-to-end pipeline with synthetic phones "
        "(no real hardware). The radar dot moves on a circle; "
        "the audio is a synthetic 440 Hz tone. Useful for "
        "dry-runs and as the integration test for the live demo.",
    )
    demo_p.add_argument("--phones", type=int, default=3,
                        help="Number of simulated phones (default 3)")
    demo_p.add_argument("--seconds", type=float, default=8.0,
                        help="Duration in seconds (default 8)")
    demo_p.add_argument("--speed", type=float, default=0.5,
                        help="Target angular speed in rad/s (default 0.5)")

    h = sub.add_parser("harness", help="Run the regression harness.")
    h.add_argument("--scenes", type=int, default=5)
    h.add_argument("--duration-s", type=float, default=2.0)
    h.add_argument("--out", type=str, default="data/regression_runs/report.json")
    # Default matches regression.py's synthetic-suite tolerance. Use a
    # positive value (e.g. 3.0) for the recorded-corpus event gate.
    h.add_argument("--require-mvdr-gain-db", type=float, default=-3.0)

    a = sub.add_parser("audit", help="Analyze a directory of phone captures.")
    a.add_argument("--captures", type=str, default="data/captures")
    a.add_argument("--out", type=str, default="data/audit/report.json")

    args = p.parse_args(argv)
    if args.cmd == "run-radar":
        from .config import ServerConfig
        from .ingest.websocket_server import PacketServer
        cfg = ServerConfig(
            host=args.host or ServerConfig().host,
            port=args.port or ServerConfig().port,
        )
        import asyncio
        asyncio.run(PacketServer(cfg).start())
    elif args.cmd == "text-radar":
        import math
        import time as _t

        from .render.console_radar import make_state_from_observation, render_to_terminal
        from .render.overlays import TranscriptLine
        started = _t.time()
        deadline = started + args.seconds if args.seconds > 0 else None
        i = 0
        try:
            while deadline is None or _t.time() < deadline:
                # Animate a synthetic speaker position so the operator
                # sees the dot move. The real radar pulls from the DSP
                # loop; this command is for headless smoke verification.
                theta = 0.05 * i
                pos = (math.cos(theta), math.sin(theta))
                state = make_state_from_observation(
                    position_xy=pos,
                    sync_stability_us=42.0 + (i % 5),
                    started_at_s=started,
                    beamform_active=True,
                    transcript_lines=[
                        TranscriptLine(
                            track_id=0,
                            text=f"text-radar tick {i}",
                            language="en",
                            confidence=1.0,
                        ),
                    ],
                )
                render_to_terminal(state)
                _t.sleep(1.0 / max(args.hz, 0.1))
                i += 1
        except KeyboardInterrupt:
            pass
        return 0
    elif args.cmd == "synth-corpus":
        from .tools.corpus import main as corpus_main
        return corpus_main(["synth", "--out", "data/corpus/synth"])
    elif args.cmd == "demo":
        from .demo import main as demo_main
        return demo_main([
            "--phones", str(args.phones),
            "--seconds", str(args.seconds),
            "--speed", str(args.speed),
        ])
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
