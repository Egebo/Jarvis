"""
Skill Executor — Jarvis'in araçlarını çalıştırır
Brain'den gelen araç çağrılarını gerçek aksiyonlara dönüştürür.
"""
import asyncio
import psutil
import subprocess
import platform
from datetime import datetime, timedelta
from typing import Any, Dict


class SkillExecutor:
    """
    Gemini'nin function-call çağrılarını karşılayan executor.
    Her metod bir 'skill'e karşılık gelir.
    """

    def __init__(self):
        self._search_client = None
        self.task_manager = None   # server.py lifespan'de set edilir
        self.memory_store = None   # server.py lifespan'de set edilir
        self.reminder_store = None   # server.py lifespan'de set edilir

    async def execute(self, tool_name: str, tool_input: Dict) -> str:
        handlers = {
            "web_search": self.web_search,
            "open_application": self.open_application,
            "open_url": self.open_url,
            # "run_command": self.run_command,  # BİLİNÇLİ KAPALI: STT yanlış
            # anlarsa tehlikeli komut çalıştırabilir. Açmadan önce sesli onay
            # mekanizması eklenmeli (Egemen'in isteği, 17 Tem 2026).
            "system_info": self.system_info,
            "set_reminder": self.set_reminder,
            "list_reminders": self.list_reminders,
            "cancel_reminder": self.cancel_reminder,
            "get_weather": self.get_weather,
            "control_media": self.control_media,
            "get_now_playing": self.get_now_playing,
            "take_screenshot": self.take_screenshot,
            "start_task": self.start_task,
            "task_status": self.task_status,
            "remember": self.remember,
            "add_todo": self.add_todo,
            "complete_todo": self.complete_todo,
            "list_todos": self.list_todos,
            "recall": self.recall,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return f"Bilinmeyen araç: {tool_name}"

        try:
            return await handler(**tool_input)
        except Exception as e:
            return f"Araç hatası ({tool_name}): {str(e)}"

    # ─── Görev Ajanı köprüsü ─────────────────────────────────────────────────
    async def start_task(self, description: str) -> str:
        if self.task_manager is None:
            return "Görev sistemi henüz hazır değil."
        from backend.config import WORKSPACE_DIR
        from backend.core.agent import TaskAgent
        from backend.skills.file_tools import FileTools

        def runner_factory(tm):
            agent = TaskAgent(description, FileTools(WORKSPACE_DIR), executor=self,
                              approval_cb=tm.request_approval)
            return agent.run()

        return self.task_manager.start(description, runner_factory)

    async def task_status(self) -> str:
        if self.task_manager is None:
            return "Görev sistemi henüz hazır değil."
        return self.task_manager.status_text()

    # ─── Kalıcı Hafıza köprüsü ─────────────────────────────────────────────────
    async def remember(self, fact: str, category: str = "hakkimda") -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.save_fact(category, fact)

    async def add_todo(self, item: str) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.add_todo(item)

    async def complete_todo(self, item: str) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.complete_todo(item)

    async def list_todos(self) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.read_todos()

    async def recall(self, query: str) -> str:
        if self.memory_store is None:
            return "Hafıza sistemi henüz hazır değil."
        return self.memory_store.search_digests(query)

    # ─── Web Arama ───────────────────────────────────────────────────────────
    async def web_search(self, query: str) -> str:
        """
        Gemini'nin Google Search grounding özelliğiyle GERÇEK web araması.
        (Grounding aracı function-calling ile aynı istekte kullanılamadığından
        ayrı bir Gemini çağrısı olarak yapılır; sonucu ana beyne metin döner.)
        """
        from google import genai
        from google.genai import types
        from backend.config import GEMINI_API_KEY, GEMINI_MODEL

        try:
            if self._search_client is None:
                self._search_client = genai.Client(api_key=GEMINI_API_KEY)

            response = await self._search_client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=(
                    "Google'da araştır ve bulduklarını Türkçe, kaynak isimleriyle "
                    f"birlikte kısa ve öz özetle: {query}"
                ),
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                ),
            )
            return response.text or f"'{query}' için sonuç bulunamadı."
        except Exception as e:
            # Grounding kotası dolduysa (ücretsiz katmanda günlük limit düşük)
            # DuckDuckGo ile gerçek arama sonuçlarına düş
            return await self._ddg_search(query, reason=str(e)[:80])

    async def _ddg_search(self, query: str, reason: str = "") -> str:
        """Yedek arama: DuckDuckGo gerçek sonuç listesi (kota gerektirmez)."""
        def _search():
            from ddgs import DDGS
            return list(DDGS().text(query, region="tr-tr", max_results=5))

        try:
            results = await asyncio.get_event_loop().run_in_executor(None, _search)
            if not results:
                return f"'{query}' için sonuç bulunamadı."
            lines = [f"- {r['title']}: {r['body']}" for r in results]
            return "Arama sonuçları:\n" + "\n".join(lines)
        except Exception as e:
            return f"Arama hatası (yedek de başarısız): {e} | ilk hata: {reason}"

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
                # 'start' kullan: uygulamayı PATH'te olmasa da App Paths
                # kaydından bulur (chrome, spotify vs. PATH'te değildir)
                proc = subprocess.run(f'start "" {cmd}', shell=True,
                                      capture_output=True, text=True, timeout=10)
                if proc.returncode != 0:
                    hata = (proc.stderr or "").strip()
                    return f"❌ {name} açılamadı: {hata or 'uygulama bulunamadı'}"
            elif system == "Darwin":
                subprocess.Popen(["open", "-a", name])
            else:
                subprocess.Popen(cmd.split())
            return f"✅ {name} açıldı."
        except Exception as e:
            return f"❌ {name} açılamadı: {e}"

    # ─── URL Açma ────────────────────────────────────────────────────────────
    async def open_url(self, url: str) -> str:
        import webbrowser
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return f"✅ Tarayıcıda açıldı: {url}"

    # ─── Genel PowerShell Komutu ─────────────────────────────────────────────
    async def run_command(self, command: str) -> str:
        """
        Jarvis'in genel PC yönetim aracı: ses/parlaklık ayarı, dosya işlemleri,
        pencere/işlem yönetimi... Egemen'in kendi bilgisayarında, kendi sesli
        komutuyla tetiklenir.
        """
        print(f"💻 PowerShell: {command}")
        try:
            proc = await asyncio.create_subprocess_exec(
                "powershell", "-NoProfile", "-NonInteractive", "-Command", command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(proc.communicate(), timeout=30)
            output = out.decode("utf-8", errors="ignore").strip()
            error = err.decode("utf-8", errors="ignore").strip()
            if proc.returncode != 0:
                return f"Komut hatası (kod {proc.returncode}): {error[:300]}"
            return output[:500] if output else "✅ Komut çalıştı (çıktı yok)."
        except asyncio.TimeoutError:
            return "Komut 30 saniyede bitmedi, iptal edildi."
        except Exception as e:
            return f"Komut çalıştırılamadı: {e}"

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

    # ─── Hatırlatıcılar ──────────────────────────────────────────────────────
    async def set_reminder(self, message: str, minutes: int = None, daily_at: str = None) -> str:
        if self.reminder_store is None:
            return "Hatırlatıcı sistemi henüz hazır değil."
        if minutes and daily_at:
            return "Hem 'minutes' hem 'daily_at' verilemez, sadece birini kullan."
        now = datetime.now()
        if daily_at:
            try:
                hour, minute = map(int, daily_at.split(":"))
                fire_at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            except ValueError:
                return "Saat formatı HH:MM olmalı (örn. '09:00')."
            if fire_at <= now:
                fire_at += timedelta(days=1)
            return self.reminder_store.add(message, fire_at, recurrence="daily")
        if not minutes:
            return "Ne zaman hatırlatacağımı belirtmelisin (dakika veya saat)."
        return self.reminder_store.add(message, now + timedelta(minutes=minutes))

    async def list_reminders(self) -> str:
        if self.reminder_store is None:
            return "Hatırlatıcı sistemi henüz hazır değil."
        return self.reminder_store.list_active()

    async def cancel_reminder(self, query: str) -> str:
        if self.reminder_store is None:
            return "Hatırlatıcı sistemi henüz hazır değil."
        return self.reminder_store.cancel(query)

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

    # ─── Çalan Medya + Açık Pencereler ───────────────────────────────────────
    async def get_now_playing(self) -> str:
        """Windows medya oturumundan çalan içeriği + açık pencere başlıklarını okur."""
        parts = []
        try:
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager as MediaManager,
            )
            mgr = await MediaManager.request_async()
            session = mgr.get_current_session()
            if session:
                props = await session.try_get_media_properties_async()
                app = (session.source_app_user_model_id or "").split("!")[0].split("_")[0]
                info = props.title or "(başlık yok)"
                if props.artist:
                    info += f" - {props.artist}"
                parts.append(f"Çalan medya: {info} (uygulama: {app})")
            else:
                parts.append("Şu an sistemde çalan medya görünmüyor.")
        except Exception as e:
            parts.append(f"Medya bilgisi alınamadı: {e}")

        try:
            import pygetwindow as gw
            titles = [t for t in gw.getAllTitles() if t.strip()][:15]
            if titles:
                parts.append("Açık pencereler: " + " | ".join(titles))
        except Exception:
            pass

        return "\n".join(parts)

    # ─── Ekran Görüntüsü ─────────────────────────────────────────────────────
    async def take_screenshot(self) -> dict:
        """
        Ekran görüntüsü alır ve görseli modele iletilecek formatta döndürür.
        Dönen dict brain.py tarafından Gemini'ye inline görsel olarak eklenir.
        """
        import pyautogui
        import base64
        import io

        loop = asyncio.get_event_loop()
        screenshot = await loop.run_in_executor(None, pyautogui.screenshot)

        # Token/boyut tasarrufu: genişliği 1280px'e indir, JPEG'e çevir
        max_width = 1280
        if screenshot.width > max_width:
            ratio = max_width / screenshot.width
            screenshot = screenshot.resize((max_width, int(screenshot.height * ratio)))

        buf = io.BytesIO()
        screenshot.convert("RGB").save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        return {
            "text": "Ekran görüntüsü alındı, görsel ekte.",
            "image_b64": img_b64,
            "mime_type": "image/jpeg",
        }
