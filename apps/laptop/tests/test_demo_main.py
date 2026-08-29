"""Direct tests for `shruti_array.demo.main`.

The demo CLI parses args, then calls `asyncio.run(_run_demo(...))`.
We mock `_run_demo` to assert the right kwargs are forwarded.
"""
from __future__ import annotations

from unittest import mock

import pytest

from shruti_array import demo


def test_demo_main_uses_default_args() -> None:
    """`demo` with no flags should use phones=3, seconds=8.0,
    speed=0.5."""
    async def fake_run(**kwargs):
        return None

    with mock.patch.object(demo, "_run_demo", side_effect=fake_run) as m:
        rc = demo.main([])
    assert rc == 0
    m.assert_called_once_with(
        n_phones=3, duration_s=8.0, target_speed_rps=0.5, force_ascii=False,
    )


def test_demo_main_forwards_overrides() -> None:
    """`demo --phones 2 --seconds 1.0 --speed 1.5` should
    pass all three through to `_run_demo`."""
    async def fake_run(**kwargs):
        return None

    with mock.patch.object(demo, "_run_demo", side_effect=fake_run) as m:
        rc = demo.main([
            "--phones", "2",
            "--seconds", "1.0",
            "--speed", "1.5",
        ])
    assert rc == 0
    m.assert_called_once_with(
        n_phones=2, duration_s=1.0, target_speed_rps=1.5, force_ascii=False,
    )


def test_demo_main_returns_zero_on_keyboard_interrupt() -> None:
    """If asyncio.run raises KeyboardInterrupt (user hits
    Ctrl-C in the actual demo), main() should swallow it
    and return 0 cleanly."""
    async def fake_run(**kwargs):
        raise KeyboardInterrupt

    with mock.patch.object(demo, "_run_demo", side_effect=fake_run):
        rc = demo.main(["--seconds", "0.1"])
    assert rc == 0


def test_demo_main_returns_zero_on_normal_completion() -> None:
    """If the asyncio loop completes normally (e.g. --seconds
    elapsed), main() should return 0."""
    async def fake_run(**kwargs):
        return None

    with mock.patch.object(demo, "_run_demo", side_effect=fake_run):
        rc = demo.main(["--seconds", "0.1"])
    assert rc == 0


def test_demo_main_propagates_non_keyboard_exceptions() -> None:
    """A non-KeyboardInterrupt exception in the demo loop
    should propagate (we don't want to swallow real bugs)."""
    async def fake_run(**kwargs):
        raise RuntimeError("real bug in the demo")

    with mock.patch.object(demo, "_run_demo", side_effect=fake_run):
        with pytest.raises(RuntimeError, match="real bug"):
            demo.main(["--seconds", "0.1"])


def test_demo_main_rejects_fewer_than_two_phones() -> None:
    """`demo --phones 1` (or 0) should fail with a clear
    error message, not crash inside the demo loop with
    `min() iterable argument is empty`. The DSP pipeline
    requires N >= 2 channels for GCC-PHAT and beamforming.
    """
    with pytest.raises(SystemExit) as exc:
        demo.main(["--phones", "1"])
    assert exc.value.code != 0
    with pytest.raises(SystemExit) as exc:
        demo.main(["--phones", "0"])
    assert exc.value.code != 0


def test_demo_main_accepts_two_phones() -> None:
    """`demo --phones 2` should be accepted (the Tier-0
    pitch mode uses 2 phones)."""
    async def fake_run(**kwargs):
        return None

    with mock.patch.object(demo, "_run_demo", side_effect=fake_run) as m:
        rc = demo.main(["--phones", "2", "--seconds", "0.1"])
    assert rc == 0
    m.assert_called_once_with(
        n_phones=2, duration_s=0.1, target_speed_rps=0.5, force_ascii=False,
    )


def test_demo_main_forwards_ascii_flag() -> None:
    """`demo --ascii` should set force_ascii=True on `_run_demo`."""
    async def fake_run(**kwargs):
        return None

    with mock.patch.object(demo, "_run_demo", side_effect=fake_run) as m:
        rc = demo.main(["--ascii", "--seconds", "0.1"])
    assert rc == 0
    m.assert_called_once_with(
        n_phones=3, duration_s=0.1, target_speed_rps=0.5, force_ascii=True,
    )
