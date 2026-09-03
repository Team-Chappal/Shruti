"""Live 2-Phone Phased Array & Radar via USB/Wi-Fi.

Connects to Phone 0 and Phone 1, drains packets through StreamAligner + DspLoop,
and displays live TDOA/azimuth tracking and audio stats in real time.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

# Add apps/laptop to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "apps" / "laptop"))

from shruti_array.config import AppConfig, ServerConfig
from shruti_array.dsp_loop import DspLoop
from shruti_array.ingest.websocket_server import PacketServer
from shruti_array.render.console_radar import make_state_from_observation, render_to_terminal
from shruti_array.render.overlays import TranscriptLine
from shruti_array.sync.alignment import StreamAligner

async def live_loop(duration_s: float = 15.0):
    cfg = AppConfig.default()
    server = PacketServer(ServerConfig(host="0.0.0.0", port=8765))
    server_task = asyncio.create_task(server.start())

    # Wait briefly for server to bind
    await asyncio.sleep(0.2)
    print("==========================================================", flush=True)
    print("  SHRUTI 2-PHONE REAL-TIME ARRAY PROCESSOR (LIVE DEMO)", flush=True)
    print("==========================================================", flush=True)
    print("Listening on ws://0.0.0.0:8765...", flush=True)
    print("Waiting for audio frames from Phone 0 and Phone 1...", flush=True)

    aligner = StreamAligner()
    aligner.register(phone_id=0, sample_rate_hz=48_000)
    aligner.register(phone_id=1, sample_rate_hz=48_000)

    loop = DspLoop(aligner, geometry=cfg.geometry)
    started = time.time()
    last_render = time.time()
    step_count = 0
    frames_produced = 0

    try:
        while time.time() - started < duration_s:
            # Drain packet queues from all connected phones
            queues = {pid: conn.queue for pid, conn in server._connections.items()}
            popped = loop.pop_from_queues(queues, max_packets_per_phone=8)

            # Step the DSP pipeline
            frame = loop.step()
            if frame is not None:
                frames_produced += 1
                pos = frame.position_xy
                az_deg = frame.azimuth_deg
            else:
                pos = loop.last_position_xy
                az_deg = None

            # Render at ~5 Hz so the console is smooth
            now = time.time()
            if now - last_render >= 0.20:
                step_count += 1
                connected_ids = server.all_phone_ids()
                lines = [
                    TranscriptLine(
                        track_id=0,
                        text=f"Active Phones: {connected_ids} | DSP Frames: {frames_produced} | Azimuth: {f'{az_deg:.1f} deg' if az_deg else 'aligning...'}",
                        language="en",
                        confidence=1.0 if frames_produced > 0 else 0.0,
                    )
                ]
                state = make_state_from_observation(
                    position_xy=pos,
                    sync_stability_us=42.0,
                    started_at_s=started,
                    beamform_active=True,
                    transcript_lines=lines,
                )
                render_to_terminal(state, force_ascii=True)
                last_render = now

            await asyncio.sleep(0.01)

    finally:
        server_task.cancel()
        try:
            await server_task
        except (asyncio.CancelledError, Exception):
            pass

    print("\n==========================================================", flush=True)
    print(f"LIVE RUN COMPLETED: {frames_produced} beamformed frames processed from phones {server.all_phone_ids()}!")
    print("==========================================================", flush=True)

def main():
    dur = 15.0
    if len(sys.argv) > 1:
        dur = float(sys.argv[1])
    asyncio.run(live_loop(dur))

if __name__ == "__main__":
    main()
