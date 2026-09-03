# Real-device round-trip status (T20 / RESOLVED 2026-09-03)

## Status: FULLY RESOLVED AND VERIFIED

Both test devices (**Nothing A059** and **realme RMX5030**) are now streaming live, uncompressed 48 kHz PCM audio simultaneously to the laptop with 100% Castagnoli CRC-32C verification over USB loopback tunnels (`adb reverse tcp:8765 tcp:8765`).

### Real Hardware Verification Output
```text
--- TEST SUMMARY ---
Phone 0 (Nothing A059):   Verified=1510 pkts (Audio=1495, Heartbeat=15), LastSeq=1495, TotalBytes=2,921,980
Phone 1 (realme RMX5030): Verified=1481 pkts (Audio=1466, Heartbeat=15), LastSeq=1466, TotalBytes=2,865,314
SUCCESS: Successfully received and verified audio streams from 2 phones!
```

---

## The Real Root Cause & Why It Was Misdiagnosed

### Prior Misdiagnosis:
The team previously suspected an OEM ColorOS/NothingOS kernel BPF cgroup socket filter because:
1. `nc -w 3 -z 172.20.122.185 8765` from the adb shell succeeded (returncode 0).
2. The Android app (`dev.shruti`) threw `socket failed: EPERM (Operation not permitted)` on every single `socket.create()` and `ServerSocket.bind()`.

### The Actual Root Cause:
`AndroidManifest.xml` was **missing `<uses-permission android:name="android.permission.INTERNET" />`**.

In the Android Linux kernel:
1. When an application process is forked by Zygote, Linux group `AID_INET` (GID 3003) is attached to the process **only** if the app declares `android.permission.INTERNET`.
2. Inspecting `/proc/<pid>/status` for `dev.shruti` revealed:
   ```text
   Uid:    10414   10414   10414   10414
   Gid:    10414   10414   10414   10414
   Groups: 9997 20414 50414
   ```
   GID 3003 was missing completely from the process groups!
3. The kernel's `net/ipv4/af_inet.c` checks `in_group_p(AID_INET)`. Without GID 3003 or `CAP_NET_RAW`, the kernel's `inet_create` function immediately returns `-EPERM` for **any** `AF_INET` socket creation, regardless of the target IP address (Wi-Fi, hotspot, or loopback).
4. The ADB shell worked only because `shell` (UID 2000) is pre-configured with GID 3003 (`AID_INET`).

---

## Changes Applied

1. **Manifest Permissions**:
   Added `android.permission.INTERNET` and `android.permission.ACCESS_NETWORK_STATE` to `apps/android/app/src/main/AndroidManifest.xml`.
2. **Endianness in Header Patching**:
   Fixed `WavFileWriter.patchHeaderSize` to write Little-Endian integers via `Integer.reverseBytes` for compliance with RIFF/WAVE 32-bit chunk size specifications.
3. **Automated Manifest Safety Test**:
   Added `manifest_declares_internet_permission` in `TransportClientWireTest.kt` to ensure `INTERNET` permission can never be accidentally regressed.
4. **Clean OkHttp MockWebServer Teardown**:
   Fixed MockWebServer shutdown handling in `TransportClientWireTest.kt`.
5. **Two-Phone USB Verification Tooling**:
   Added `tools/test_usb_round_trip.py` and `tools/live_two_phones_radar.py`.
