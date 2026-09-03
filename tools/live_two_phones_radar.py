"""Live 2-Phone Phased Array, Radar, Web UI & Offline ASR via USB / Wi-Fi.

Connects to Phone 0 and Phone 1, drains packets through StreamAligner + DspLoop,
runs real-time Delay-and-Sum or MVDR beamforming, offline SherpaOnnx speech recognition,
and serves a live Web Dashboard with an interactive RAW <-> BEAMFORMED toggle at http://localhost:8766/.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Add apps/laptop to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "apps" / "laptop"))

import numpy as np

from shruti_array.config import AppConfig, ServerConfig
from shruti_array.dsp_loop import DspLoop
from shruti_array.ingest.metrics_server import MetricsHTTPServer
from shruti_array.ingest.websocket_server import PacketServer
from shruti_array.recorder import LoopRecorder
from shruti_array.render.console_radar import make_state_from_observation, render_to_terminal
from shruti_array.render.overlays import TranscriptLine
from shruti_array.sync.alignment import StreamAligner

try:
    import msvcrt
    HAS_MSVCRT = True
except ImportError:
    HAS_MSVCRT = False


def get_asr_engine(model_dir: Path, enable_real: bool = True):
    encoder = model_dir / "encoder.onnx"
    if enable_real and encoder.is_file():
        try:
            from shruti_array.asr.sherpa_onnx import SherpaOnnxASR, SherpaOnnxConfig
            return SherpaOnnxASR(
                SherpaOnnxConfig(
                    encoder=str(model_dir / "encoder.onnx"),
                    decoder=str(model_dir / "decoder.onnx"),
                    joiner=str(model_dir / "joiner.onnx"),
                    tokens=str(model_dir / "tokens.txt"),
                    language="en",
                )
            )
        except Exception as e:
            print(f"[ASR] Failed to initialize sherpa-onnx: {e}. Falling back to mock.", flush=True)
    from shruti_array.asr import MockASR
    return MockASR()


async def live_loop(
    duration_s: float = 15.0,
    beamformer: str = "das",
    record_toggle: str | None = None,
    force_ascii: bool = True,
):
    cfg = AppConfig.default()
    server = PacketServer(ServerConfig(host="0.0.0.0", port=8765))
    server_task = asyncio.create_task(server.start())

    beamform_active = True

    def toggle_mode() -> bool:
        nonlocal beamform_active
        beamform_active = not beamform_active
        mode_str = "BEAMFORMED (ARRAY ACTIVE)" if beamform_active else "RAW (SINGLE MIC)"
        print(f"\n>>> [TOGGLE FLIPPED] Current Mode: {mode_str} <<<\n", flush=True)
        return beamform_active

    metrics_server = MetricsHTTPServer(
        host="0.0.0.0",
        port=8766,
        packet_server=server,
        on_toggle=toggle_mode,
    )
    metrics_task = asyncio.create_task(metrics_server.start())

    await asyncio.sleep(0.2)
    print("==========================================================", flush=True)
    print("  SHRUTI 2-PHONE REAL-TIME ARRAY PROCESSOR (LIVE DEMO)", flush=True)
    print("==========================================================", flush=True)
    print("WebSocket Ingest: ws://0.0.0.0:8765/", flush=True)
    print("Web UI Dashboard: http://localhost:8766/  <-- OPEN IN BROWSER", flush=True)
    print("Interactive Hotkey: Press [SPACE] or [T] to toggle RAW <-> BEAMFORMED", flush=True)
    print(f"Beamformer: {beamformer.upper()} | Sync: Ultrasonic 17.5-22kHz PRBS", flush=True)

    model_dir = repo_root / "data" / "models" / "sherpa"
    asr = get_asr_engine(model_dir)
    print(f"ASR Engine: {asr.__class__.__name__}", flush=True)

    recorder = None
    if record_toggle:
        out_p = Path(record_toggle)
        out_p.mkdir(parents=True, exist_ok=True)
        recorder = LoopRecorder(out_dir=out_p, phone_ids=[0, 1], sample_rate_hz=48_000)
        print(f"Recording toggle stems into: {out_p}", flush=True)

    aligner = StreamAligner()
    aligner.register(phone_id=0, sample_rate_hz=48_000)
    aligner.register(phone_id=1, sample_rate_hz=48_000)

    loop = DspLoop(aligner, geometry=cfg.geometry, beamformer=beamformer)
    started = time.time()
    last_render = time.time()
    last_asr_time = time.time()
    frames_produced = 0
    accumulated_audio: list[np.ndarray] = []
    latest_transcript_text = "listening..."

    try:
        while duration_s < 0 or (time.time() - started < duration_s):
            # Check for console hotkey press (Windows)
            if HAS_MSVCRT and msvcrt.kbhit():
                try:
                    ch = msvcrt.getch()
                    if ch in (b" ", b"t", b"T"):
                        toggle_mode()
                except Exception:
                    pass

            # Drain packet queues from all connected phones
            queues = {pid: conn.queue for pid, conn in server._connections.items()}
            loop.pop_from_queues(queues, max_packets_per_phone=8)

            # Step the DSP pipeline
            frame = loop.step()
            if frame is not None:
                frames_produced += 1
                pos = frame.position_xy
                az_deg = (
                    float(np.degrees(np.arctan2(pos[1], pos[0])))
                    if pos is not None
                    else None
                )
                if recorder is not None:
                    recorder.record(frame)
                # If beamform active, accumulate array output; else raw Phone 0
                audio_sample = frame.beamformed if beamform_active else frame.channels[0]
                accumulated_audio.append(audio_sample)
            else:
                pos = loop.last_position
                az_deg = None

            # Run ASR every ~1.5 seconds if we have collected audio
            now = time.time()
            if now - last_asr_time >= 1.5 and accumulated_audio:
                audio_chunk = np.concatenate(accumulated_audio)
                # Keep last 0.5s for continuity, clear rest
                keep_samples = min(len(audio_chunk), 24_000)
                accumulated_audio = [audio_chunk[-keep_samples:]]
                try:
                    segments = asr.transcribe(audio_chunk, sample_rate_hz=48_000)
                    if segments and segments[0].text:
                        latest_transcript_text = segments[0].text
                except Exception:
                    pass
                last_asr_time = now

            # Render radar at ~5 Hz
            if now - last_render >= 0.20:
                connected_ids = server.all_phone_ids()
                status_text = (
                    f"Phones: {connected_ids} | Frames: {frames_produced} | "
                    f"Azimuth: {f'{az_deg:.1f} deg' if az_deg else 'aligning...'}"
                )
                lines = [
                    TranscriptLine(
                        track_id=0,
                        text=status_text,
                        language="en",
                        confidence=1.0,
                    ),
                    TranscriptLine(
                        track_id=1,
                        text=f"Transcript: {latest_transcript_text}",
                        language="en",
                        confidence=1.0,
                    ),
                ]
                state = make_state_from_observation(
                    position_xy=pos,
                    sync_stability_us=42.0,
                    started_at_s=started,
                    beamform_active=beamform_active,
                    transcript_lines=lines,
                )
                render_to_terminal(state, force_ascii=force_ascii)
                last_render = now

            await asyncio.sleep(0.01)

    finally:
        if recorder is not None:
            paths = recorder.finalise()
            print(f"\n[RECORDER] Wrote toggle WAV stems:\n  " + "\n  ".join(str(p) for p in paths), flush=True)

        metrics_task.cancel()
        server_task.cancel()
        try:
            await asyncio.gather(server_task, metrics_task, return_exceptions=True)
        except Exception:
            pass

    print("\n==========================================================", flush=True)
    print(f"LIVE RUN COMPLETED: {frames_produced} beamformed frames processed from phones {server.all_phone_ids()}!")
    print("==========================================================", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Live 2-Phone Phased Array Radar")
    parser.add_argument("--seconds", type=float, default=15.0, help="Duration in seconds (-1 for continuous)")
    parser.add_argument("--beamformer", choices=["das", "mvdr"], default="das", help="Beamforming algorithm")
    parser.add_argument("--record-toggle", type=str, default=None, help="Directory to save toggle WAV stems")
    parser.add_argument("--ascii", action="store_true", default=True, help="Force ASCII rendering")
    args = parser.parse_args()

    asyncio.run(
        live_loop(
            duration_s=args.seconds,
            beamformer=args.beamformer,
            record_toggle=args.record_toggle,
            force_ascii=args.ascii,
        )
    )


if __name__ == "__main__":
    main()
