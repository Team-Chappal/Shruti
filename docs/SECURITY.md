# SHRUTI — Trust model and security posture

A real product with a threat model in mind. This document is short
because the threat surface is small: the array processor only
accepts audio from three phones on the same Wi-Fi Direct group at
demo time, and the wire format is a custom protocol we control
end-to-end. But "small surface" is not "no surface," and the few
defenses we have are real.

## What we trust

- **The three phones on the Wi-Fi Direct group.** They are the
  only source of audio we accept. The ingest server refuses any
  connection that doesn't carry our packet format.
- **The laptop's filesystem.** All state is on disk; the
  `tools/rebuild/dirty-check.py` script refuses to start a
  rebuild on a dirty git tree. A compromised laptop compromises
  the whole system; this is inherent to the deployment model.
- **The Python and Kotlin standard libraries.** No third-party
  crypto in the audio path; CRC-32C is for integrity, not
  authentication.

## What we do not trust

- **The LAN.** The laptop's WebSocket server binds to
  `0.0.0.0:8765` by default, which means it accepts connections
  from anyone on the local network. This is fine for the demo
  venue (closed Wi-Fi, three phones only). For any deployment
  outside that, bind to the Wi-Fi Direct group owner's interface
  only and require the client to send a pre-shared key (TBD).
- **The packet's claimed `phone_id`.** The protocol accepts the
  `phone_id` from the wire. A hostile device can claim any
  `phone_id` it likes and inject audio. Mitigations: a per-event
  pre-shared key inserted into a future version of the protocol
  (the `reserved` field is reserved for exactly this), and the
  rate limiter which caps injection.
- **The phones' clocks.** The chirp handshake is the only
  defense against a phone that has lost its clock lock. A
  malicious phone that has lost lock degrades its own channel
  and the algorithm's localisation, but cannot inject data
  outside its own sequence space.

## Defenses in place

- **CRC-32C integrity check on every packet.** A bit error in
  transit is detected and the packet dropped. The CRC polynomial
  is Castagnoli (iSCSI standard, hardware-offload on most NICs).
  Self-tested against the iSCSI test vector
  `crc32c("123456789") == 0xE3069283` at every import.
- **Per-frame size cap before CRC.** `MAX_PACKET_BYTES =
  HEADER_SIZE + 16384 * 2 + CRC_SIZE = 32802`. Anything larger
  is rejected without ever computing a CRC, so a hostile device
  can't tie us up in CRC computation on a 4 GB buffer.
- **Sliding-window rate limit per phone.** Default: 400 packets
  per 2 s per phone. Real phones send ~50/s; the limit is 4×
  headroom. A device that bursts above this is dropped, not the
  whole server.
- **Monotonic sequence check per phone.** Duplicates are dropped
  silently. Gaps are counted as dropped frames and exposed as
  the `shruti_dropped_frames_total` counter.
- **Bounded per-phone queue with drop-oldest semantics.** A slow
  consumer cannot stall the array; the oldest packet is dropped
  before the queue blocks the writer.
- **No filesystem access in the audio path.** Audio data lives
  in memory and flows through the DSP loop. The only disk
  interaction in the ingest path is the audit directory
  (`data/captures/`), which is written to from the team-controlled
  capture session, not from the network.
- **Structured logging with a JSON mode** (`SHRUTI_LOG_FORMAT=json`)
  for shipping to an aggregator without regex-parsing free text.
- **OpenMetrics `/metrics` endpoint** for live counter scraping.

## What we will add when the demo becomes a product

- **Per-event pre-shared key in the protocol's `reserved` field.**
  Both sides derive a per-packet MAC from the key + sequence
  number, defeating packet replay. The phone stores the key in
  Android Keystore, the laptop reads it from an env var.
- **Mutual TLS on the WebSocket** when the transport moves off
  Wi-Fi Direct. The current deployment trusts the LAN.
- **Rate limit on the per-phone sample rate field** to prevent
  a hostile device from claiming a 1 MHz sample rate and
  exhausting memory in the queue. Currently bounded by
  `MAX_PAYLOAD_SAMPLES`.
- **Provenance stamps in the corpus** (per-scene SHA-256 of the
  WAV files, signed with the team's GPG key) so judges can
  verify the recorded corpus wasn't swapped post-hoc.

## Reporting a vulnerability

This is a hackathon project. There is no formal security contact.
If you find a real issue, file a GitHub issue and tag it
`security`; the team triages within 48 hours during the event
window and within a week otherwise.
