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
    t.add_argument("--ascii", action="store_true",
                   help="Use ASCII glyphs only (Windows cp1252 console)")

    d = sub.add_parser(
        "dial",
        help="Dial the phones directly via WebSocket and read the audio. "
             "T19: used when the Wi-Fi AP has client isolation and the "
             "phones cannot reach the laptop. The laptop dials each phone's "
             "IP on port 8765; the phone's InboundWebSocketServer pushes "
             "the audio stream out to the laptop.",
    )
    d.add_argument(
        "--phone", action="append", required=True,
        help="Phone to dial, as 'phone_id=host' (repeatable). "
             "Example: --phone 0=10.158.110.1 --phone 1=10.158.110.136",
    )
    d.add_argument("--port", type=int, default=8765,
                   help="WebSocket port on the phone (default 8765).")
    d.add_argument("--duration", type=float, default=10.0,
                   help="How long to keep the connections open, seconds "
                        "(default 10).")

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
    demo_p.add_argument("--ascii", action="store_true",
                        help="Use ASCII glyphs only (Windows cp1252 console)")
    demo_p.add_argument(
        "--record-toggle", type=str, default=None, metavar="DIR",
        help="T15: write per-phone + beamformed WAVs to DIR for the "
        "duration of the demo. The toggle-moment capture asset.",
    )

    h = sub.add_parser("harness", help="Run the regression harness.")
    h.add_argument("--scenes", type=int, default=5)
    h.add_argument("--duration-s", type=float, default=2.0)
    h.add_argument("--out", type=str, default="data/regression_runs/report.json")
    # Default matches regression.py's synthetic-suite tolerance. Use a
    # positive value (e.g. 3.0) for the recorded-corpus event gate.
    h.add_argument("--require-mvdr-gain-db", type=float, default=-3.0)

    r = sub.add_parser(
        "replay",
        help="Replay a directory of pre-recorded multichannel "
        "stems through the live DSP pipeline. The third rung of "
        "the fallback ladder; no phones required. Renders the "
        "same text radar as `demo`.",
    )
    r.add_argument("directory", type=str,
                   help="Directory of per-phone WAV stems")
    r.add_argument("--seconds", type=float, default=8.0,
                   help="Duration in seconds (default 8)")
    r.add_argument("--speed", type=float, default=0.5,
                   help="Synthetic target angular speed in rad/s (default 0.5)")
    r.add_argument("--ascii", action="store_true",
                   help="Use ASCII glyphs only (Windows cp1252 console)")

    a = sub.add_parser("audit", help="Analyze a directory of phone captures.")
    a.add_argument("--captures", type=str, default="data/captures")
    a.add_argument("--out", type=str, default="data/audit/report.json")

    args = p.parse_args(argv)
    if args.cmd == "dial":
        from .ingest.phone_dialer import main as dial_main
        # Pass through the --phone / --port / --duration flags.
        dial_argv: list[str] = []
        for ph in args.phone:
            dial_argv += ["--phone", ph]
        dial_argv += ["--port", str(args.port), "--duration", str(args.duration)]
        raise SystemExit(dial_main(dial_argv))
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
                render_to_terminal(state, force_ascii=args.ascii)
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
        demo_argv = [
            "--phones", str(args.phones),
            "--seconds", str(args.seconds),
            "--speed", str(args.speed),
        ]
        if args.ascii:
            demo_argv.append("--ascii")
        if args.record_toggle:
            demo_argv.extend(["--record-toggle", args.record_toggle])
        return demo_main(demo_argv)
    elif args.cmd == "harness":
        from .harness.regression import main as harness_main
        return harness_main([
            "--scenes", str(args.scenes),
            "--duration-s", str(args.duration_s),
            "--out", args.out,
            "--require-mvdr-gain-db", str(args.require_mvdr_gain_db),
        ])
    elif args.cmd == "replay":
        from .replay import main as replay_main
        replay_argv = [
            args.directory,
            "--seconds", str(args.seconds),
            "--speed", str(args.speed),
        ]
        if args.ascii:
            replay_argv.append("--ascii")
        return replay_main(replay_argv)
    elif args.cmd == "audit":
        from .tools.audit import main as audit_main
        return audit_main(["--captures", args.captures, "--out", args.out])
    return 0  # pragma: no cover


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
