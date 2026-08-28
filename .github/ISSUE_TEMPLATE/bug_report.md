name: Bug report
description: Something is wrong. Real bugs that would have hurt the demo get fixed first.
labels: ["needs-triage"]
---

## What happened

<!-- A precise description of the bug. "It crashed" is not enough;
"shruti-array harness --scenes 5 failed with TypeError: cannot
unpack non-iterable float object on line 167" is. -->

## How to reproduce

<!-- The exact command, the exact environment, the exact inputs.
If the bug requires a real device, say so — those go in the
'on-site only' bucket and may not get fixed pre-event. -->

```sh
cd apps/laptop
shruti-array ...  # the failing command
```

## What I expected

<!-- What you thought would happen. -->

## What actually happened

<!-- The output, the traceback, the screenshot. -->

```
# paste the error / output here
```

## Environment

- [ ] Laptop (Python)
  - Python version: <!-- 3.10 / 3.11 / 3.12 -->
  - OS: <!-- Windows / Linux / macOS -->
  - Commit: <!-- `git rev-parse --short HEAD` -->
- [ ] Android (Kotlin)
  - Device: <!-- e.g., iQOO Z7 -->
  - Android version: <!-- e.g., 13 -->
- [ ] Real devices involved
  - Which iQOO loaner: <!-- A / B / C -->

## Logs / metrics

<!-- If you have /metrics output, `shruti_packets_received_total`,
`shruti_crc_failures_total`, or anything else relevant, paste it
here. The metrics endpoint is the first thing the team looks at
when triaging. -->

```
# curl http://localhost:8766/metrics
```

## Severity

- [ ] **Live-demo blocker.** This breaks the toggle, the radar, the
      sync, or the ASR. Fix before the next event round.
- [ ] **Plausible-demo blocker.** Could break under load, under
      long uptime, or under venue-specific conditions.
- [ ] **Polish.** Annoying but not demo-blocking.
- [ ] **Cosmetic.** Wrong colour in the radar, a typo in a doc.
