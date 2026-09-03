"""Test USB round-trip connection with two phones.
Listens on ws://127.0.0.1:8765, collects audio frames, and reports stats per phone.
"""
from __future__ import annotations

import asyncio
import sys
import time
from collections import defaultdict
from pathlib import Path

# Add apps/laptop to sys.path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / "apps" / "laptop"))

import websockets
from shruti_array.protocol import (
    HEADER_SIZE,
    CRC_SIZE,
    MAX_PAYLOAD_SAMPLES,
    verify_packet,
    PacketType,
)

MAX_PACKET_BYTES = HEADER_SIZE + MAX_PAYLOAD_SAMPLES * 2 + CRC_SIZE

stats = defaultdict(lambda: {"received": 0, "verified": 0, "audio": 0, "heartbeat": 0, "bytes": 0, "last_seq": -1})

async def handler(ws):
    remote = ws.remote_address
    print(f"[SERVER] Connection opened from {remote}", flush=True)
    try:
        async for msg in ws:
            if not isinstance(msg, bytes):
                continue
            raw = msg
            if len(raw) < HEADER_SIZE + CRC_SIZE:
                continue
            try:
                hdr = verify_packet(raw)
            except Exception as e:
                print(f"[SERVER] CRC or Header failure from {remote}: {e}", flush=True)
                continue
            pid = hdr.phone_id
            st = stats[pid]
            st["received"] += 1
            st["verified"] += 1
            st["bytes"] += len(raw)
            st["last_seq"] = hdr.sequence
            if hdr.packet_type == PacketType.AUDIO_FRAME:
                st["audio"] += 1
            elif hdr.packet_type == PacketType.HEARTBEAT:
                st["heartbeat"] += 1

            if st["received"] % 25 == 1:
                print(
                    f"[AUDIO FRAME] Phone {pid}: seq={hdr.sequence}, type={hdr.packet_type.name}, "
                    f"samples={hdr.sample_count}, total_pkts={st['received']}",
                    flush=True,
                )
    except Exception as e:
        print(f"[SERVER] Connection {remote} closed: {e}", flush=True)

async def main():
    print("[SERVER] Starting test listener on ws://0.0.0.0:8765 ...", flush=True)
    async with websockets.serve(handler, "0.0.0.0", 8765, max_size=MAX_PACKET_BYTES):
        print("[SERVER] Ready! Waiting for phone connections for 20 seconds...", flush=True)
        await asyncio.sleep(20)

    print("\n--- TEST SUMMARY ---", flush=True)
    if not stats:
        print("FAIL: No packets received from any phone.", flush=True)
        sys.exit(1)
    for pid, st in sorted(stats.items()):
        print(
            f"Phone {pid}: Verified={st['verified']} pkts (Audio={st['audio']}, "
            f"Heartbeat={st['heartbeat']}), LastSeq={st['last_seq']}, TotalBytes={st['bytes']}",
            flush=True,
        )
    if len(stats) >= 2:
        print(f"SUCCESS: Successfully received and verified audio streams from {len(stats)} phones!", flush=True)
    else:
        print(f"PARTIAL: Received data from {len(stats)} phone(s).", flush=True)

if __name__ == "__main__":
    asyncio.run(main())
