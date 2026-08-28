# Contributing to SHRUTI

Thanks for your interest. This is a hackathon project that
lives or dies on whether the live demo works at the venue, so
contributions that improve test coverage, fix real bugs, or
add new defensive layers are most welcome.

## Quick start

```sh
git clone https://github.com/Team-Chappal/Shruti.git
cd Shruti
cd apps/laptop
python -m pip install -e ".[dev]"
make test     # 109 tests
make bench    # microbenchmark
make demo     # end-to-end pipeline, no real hardware
```

The CI runs the same gate on every push:
ruff, mypy (strict), bandit, pytest with a 75% coverage gate,
the end-to-end `shruti-array demo` smoke, and the benchmark.
All of these are runnable locally; the dev loop is fast.

## What to contribute

The team has 17 closed issues covering the original build.
The remaining work is:

- **Wiring the Android app to the real iQOO fleet.** The
  Kotlin side has `NEEDS-DEVICE` markers; the on-device
  calibration, the UNPROCESSED source selection, and the
  Wi-Fi Direct bridge host IP are all event-day work.
- **A real ASR/TTS integration.** The sherpa-onnx and
  Piper scaffolds are in place; the QNN-exported model and
  the on-device integration are event-day work.
- **A real `tools/record_corpus.py` that captures and
  labels scenes** from a known speaker in a known room.
  The current scaffold is a stub.
- **More tests on the recorded-corpus path.** The
  synthetic-corpus gate is permissive (-3.0 dB); the
  recorded-corpus gate is what the event actually
  evaluates. Tests that exercise the batch fallback
  against real-room WAVs are welcome.
- **Wire-format versioning.** The current protocol is
  v1, frozen. A v2 with a per-event pre-shared key (per
  `docs/SECURITY.md`) is the next thing on the security
  roadmap.
- **Documentation polish.** Anything in `docs/` that
  disagrees with the code, or that the next person on
  the project will trip over.

## Coding conventions

### Python

- `from __future__ import annotations` at the top of every
  module (the codebase targets 3.10+).
- Type hints everywhere. Mypy strict; the `warn_unused_ignores`
  and `warn_redundant_casts` flags are on.
- One class or one logical responsibility per module. The
  DSP modules each fit in ~100 lines; please don't ship
  500-line files.
- Docstrings on every public function and class. The
  project uses the Google docstring style with a one-line
  summary plus a longer body where it helps.
- Tests are in `apps/laptop/tests/test_<module>.py` and
  import the module under test directly. We do not mock
  the protocol layer or the DSP math; tests assert on
  real numeric output. If you find yourself reaching for
  `unittest.mock`, that's usually a code smell.
- The CI runs on Python 3.10, 3.11, and 3.12. Type hints
  must work across all three.

### Kotlin

- `object Protocol` is the home for all wire-format
  constants. The Python reference is in
  `apps/laptop/shruti_array/protocol.py`; **the two must
  stay byte-compatible.** If you change a constant, the
  tests on both sides catch it before CI goes green.
- The CRC-32C self-test runs at object init time. If the
  self-test fails the whole module fails to load. This is
  intentional.
- Android `linter.xml` flags a few intentional warnings
  (e.g., `MissingTranslation` — we ship English-only).
  Don't remove those without checking with the team.

## Pull request process

1. **One logical change per PR.** If your PR fixes three
   unrelated bugs, the merge will be deferred until the
   PR is split. This keeps the git history auditable for
   the hackathon judges.
2. **Tests first.** If you're adding a new feature, the PR
   should include the test that proves the feature works
   *and* a test that documents how a future refactor would
   catch a regression.
3. **The CI gate must be green.** All of ruff, mypy,
   bandit, pytest (with coverage), the demo smoke, and
   the benchmark must pass.
4. **Commit messages start with the wave name** if you're
   part of the autonomous-polish pass (`Wave 12: ...`).
   Other contributors can use any prefix; the team uses
   `fix:`, `feat:`, `docs:`, `chore:`, and `refactor:`
   for non-wave commits.
5. **Don't push to main directly.** Use a side branch
   (the team uses `autonomous-polish` for the bulk
   polish work; other contributors should pick
   descriptive names). The `main` branch is the
   battle-plan's "code written on-site" record.

## What NOT to do

- **Don't fabricate on-device numbers.** The 42 µs sync
  number, the UNPROCESSED capture, the Wi-Fi Direct
  throughput, and the ASR WER are all real measurements
  that need the loaner fleet. If a test or a doc quotes
  a number, it should be either (a) a design target with
  "target" or "predicted" in the wording, or (b) a
  measurement that's actually been taken.
- **Don't replace `NEEDS-DEVICE` markers with simulated
  code that pretends to be the real thing.** The markers
  are honest; replacing them with code that compiles but
  doesn't reflect real device behaviour is dishonest.
- **Don't disable the CI gates to make a PR merge.** If
  a gate is wrong, fix the gate. If the code is wrong,
  fix the code. `--no-verify` is not the answer.
- **Don't commit `data/` artifacts.** The gitignore
  excludes the corpus, the captures, the regression
  reports, the audit reports, and the models directory.
  If you need a new file there, it's transient; the
  per-event refresh is in `tools/rebuild/recipe.md`.

## Code of conduct

This is a hackathon project. The team is small, the
deadline is real, and the venue is loud. Be kind, be
specific, and be on time. Disagreements go in the PR
thread, not in the venue.

## License

MIT, per `LICENSE`. By contributing, you agree that your
contributions are licensed under the same terms.
