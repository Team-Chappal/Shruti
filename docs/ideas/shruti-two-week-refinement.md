# SHRUTI — Two-Week Build Refinement

## Problem Statement
How might we give any classroom, press scrum, or crowded hall a studio-grade directional microphone — built from three phones already on the bench — with zero new hardware, zero internet, and zero cloud?

## Recommended Direction
**Spine-first + rebuild recipe + rubric breadth**, in five phases:

| Phase | Days | Delivers |
|---|---|---|
| **0 — Sync spike** | 1–2 | Go/no-go on the physics: chirp offset stability <100µs on personal phones; UNPROCESSED phase/latency characterization per unit; chirp-in-noise margin |
| **1 — Two-phone spine** | 3–5 | End-to-end floor: capture → Wi-Fi Direct → laptop → aligned frames → TDOA radar dot → RAW⟷BEAMFORMED toggle. **Noisy-room corpus recorded + regression harness** |
| **2 — Core deep** | 6–9 | MVDR upgrade, drift compensation, phone-3 admission, NPU Indic ASR (ONNX/QNN), vernacular TTS. **Rebuild recipe written alongside each milestone** (scripts, checklists, commit ritual) |
| **3 — Breadth** | 10–12 | Per-speaker transcript streams, stem-replay (laptop-closed recovery), robustness matrix, rubric-artifact audit |
| **4 — Dress rehearsal** | 13–14 | Full demo runs twice; **hedge executes**: rehearsed on-site rebuild run *or* polish + pitch video, per compliance verdict |

## Key Assumptions to Validate
- [ ] **Phase-coherent UNPROCESSED capture** — shared clap across 2 phones, cross-correlate, offset std <100µs *(kills the project if it fails)*
- [ ] **Chirp survives room noise** — PRBS detection rate >99% at fan+chatter SNR
- [ ] **Wi-Fi Direct sustains 3× 48kHz streams** — 5-min lossless laptop capture, zero drops
- [ ] **NPU runs Indic ASR real-time** — RTF <0.5 on QNN-exported model
- [ ] **Compliance model confirmed** — organizers clarify whether pre-written code may ship

## MVP Scope
Two phones: synced capture → radar dot → the toggle → transcript. The demo floor nothing can break below.

## Not Doing (and Why)
- **5-phone super array** — novelty dimension already won at 3; only if fully green by day 10
- **ML speaker diarization** — TDOA tracking covers the demo; rabbit hole
- **Cloud/internet features** — contradicts the core thesis
- **Cross-platform/iOS** — iQOO Android only
- **ASR fine-tuning** — pre-trained Indic model suffices; days of cost for marginal WER

## Open Questions
- Which Indic ASR model, and is there a proven QNN export path for it?
- Do all 3 loaner units share the same Snapdragon generation (phase parity)?
- Can you get venue access for one rehearsal before submission?
