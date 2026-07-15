"""
Skill Executor — Jarvis'in araçlarını çalıştırır
Brain'den gelen araç çağrılarını gerçek aksiyonlara dönüştürür.
"""
import asyncio
import psutil
import subprocess
import platform
from datetime import datetime
from typing import Any, Dict


class SkillExecutor:
    """
    Gemini'nin function-call çağrılarını karşılayan executor.
    Her metod bir 'skill'e karşılık gelir.
    """

    async def execute(self, tool_name: str, tool_input: Dict) -> str:
        handlers = {
            "web_search": self.web_search,
            "open_application": self.open_application,
            "system_info": self.system_info,
            "set_reminder": self.set_reminder,
            "get_weather": self.get_weather,
            "control_media": self.control_media,
            "take_screenshot": self.take_screenshot,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return f"Bilinmeyen araç: {tool_name}"

        try:
            return await handler(**tool_input)
        except Exception as e:
            return f"Araç hatası ({tool_name}): {str(e)}"

    # ─── Web Arama ───────────────────────────────────────────────────────────
    async def web_search(self, query: str) -> str:
        import httpx
        try:
            # DuckDuckGo Instant Answer API (ücretsiz)
            url = "https://api.duckduckgo.com/"
            params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url, params=params)
                data = r.json()

            abstract = data.get("AbstractText", "")
            answer = data.get("Answer", "")
            related = [r["Text"] for r in data.get("RelatedTopics", [])[:3] if "Text" in r]

            result = ""
            if answer:
                result += f"Cevap: {answer}\n"
            if abstract:
                result += f"Özet: {abstract}\n"
            if related:
                result += "İlgili: " + " | ".join(related)

            return result or f"'{query}' için sonuç bulunamadı."
        except Exception as e:
            return f"Arama hatası: {e}"

    # ─── Uygulama Açma ───────────────────────────────────────────────────────
    async def open_application(self, name: str, args: str = "") -> str:
        system = platform.system()

        # Yaygın uygulama isimleri → komutlar
        app_map = {
            "chrome": "chrome" if system != "Darwin" else "open -a 'Google Chrome'",
            "google chrome": "chrome",
            "firefox": "firefox",
            "spotify": "spotify",
            "vs code": "code",
            "vscode": "code",
            "visual studio code": "code",
            "notepad": "notepad",
            "calculator": "calc",
            "hesap makinesi": "calc",
            "dosya gezgini": "explorer",
            "file explorer": "explorer",
            "terminal": "cmd" if system == "Windows" else "terminal",
            "görev yöneticisi": "taskmgr",
            "task manager": "taskmgr",
        }

        cmd = app_map.get(name.lower(), name)
        if args:
            cmd += f" {args}"

        try:
            if system == "Windows":
                subprocess.Popen(cmd, shell=True)
            elif system == "Darwin":
                subprocess.Popen(["open", "-a", name])
            else:
                subprocess.Popen(cmd.split())
            return f"✅ {name} açıldı."
        except Exception as e:
            return f"❌ {name} açılamadı: {e}"

    # ─── Sistem Bilgisi ──────────────────────────────────────────────────────
    async def system_info(self, metric: str = "all") -> str:
        info = {}

        if metric in ("cpu", "all"):
            info["CPU"] = f"%{psutil.cpu_percent(interval=1):.1f}"

        if metric in ("memory", "all"):
            mem = psutil.virtual_memory()
            info["RAM"] = f"%{mem.percent:.1f} ({mem.used // 1024**3}GB / {mem.total // 1024**3}GB)"

        if metric in ("battery", "all"):
            bat = psutil.sensors_battery()
            if bat:
                status = "şarjda" if bat.power_plugged else "pilde"
                info["Pil"] = f"%{bat.percent:.0f} ({status})"
            else:
                info["Pil"] = "Bilgi yok"

        if metric in ("disk", "all"):
            disk = psutil.disk_usage("/")
            info["Disk"] = f"%{disk.percent:.1f} ({disk.used // 1024**3}GB / {disk.total // 1024**3}GB)"

        if metric in ("network", "all"):
            net = psutil.net_io_counters()
            info["Ağ"] = f"↓{net.bytes_recv // 1024**2}MB ↑{net.bytes_sent // 1024**2}MB"

        return " | ".join([f"{k}: {v}" for k, v in info.items()])

    # ─── Hatırlatıcı ─────────────────────────────────────────────────────────
    async def set_reminder(self, message: str, minutes: int) -> str:
        async def _remind():
            await asyncio.sleep(minutes * 60)
            # Basit bildirim — platform'a göre değişir
            system = platform.system()
            if system == "Windows":
                subprocess.run(
                    ["powershell", "-Command",
                     f'Add-Type -AssemblyName System.Windows.Forms; '
                     f'[System.Windows.Forms.MessageBox]::Show("{message}", "Jarvis Hatırlatıcı")'],
                    capture_output=True
                )
            elif system == "Darwin":
                subprocess.run(["osascript", "-e",
                                f'display notification "{message}" with title "Jarvis"'])
            else:
                subprocess.run(["notify-send", "Jarvis", message])

        asyncio.create_task(_remind())
        return f"✅ {minutes} dakika sonra hatırlatacağım: '{message}'"

    # ─── Hava Durumu ─────────────────────────────────────────────────────────
    async def get_weather(self, city: str = "Istanbul") -> str:
        import httpx
        try:
            # wttr.in ücretsiz API
            url = f"https://wttr.in/{city}?format=j1&lang=tr"
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                data = r.json()

            current = data["current_condition"][0]
            temp = current["temp_C"]
            feels = current["FeelsLikeC"]
            desc = current["lang_tr"][0]["value"] if "lang_tr" in current else current["weatherDesc"][0]["value"]
            humidity = current["humidity"]
            wind = current["windspeedKmph"]

            return (f"{city}: {desc}, {temp}°C (hissedilen {feels}°C), "
                    f"Nem %{humidity}, Rüzgar {wind}km/s")
        except Exception as e:
            return f"Hava durumu alınamadı: {e}"

    # ─── Medya Kontrol ───────────────────────────────────────────────────────
    async def control_media(self, action: str) -> str:
        import pyautogui
        import time

        key_map = {
            "play": "playpause",
            "pause": "playpause",
            "next": "nexttrack",
            "previous": "prevtrack",
            "volume_up": "volumeup",
            "volume_down": "volumedown",
            "mute": "volumemute",
        }

        key = key_map.get(action)
        if not key:
            return f"Bilinmeyen medya komutu: {action}"

        pyautogui.press(key)
        return f"✅ {action} yapıldı."

    # ─── Ekran Görüntüsü ─────────────────────────────────────────────────────
    async def take_screenshot(self) -> str:
        import pyautogui
        import base64
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            tmp_path = f.name

        screenshot = pyautogui.screenshot()
        screenshot.save(tmp_path)

        with open(tmp_path, "rb") as f:
            img_data = base64.b64encode(f.read()).decode()
        os.unlink(tmp_path)

        # Base64 görseli modele gönder (vision)
        return f"[SCREENSHOT_B64:{img_data[:100]}...]"  # truncated for brevity
