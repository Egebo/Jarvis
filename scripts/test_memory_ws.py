"""Kalıcı hafıza websocket entegrasyon testi (sunucu açıkken çalıştır).
Kullanım: ./venv/Scripts/python.exe scripts/test_memory_ws.py
"""
import asyncio
import json
import sys
from pathlib import Path

import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import MEMORY_DIR


async def main():
    client_id = "pc-memory-test"
    async with websockets.connect(
        f"ws://localhost:8765/ws/{client_id}", max_size=10 * 1024 * 1024
    ) as ws:
        await ws.send(json.dumps({"type": "text", "data": "Not al: en sevdigim renk mavi."}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            print(msg["type"], ":", str(msg.get("data"))[:80])
            if msg["type"] == "status" and msg["data"] == "idle":
                break

        await ws.send(json.dumps({"type": "reset"}))
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
            print(msg["type"], ":", str(msg.get("data"))[:80])
            if msg["type"] == "status" and msg["data"] == "reset":
                break

    # reset arka plan özetleme görevini tetikler - tamamlanmasını bekle
    print("Arka plan özetleme bekleniyor (8sn)...")
    await asyncio.sleep(8)

    print("\nMEMORY_DIR:", MEMORY_DIR)
    if MEMORY_DIR.exists():
        for p in sorted(MEMORY_DIR.rglob("*.md")):
            print(" -", p.relative_to(MEMORY_DIR))
    else:
        print("UYARI: MEMORY_DIR henüz oluşmadı")


asyncio.run(main())
