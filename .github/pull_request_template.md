## Summary

<!-- One-paragraph description of the change. If this fixes a real
bug, say so explicitly; the team audits "real bug fixes" against
"polish" and they're treated differently in the changelog. -->

## What changed

<!-- The actual delta, file by file. The CI comments on the diff
will tell the reviewer what changed mechanically; tell them
*why* it changed. -->

- `path/to/file.py`: what changed and why
- `path/to/another.py`: ...

## Verification

<!-- Check every box that applies. The CI runs the laptop suite +
Android :protocol:test + lint + mypy + bandit + demo smoke + benchmark
on every push, so if the box is checked the contributor is saying
"I ran this locally and it passed." -->

- [ ] `cd apps/laptop && make test` (laptop tests, currently 109)
- [ ] `cd apps/laptop && make bench` (benchmark still in budget)
- [ ] `cd apps/laptop && shruti-array demo --seconds 1` (e2e smoke)
- [ ] `cd apps/android && ./gradlew :protocol:test` (Kotlin protocol, 11)
- [ ] New tests added if applicable (link the test file)
- [ ] Coverage not regressed below 75% (CI enforces)

## Type of change

- [ ] Bug fix (a real bug that would have hurt the demo)
- [ ] New feature (a defensive layer or a new piece of the pipeline)
- [ ] Refactor (no behavioural change)
- [ ] Documentation
- [ ] CI / build system
- [ ] Other (please describe)

## Checklist

- [ ] One logical change per PR (split if not)
- [ ] Commit messages follow the convention (wave name or prefix)
- [ ] No fabricated on-device numbers; no `NEEDS-DEVICE` markers
      replaced with simulated code
- [ ] No secrets, no `data/` artifacts, no large binary files
      committed
- [ ] If the change affects the wire format, the Kotlin side
      changes in the same commit
- [ ] If the change affects the CLI surface, `docs/CLI.md` is
      updated in the same commit

## Hackathon compliance

<!-- If this is a wave-of-X commit, the team uses these to track
which work was pre-event vs. on-site. -->

- [ ] Pre-event (planned work before the hackathon window)
- [ ] On-site (real work done at the venue)
- [ ] Post-event (polish / docs after submission)

## Related

<!-- Link the issue, the architecture doc section, the
LEARNED.md entry, or the wave-name commit. Reviewers want
to read the design first and the code second. -->
