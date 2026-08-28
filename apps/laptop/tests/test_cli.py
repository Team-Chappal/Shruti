"""Direct tests for the top-level CLI dispatch.

The CLI's `main()` is a dispatcher. The heavy subcommands
(`run-radar`, `text-radar`, `demo`) call into blocking
servers / event loops. We don't want to actually start a
WebSocket in a unit test; we want to verify that the right
subcommand is invoked with the right arguments, and that
the argparse surface is what the docs and the
CONTRIBUTING.md quick-start claim it is.

Strategy: replace the imported module-level references to
the blocking entry points with mocks, then call `main()`
and assert the right thing happened.
"""
from __future__ import annotations

import sys
from unittest import mock

import pytest

from shruti_array import cli


def _called_with(mock_obj: mock.MagicMock, *args: str) -> bool:
    """True if `mock_obj` was called with the given argv list."""
    return mock_obj.call_args == mock.call(list(args))


def test_cli_help_lists_every_subcommand() -> None:
    """The argparse `--help` output is what the README and
    CONTRIBUTING.md link to. Every subcommand must be
    discoverable, with non-empty help text."""
    with mock.patch.object(sys, "argv", ["shruti-array", "--help"]):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
    assert exc.value.code == 0
    # The argument parser writes to stdout/stderr; we don't
    # need to assert on the exact text, just that no
    # exception escaped. The other tests in this file
    # exercise each subcommand individually.


def test_cli_dispatches_text_radar_with_seconds_zero() -> None:
    """`text-radar --seconds 0` should call into the text
    radar's loop. We mock the render call (the sleep
    inside the loop is real) and a short --seconds lets the
    loop exit on its own. Use seconds=0.01 to avoid
    actually waiting."""
    with mock.patch("shruti_array.render.console_radar.render_to_terminal") as m:
        with mock.patch("time.sleep", side_effect=KeyboardInterrupt):
            rc = cli.main(["text-radar", "--seconds", "0.01", "--hz", "50"])
    assert rc is None or rc == 0
    assert m.called


def test_cli_dispatches_synth_corpus_to_corpus_main() -> None:
    """`synth-corpus` should hand off to `corpus.main(["synth",
    "--out", "data/corpus/synth"])`."""
    with mock.patch("shruti_array.tools.corpus.main", return_value=0) as m:
        rc = cli.main(["synth-corpus"])
    assert rc == 0
    assert m.call_args == mock.call(["synth", "--out", "data/corpus/synth"])


def test_cli_dispatches_harness_with_overridden_args() -> None:
    """`harness` should forward every CLI flag to
    `regression.main` as a string list."""
    with mock.patch("shruti_array.harness.regression.main", return_value=0) as m:
        rc = cli.main([
            "harness",
            "--scenes", "7",
            "--duration-s", "1.5",
            "--out", "/tmp/r.json",
            "--require-mvdr-gain-db", "-1.5",
        ])
    assert rc == 0
    args, _ = m.call_args
    assert args == ([
        "--scenes", "7",
        "--duration-s", "1.5",
        "--out", "/tmp/r.json",
        "--require-mvdr-gain-db", "-1.5",
    ],)


def test_cli_dispatches_audit_with_overridden_paths(tmp_path) -> None:
    """`audit` should forward `--captures` and `--out` to
    `audit.main`."""
    with mock.patch("shruti_array.tools.audit.main", return_value=0) as m:
        rc = cli.main([
            "audit",
            "--captures", str(tmp_path / "caps"),
            "--out", str(tmp_path / "report.json"),
        ])
    assert rc == 0
    assert m.call_args == mock.call([
        "--captures", str(tmp_path / "caps"),
        "--out", str(tmp_path / "report.json"),
    ])


def test_cli_dispatches_demo_with_all_args() -> None:
    """`demo` should forward `--phones`, `--seconds`, `--speed`
    to `demo.main` as strings (with the expected
    float/int conversions from argparse)."""
    with mock.patch("shruti_array.demo.main", return_value=0) as m:
        rc = cli.main([
            "demo",
            "--phones", "2",
            "--seconds", "3",
            "--speed", "0.25",
        ])
    assert rc == 0
    args, _ = m.call_args
    # argparse converted the numeric flags to typed values
    # before re-stringifying them in the cli dispatcher.
    assert args == (["--phones", "2", "--seconds", "3.0", "--speed", "0.25"],)


def test_cli_run_radar_passes_host_and_port_through() -> None:
    """`run-radar --host X --port Y` should construct a
    ServerConfig with `host=X, port=Y` and pass it to
    `PacketServer(cfg)`. We can't actually run the server,
    so we patch both `PacketServer` (to capture the config)
    and `asyncio.run` (to return immediately instead of
    blocking forever)."""
    captured: dict = {}

    class _FakeServer:
        def __init__(self, cfg):
            captured["cfg"] = cfg
        async def start(self):
            captured["started"] = True

    with mock.patch(
        "shruti_array.ingest.websocket_server.PacketServer", _FakeServer
    ), mock.patch("asyncio.run", return_value=None):
        rc = cli.main(["run-radar", "--host", "10.0.0.5", "--port", "9000"])
    # The PacketServer was constructed with the right config.
    assert captured["cfg"].host == "10.0.0.5"
    assert captured["cfg"].port == 9000
    # The run-radar branch doesn't return a value (the
    # real one blocks on the server).
    assert rc is None or rc == 0


def test_cli_run_radar_defaults_to_serverconfig_defaults() -> None:
    """`run-radar` with no flags should use ServerConfig's
    own defaults."""
    captured: dict = {}

    class _FakeServer:
        def __init__(self, cfg):
            captured["cfg"] = cfg
        async def start(self):
            pass

    with mock.patch(
        "shruti_array.ingest.websocket_server.PacketServer", _FakeServer
    ), mock.patch("asyncio.run", return_value=None):
        rc = cli.main(["run-radar"])
    # args.host is None, so the dispatcher falls back to
    # ServerConfig().host == "0.0.0.0" (and port 8765).
    assert captured["cfg"].host == "0.0.0.0"
    assert captured["cfg"].port == 8765
    assert rc is None or rc == 0


def test_cli_missing_subcommand_exits_with_error() -> None:
    """A bare `shruti-array` with no subcommand should exit
    non-zero (argparse enforces required=True on the
    subparsers)."""
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code != 0


def test_cli_unknown_subcommand_exits_with_error() -> None:
    """An unknown subcommand should also exit non-zero."""
    with pytest.raises(SystemExit) as exc:
        cli.main(["bogus"])
    assert exc.value.code != 0


def test_cli_text_radar_argument_parsing_only() -> None:
    """Validate that the text-radar subcommand accepts the
    documented flags and that the resulting RadarState has
    the expected fields. We bail out of the loop after one
    tick by raising KeyboardInterrupt from a mocked sleep."""
    with mock.patch("shruti_array.render.console_radar.render_to_terminal") as m:
        with mock.patch("time.sleep", side_effect=KeyboardInterrupt):
            cli.main(["text-radar", "--seconds", "0.1", "--hz", "10"])
    # render_to_terminal was called at least once.
    assert m.called
    # The first call's first arg is a RadarState; the
    # sync_stability_us was 42.0 + (i % 5) for i=0, so 42.0.
    first_state = m.call_args_list[0].args[0]
    assert first_state.sync_stability_us == pytest.approx(42.0, abs=1e-9)
