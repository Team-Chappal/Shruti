# SHRUTI — Benchmark numbers

The DSP hot-path benchmark, run on the developer's laptop. Captured
as part of the regression suite; refresh with `make bench`.

The numbers below are from the captured run on this machine; the
JSON at `data/benchmarks/latest.json` is the source of truth and
gets committed alongside any change to the DSP code.

## What we measure

Each benchmark runs 200 iterations of the operation on a fixed-size
input and reports the median, p95, and max wall-clock time. The
median is the "typical" number; the p95 is what the live demo has
to budget for; the max catches refactors that introduce
constant-factor regressions.

| Benchmark                     | What it covers                                  |
|-------------------------------|-------------------------------------------------|
| `chirp_cross_correlation_2s`  | 2-second chirp xcorr (one per heartbeat)         |
| `gcc_phat_2048`               | TDOA estimate on a 2048-sample window            |
| `das_2s`                      | Delay-and-sum beamforming on 2 s of audio        |
| `mvdr_2s_n8`                  | MVDR beamforming with 8 sub-frames                |
| `protocol_frame_packet`       | CRC-32C + header packing for one packet          |

## Captured numbers

Run on Windows 11, Python 3.12, single-threaded, NumPy 2.4.6,
SciPy 1.17.1, Numba-free (pure NumPy).

```
name                                 median        p95        max
chirp_cross_correlation_2s          2.25ms     2.48ms     3.22ms
gcc_phat_2048                       0.08ms     0.09ms     0.61ms
das_2s                             15.13ms    16.09ms    17.41ms
mvdr_2s_n8                          2.66ms     2.87ms     7.42ms
protocol_frame_packet               0.08ms     0.08ms     0.12ms
```

## Latency budget

The live demo's round-trip budget is 200 ms end-to-end. The
numbers above tell us what fraction each operation eats:

| Step                                | Time      | Of budget  |
|-------------------------------------|-----------|------------|
| Capture → frame (on phone)          | 20 ms     | 10%        |
| Frame → Wi-Fi Direct → laptop       | ~5 ms     | 2.5%       |
| Server parse + CRC + queue          | < 0.5 ms  | 0.25%      |
| DSP loop: align, TDOA, beamform     | 16 ms (D&S) / 3 ms (MVDR) | 8% / 1.5% |
| ASR pass-through (mock or sherpa)    | 5-30 ms   | 2.5-15%    |
| Render → screen mirror              | 16 ms     | 8%         |
| **Total (D&S path)**                 | **~65 ms**| **32%**    |
| **Total (MVDR path)**                | **~50 ms**| **25%**    |

The headroom (200 ms - 65 ms = 135 ms) is the network jitter
budget. On the hackathon's Wi-Fi Direct, the measured jitter is
typically 30-50 ms p99.

## Why D&S is slower than MVDR here

D&S is `O(N log N)` per frame because of the FFT-based delay
phase-shifts. MVDR is also `O(N log N)` for the sub-frame DFTs
plus an `O(N^3)` per-frequency-bin solve; for N=3 the solve is
3x3 = 27 multiplies, so MVDR ends up faster. The "D&S is
simpler" advantage is real only for very small N; the team's
regression harness uses D&S as the smoke gate because it's
better-understood and easier to reason about, not because it's
faster.

## Refactor guard

The benchmark is the tripwire for constant-factor regressions.
If a refactor makes D&S 50% slower but doesn't change the
output, the unit tests stay green but the benchmark catches it
in CI. (The benchmark currently runs locally only; adding it to
the CI workflow is a Wave 10 item.)

## How to refresh

```sh
cd apps/laptop
make bench     # writes data/benchmarks/latest.json
```

The JSON is the canonical record; the markdown here is a
human-friendly view. Don't hand-edit either.
