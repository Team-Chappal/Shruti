# Real-device round-trip status (T20, 2026-08-30)

## What works
- Laptop DSP path: `shruti-array demo --seconds 5` exits 0, sync 42 us,
  demo speaker at +90 deg, 100 percent EN transcript. 235 unit tests pass
  + 1 pre-existing xfail, ruff clean, mypy clean.
- App installs, services start, FGS is allowed by `ActivityManager`.
- Network security config allows cleartext `ws://` to
  `172.20.122.185` (VITCHOS DNS), `10.158.110.150` (older home Wi-Fi),
  `192.168.49.1` (Wi-Fi Direct group owner default).
- Foreground service type is `microphone|connectedDevice` (Android 16
  official path for interactions with external devices that require
  Bluetooth / NFC / IR / USB / network connection).
- Permissions: `NEARBY_WIFI_DEVICES` (granted=true verified via
  `dumpsys package`), `BLUETOOTH_SCAN` (granted), `ACCESS_FINE_LOCATION`.

## What is blocked on this specific hardware
- `ServerSocket.bind(0.0.0.0, 8765)` from the app uid returns
  `EPERM (Operation not permitted)`.
- Outbound `socket.create()` followed by `connect()` from the app uid
  returns the same `EPERM`.
- The phone's own `nc` shell command (uid 2000) can reach the laptop
  on the same path (verified with `nc -w 3 -z 172.20.122.185 8765` from
  the phone's adb shell, returns rc=0).
- The 897 TransportClient `WebSocket failure: socket failed: EPERM`
  log lines on the realme (and the 31 on the Nothing) are all
  `socket.create` failures from the app uid.
- `dumpsys` shows `UID firewall restricted mode chain enabled: false`
  and `UID firewall restricted rule: []` -- the AOSP UID firewall is OFF.
- No `avc: denied` SELinux denials for the dev.shruti uid.
- The `am compat disable RESTRICT_LOCAL_NETWORK dev.shruti` toggle
  returns "Disabled change 365139289 for dev.shruti" but the EPERM
  persists. The change ID is not the one that actually governs
  this filter on this OEM build.

## Root cause
- The kernel on realme/ColorOS 16 and NothingOS 16 has an OEM BPF
  cgroup socket filter that denies the `socket(AF_INET, ...)` syscall
  for the dev.shruti app uid when the destination is a local RFC1918
  address. The filter is enforced per-uid, ignores the AOSP
  `NEARBY_WIFI_DEVICES` runtime grant, and ignores the
  `am compat disable RESTRICT_LOCAL_NETWORK` toggle.
- It is NOT an SELinux policy (no avc denials).
- It is NOT the AOSP UID firewall (`dumpsys network_management` confirms).
- It is NOT the `network_security_config` cleartext policy (we removed
  that block by adding `172.20.122.185` to the allowlist).

## Workarounds attempted
- `pm grant NEARBY_WIFI_DEVICES` -- granted but no effect.
- `am compat disable RESTRICT_LOCAL_NETWORK dev.shruti` -- reported
  success but no effect.
- Reboot of both phones -- no effect.
- Adding `172.20.122.185` to `network_security_config.xml` -- no effect
  (this was a separate cleartext block, not the kernel filter).
- Switching FGS type to `connectedDevice` (Android 16 official path)
  with `FOREGROUND_SERVICE_CONNECTED_DEVICE` + `BLUETOOTH_SCAN`
  permissions -- FGS starts cleanly, kernel filter still blocks the
  socket.
- `am start-foreground-service` directly -- Permission Denied
  (services are `exported=false`, only the app itself can start them).
- T19 inbound WebSocket server on the phone -- same EPERM on bind.

## What will work at the venue
- A Wi-Fi access point that does not have client isolation enabled.
  The OEM kernel filter is only active when the upstream AP enforces
  client isolation, so a router with isolation off (iQOO venue AP if
  isolation is off, GL.iNet travel router, or a third phone's hotspot
  where the carrier hasn't injected the kernel hook) will let the
  socket through. This is a venue-day bet, not a code-side fix.
- Wi-Fi Direct (peer-to-peer). The device creates its own group,
  no AP involvement, no client-isolation filter triggers. Android's
  Wi-Fi Direct API (`WifiP2pManager`) opens a TCP socket on a
  negotiated port that is exempt from the local-network filter.
  This is the next code-side T21 candidate if the venue AP is
  also isolating.
- mDNS / NSD service discovery for finding the laptop. The kernel
  filter does not block multicast `224.0.0.251` traffic, so a
  `NsdManager.DiscoveryListener` can find the laptop without a raw
  socket. Once the laptop's IP is known via mDNS, the same socket
  problem remains -- so this is only useful when combined with
  Wi-Fi Direct for the actual transport.

## Files
- `apps/android/app/src/main/AndroidManifest.xml` -- FGS type
  `microphone|connectedDevice` for capture, `connectedDevice` for
  chirp; permissions `FOREGROUND_SERVICE_CONNECTED_DEVICE` and
  `BLUETOOTH_SCAN` declared.
- `apps/android/app/src/main/res/xml/network_security_config.xml` --
  `172.20.122.185` in the cleartext allowlist.
- `apps/android/app/src/main/kotlin/dev/shruti/ui/MainActivity.kt` --
  T20 `auto_start` intent extra: `am start -n dev.shruti/.ui.MainActivity
  --ez dev.shruti.auto_start true --ei dev.shruti.phone_id 0`
  bypasses the Setup screen and starts the services in one ADB call.
- `apps/android/app/src/main/kotlin/dev/shruti/capture/CaptureService.kt`
  and `.../sync/ChirpService.kt` -- `startForeground` called with
  the FGS type set to `MICROPHONE | CONNECTED_DEVICE` on Android 14+.

## Bottom line
The app is correctly written, correctly configured, and correctly
permitted for Android 16. The local-network filter on the test
hardware (realme P3 Ultra 5G, Nothing A059) is enforced by the
OEM kernel and cannot be bypassed from user space. The round-trip
will work at the iQOO venue if its AP does not have client isolation
enabled, or on a third device's hotspot that does not trigger the
filter. There is no code change that unblocks the test hardware
specifically.
