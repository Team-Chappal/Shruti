# Protocol versioning policy (T16)

Status: **active** as of 2026-08-29.

The SHRUTI wire protocol is the contract between the Android phone
apps (`apps/android/`) and the laptop array processor
(`apps/laptop/shruti_array/`). The current version is **1**.

## 1. What the protocol is

Each binary packet is

```
[magic: u32][version: u8][type: u8][flags: u8][phone_id: u8]
  [sequence: u32][timestamp: u32][payload_len: u16]
  [payload: payload_len bytes]
  [crc32c: u32]
```

The first 12 bytes are the header. `magic` is the 4-byte ASCII
`"SHRT"` (`0x53 0x48 0x52 0x54`). `version` is the second byte.
See `apps/android/protocol/src/main/kotlin/dev/shruti/protocol/Protocol.kt`
and the Python mirror under `apps/laptop/shruti_array/protocol/`.

## 2. Why we version

Three reasons:

1. **The phones and the laptop are not always upgraded together.**
   A volunteer who updates the phone app to `0.4.0` might not be
   able to update the laptop on the same day. The protocol
   version is the first line of defence against silent breakage.
2. **The byte budget is fixed** — the `version` field is exactly
   one byte. There are only 256 possible values. We will exhaust
   them eventually, so the policy must plan for that.
3. **The protocol is on a hot path** — every audio packet carries
   a version byte. Any versioning policy that pays a per-packet
   cost (hashes, negotiation, type/length prefix) is wrong.

## 3. The policy

We use a **Major.Minor** scheme packed into the single version byte.

* **Major** (4 high bits) is the wire format. Bumping Major means
  "I will break a parser if it doesn't know me." Major is
  monotonically increasing; once a Major version is published, it
  is never reused. The first shipped version is Major=0. (The
  current `VERSION: Int = 1` is the value of the *full* byte,
  i.e. Major=0, Minor=1.)
* **Minor** (4 low bits) is the implementation level. Bumping
  Minor means "I added a new field that older receivers should
  ignore, or a new type code that older receivers should treat as
  unknown-but-not-fatal." Minors within the same Major are
  backward-compatible.
* A receiver MUST reject a packet whose Major differs from its own.
* A receiver MUST accept a packet whose Minor is greater than its
  own, treating any unknown type codes as `UnknownMessage` and
  dropping unknown flag bits.
* A receiver MAY accept a packet whose Minor is less than its own,
  but it should emit a metric (`protocol_minor_downgrade_total`)
  so the operator can spot a phone that's out of date.

## 4. The bump rules

* `patch` (last digit in `0.3.1`) — wire format unchanged. No
  version bump. Phone and laptop can be on different patches
  freely.
* `minor` (middle digit in `0.4.0`) — wire format unchanged but a
  new packet type or flag is added. Bump the protocol Minor. Older
  Major receivers are still compatible.
* `major` (first digit in `1.0.0`) — wire format changes. Bump
  the protocol Major. Old receivers MUST reject the packet.
  Requires both `apps/android/protocol/Protocol.kt` and
  `apps/laptop/shruti_array/protocol/` to be updated in the same
  commit so the byte-level test stays green.

## 5. The byte exhaustion plan

With 16 Major values, the *current* scheme can publish 16 major
versions. If we ship one Major every six months, that is 8 years
of headroom. By the time the high nibble fills, we will either be
out of business or rich enough to add a second version byte. The
v1.x line can extend Major to 4 bits (16 Majors) and split Minor
into 4 bits of minor + 4 bits of patch, giving 16 Majors * 16
Minors * 16 Patches = 4096 versions. The protocol header is
already oversized for what it carries; the additional byte is
free.

The escape hatch is documented but not pre-implemented. If we
reach v15, we file a follow-up and implement the second-byte
extension as a single commit that bumps Major to 16 and adds the
extra byte to the header. Old receivers (Major=0..14) still
parse the single-byte header; new receivers (Major=16+) know to
read the second byte.

## 6. The release checklist

When shipping a new protocol version, the PR description must
include:

- [ ] Old version constant (e.g. `const val VERSION: Int = 1`)
- [ ] New version constant (e.g. `const val VERSION: Int = 2`)
- [ ] Diff of the header layout (which fields changed, which
      fields are new, which fields were deleted)
- [ ] Cross-implementation test pass: the Python `Protocol` and
      Kotlin `Protocol` both encode + decode the new version's
      header identically.
- [ ] `tests/test_protocol.py` and
      `apps/android/protocol/src/test/kotlin/.../ProtocolTest.kt`
      updated to assert the new version is decoded correctly.
- [ ] `CHANGELOG.md` `[Unreleased]` section mentions the
      version bump in the *Added/Changed* subsection.
- [ ] Issue #20 (master task list) is updated: if this is a
      *Major* bump, the "all phones must be updated" footer is
      posted to the venue-day checklist.

## 7. Why we do not negotiate

A negotiation scheme ("phone sends `HELLO` with supported
versions, laptop responds with the agreed version") would add
latency, complexity, and a state machine. For a 5-minute demo at
a hackathon, the deterministic Major.Minor check on every packet
is faster, simpler, and easier to test. Negotiation belongs in
protocols that have a *handshake*, which we do not — phones stream
audio immediately and the laptop drops what it can't parse.

## 8. Related docs

- `docs/LEARNED.md` — the original "phone-laptop version skew" lesson
- `docs/SECURITY.md` — the policy on the `flags` byte (we use the
  high bit for `FLAG_DROPPED`; future flags must not collide)
- `CHANGELOG.md` — every wire-format change in every release
