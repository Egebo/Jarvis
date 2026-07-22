"""Görev ajanı websocket entegrasyon testi (sunucu açıkken çalıştır).
Kullanım: ./venv/Scripts/python.exe scripts/test_task_ws.py
"""
import asyncio, json, sys
import websockets


async def main():
    async with websockets.connect("ws://localhost:8765/ws/task-test",
                                  max_size=10 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"type": "text",
            "data": "Görev: workspace'e deneme.txt adında icinde 'merhaba' yazan bir dosya olustur."}))
        seen = []
        while True:
            msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
            if msg["type"] == "task_update":
                seen.append(msg["data"]["event"])
                print("OLAY:", msg["data"]["event"], "|", msg["data"]["message"][:80])
                if msg["data"]["event"] in ("done", "failed"):
                    break
            elif msg["type"] == "response":
                print("YANIT:", msg["data"][:80])
    print("Olay sirasi:", seen)
    assert seen[0] == "started" and seen[-1] == "done", "Olay sirasi hatali!"
    print("ENTEGRASYON OK")

asyncio.run(main())
