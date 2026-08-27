"""Tests for the lightweight metrics module."""
from __future__ import annotations

from shruti_array.metrics import GLOBAL, Metrics


def test_inc_and_snapshot() -> None:
    m = Metrics()
    m.inc("foo_total")
    m.inc("foo_total")
    m.inc("foo_total", value=3, phone="a")
    snap = m.snapshot()
    assert snap["counters"]["foo_total"] == 2.0
    assert snap["counters"]["foo_total{phone=\"a\"}"] == 3.0


def test_set_gauge() -> None:
    m = Metrics()
    m.set_gauge("queue_depth", 7.5)
    m.set_gauge("queue_depth", 3.0)
    snap = m.snapshot()
    assert snap["gauges"]["queue_depth"] == 3.0


def test_render_openmetrics_text() -> None:
    m = Metrics()
    m.inc("shruti_packets_received_total")
    m.inc("shruti_packets_received_total", phone="0")
    m.set_gauge("shruti_active_phones", 3)
    out = m.render()
    assert "shruti_packets_received_total 1" in out
    assert "shruti_packets_received_total{phone=\"0\"} 1" in out
    assert "shruti_active_phones 3.000" in out


def test_merge_aggregates() -> None:
    a = Metrics()
    a.inc("c_total", 5)
    b = Metrics()
    b.inc("c_total", 3)
    a.merge(b)
    assert a.snapshot()["counters"]["c_total"] == 8.0


def test_global_is_a_metrics() -> None:
    # The module-level GLOBAL is a usable Metrics instance; we don't
    # assert specific values (other tests pollute it).
    assert isinstance(GLOBAL, Metrics)
