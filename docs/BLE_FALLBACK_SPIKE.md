# T17: BLE / Auracast transport fallback spike

Status: **design spike** — 2026-08-29. Not implemented in
production code. The OkHttp WebSocket path on Wi-Fi is the
primary transport; this document explains what we'd do if it
falls over at the venue.

## 1. When this matters

The OkHttp WebSocket on the Wi-Fi connection works when:

- Both the laptop and the three phones are on the same Wi-Fi
  SSID.
- The Wi-Fi AP does not have client isolation enabled
  (Android hotspots enable this by default; a venue router
  usually does not).
- The phone's network is reachable from the laptop. In the
  tests we ran on 2026-08-29, mobile hotspots from both the
  Nothing and a friend phone had client isolation enabled,
  which made the realme unable to reach the laptop on the
  hotspot subnet.

If the venue Wi-Fi also has isolation, or if the room has no
usable Wi-Fi, we need a fallback. The two candidates are BLE
and Auracast (LE Audio broadcast).

## 2. BLE GATT server on the laptop, GATT client on the phone

The laptop runs a BLE GATT server with one service:

- Service UUID: `0000a1b2-0000-1000-8000-00805f9b34fb` (SHRUTI)
- Characteristic UUID: `0000a1b3-...-34fb` (audio frames)
- Characteristic UUID: `0000a1b4-...-34fb` (config — read
  sample rate, phone id, is_master)

The phone's app subscribes to `a1b3` notifications. The laptop
gates notifications on a 20 ms timer (one frame's worth of PCM
@ 48 kHz = 960 samples). The phone feeds the received
notifications into the same `TransportClient.send()` path that
the WebSocket path uses; the rest of the DSP loop is unchanged.

### Why we chose GATT, not L2CAP

L2CAP credit-based channels would be faster (no GATT MTU
overhead) but require a paired connection and the laptop's BLE
stack has to support Credit-Based Flow Control mode. GATT works
on stock Bluetooth 4.0+ which both phones have.

### MTU and throughput

- Default GATT MTU is 23 bytes (3 bytes overhead, 20 bytes
  payload). One frame is 1954 bytes; that's 98 GATT writes per
  frame.
- Negotiating a 512-byte MTU is standard on Android 8+ and on
  Windows 10+ (which has native BLE GATT server support since
  Windows 10 1809). That drops the per-frame writes to 4.
- 48 kHz * 2 bytes = 96 kB/s audio. At 512-byte MTU and 100 ms
  notification interval, the GATT path can carry 5 kB/s. So we
  need a higher notification rate (~20 ms) and possibly chunking
  across multiple characteristics.

The laptop GATT server will use **three parallel characteristics**
(`a1b3`, `a1b5`, `a1b6`), each carrying one third of the frame,
notified simultaneously. With 512-byte MTU and 20 ms
notifications, this gives ~76 kB/s aggregate. Close to the 96
kB/s we need; the 20 kB/s gap is absorbed by the phone's
receive-side ring buffer.

## 3. Auracast (LE Audio broadcast) — rejected for v1

Auracast is the broadcast profile of Bluetooth LE Audio. It
supports a 16 kHz or 48 kHz mono broadcast stream, multiple
receivers, and is genuinely the right answer for a microphone
array. Reasons we are not using it for v1:

- Windows 10 / 11 has no Auracast support. The laptop GATT
  server is the only piece of code that needs to be portable;
  the phones can be swapped at the venue.
- Auracast receivers cannot be told the *correct* sample
  time, only the broadcast time. The chirp handshake relies
  on per-receiver arrival time, which GATT preserves and
  Auracast flattens.
- The Qt-style "audio sharing" UX of Auracast is wrong for a
  hackathon demo where the judge wants to see the array
  configuration, not join a broadcast.

When Windows ships Auracast (2027+), T17 should be revisited.

## 4. The spike we'd write

A 1-day spike that proves the BLE path works end-to-end on the
real hardware:

- `apps/android/app/src/main/kotlin/dev/shruti/transport/BleTransportClient.kt`
  — replaces `TransportClient` for the BLE path. Same `send()`
  and `start(context)` API, different transport.
- `apps/laptop/shruti_array/ingest/ble_server.py` — Python
  `bleak` GATT server that mimics the WebSocket server's
  `PacketServer` handler.
- `tests/test_ble_transport.py` — round-trip test on real
  hardware, like the WebSocket e2e test.

The BLE path is *only* enabled when the OkHttp WebSocket fails
to connect for 5+ seconds. The phone falls back automatically;
the laptop never advertises BLE unless the WS listener has
missed a heartbeat from all 3 phones.

## 5. Why we did not implement it

1. The venue's Wi-Fi is a real AP without client isolation, so
   the WebSocket path is the right answer for iQOO City Battles
   2026. The BLE fallback is a future-tense concern.
2. `bleak` (the only mature Python BLE GATT library) is Linux-
   only. A Windows port would have to be written.
3. The OkHttp WebSocket fix from the T16 commit (the
   `TransportClient.start(context)` was never being called) is
   what actually unblocks the round-trip on real hardware. BLE
   is a parallel safety net, not a primary fix.

## 6. The acceptance criteria for T17 (if we ever start it)

- [ ] `BleTransportClient.start(context)` connects to the
      laptop's GATT service in < 3 s on a real phone.
- [ ] 60 s of audio round-trips over BLE with < 1% packet loss
      (same as WebSocket).
- [ ] `test_ble_transport.py` runs in CI on Linux.
- [ ] Phone falls back to BLE within 5 s of WebSocket failure,
      recovers to WebSocket within 5 s of WebSocket recovery.
- [ ] Documented in `docs/OPERATIONS.md` how to enable the BLE
      path on the laptop and the phones.
