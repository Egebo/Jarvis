"""
Jarvis'i sistem tepsisinde (saat yanındaki gizli simgeler alanı) çalıştıran
başlatıcı. Sunucuyu ve PC client'ı görünür konsol penceresi olmadan arka
planda subprocess olarak başlatır; tepsi ikonundan web arayüzü açılabilir,
her şey tek tıkla durdurulabilir.
"""
import os
import subprocess
import sys
import webbrowser
from pathlib import Path

import pystray
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
from backend.config import JARVIS_DATA_DIR  # noqa: E402

PYTHON = REPO_ROOT / "venv" / "Scripts" / "python.exe"
WEB_URL = "http://localhost:8765"
LOGS_DIR = JARVIS_DATA_DIR / "logs"

# subprocess.CREATE_NO_WINDOW - sadece Windows'ta var, konsol penceresi
# açtırmadan arka planda çalıştırmak için gerekli.
CREATE_NO_WINDOW = 0x08000000

_processes: list[subprocess.Popen] = []
_log_files: list = []


def _start(args: list[str], cwd: Path, log_name: str) -> subprocess.Popen:
    """Bir Python scriptini konsol penceresi açmadan arka planda başlatır.
    stdout/stderr, konsol gizlendiği için hiçbir yerde görünmeyeceğinden
    Documents/Jarvis/logs/ altına yönlendirilir - bir şey patlarsa sessizce
    kaybolmasın diye."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_file = open(LOGS_DIR / log_name, "a", encoding="utf-8")
    _log_files.append(log_file)
    # Konsolsuz (pythonw) çalışırken Python stdout için Türkçe Windows'un
    # varsayılan codepage'ini (cp1254) kullanıyor - emoji/özel karakter
    # print()'leri UnicodeEncodeError ile sunucuyu çökertiyordu. UTF-8'e
    # zorlanıyor.
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.Popen(
        [str(PYTHON), *args],
        cwd=str(cwd),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=CREATE_NO_WINDOW,
        env=env,
    )
    _processes.append(proc)
    return proc


def _make_icon_image() -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((2, 2, 61, 61), fill=(0, 150, 255, 255))
    draw.text((24, 16), "J", fill=(0, 0, 0, 255))
    return img


def _open_web(icon, item):
    webbrowser.open(WEB_URL)


def _quit(icon, item):
    for proc in _processes:
        proc.terminate()
    for log_file in _log_files:
        log_file.close()
    icon.stop()


def main():
    _start(["-m", "backend.server"], cwd=REPO_ROOT, log_name="server.log")
    _start(["pc-client/jarvis_pc.py"], cwd=REPO_ROOT, log_name="pc_client.log")

    menu = pystray.Menu(
        pystray.MenuItem("Jarvis çalışıyor", None, enabled=False),
        pystray.MenuItem("Web arayüzünü aç", _open_web, default=True),
        pystray.MenuItem("Durdur ve çık", _quit),
    )
    icon = pystray.Icon("jarvis", _make_icon_image(), "Jarvis", menu)
    icon.run()


if __name__ == "__main__":
    main()
