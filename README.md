# Shruti

> Three phones. One microphone. Zero mercy for noise.

**SHRUTI** fuses multiple smartphones into a single phased microphone array. Built for the iQOO Hackathon 2026 - City Battles (Smart Education track, Bengaluru).

## How it works

1. **Ultrasonic chirp handshake** synchronizes the phones' audio clocks.
2. **TDOA localization** finds the speaker in the room (radar view).
3. **Beamforming** steers a virtual mic at the speaker and suppresses everything else.
4. **Offline Indic ASR** on the Snapdragon NPU produces a clean, vernacular transcript.

All local. No cloud. No internet.

## Stack

- Android (Kotlin) - capture + UI
- DSP - chirp sync, GCC-PHAT TDOA, delay-and-sum beamforming
- ONNX Runtime + QNN - on-device ASR

## Team

Team Chappal - iQOO City Battles 2026, Bengaluru.

## Docs

- [Battle plan](./SHRUTI_BATTLE_PLAN.md)
- [Agent config](./AGENTS.md)
