# 🤖 JARVIS: Kişisel Yapay Zeka Asistanı

Iron Man'deki JARVIS'ten ilham alınarak yapılmış, sesle aktifleşen kişisel AI asistan.

## Mimari

```
┌─────────────────────────────────────────────────────┐
│                    JARVIS SİSTEMİ                   │
│                                                     │
│   PC Client          Backend Server    Mobile App   │
│   ──────────         ──────────────   ──────────   │
│   • Wake word   ─→   • FastAPI        • React      │
│   • Mikrofon         • Whisper STT      Native      │
│   • Hoparlör    ←─   • Gemini API    • iOS/Android  │
│                      • TTS Engine                   │
│                      • Skills/Tools                 │
└─────────────────────────────────────────────────────┘
```

## Hızlı Başlangıç

### 1. Kurulum
```bash
# scripts\setup.bat çalıştırın (Windows)
# VEYA manuel:
python -m venv venv
venv\Scripts\activate
pip install -r backend\requirements.txt
```

### 2. API Anahtarı
`.env.example` dosyasını `.env` olarak kopyalayın ve doldurun:
```
GEMINI_API_KEY=your_gemini_api_key_here
```
Anahtarı [Google AI Studio](https://aistudio.google.com/apikey) üzerinden alabilirsiniz.

### 3. Sunucuyu Başlatın
```bash
scripts\start_server.bat
# VEYA:
python -m backend.server
```

### 4. PC Client (Sesli)
```bash
scripts\start_pc_client.bat
# "Jarvis" dediğinizde aktifleşir
```

### 4b. Metin Modu (Test)
```bash
scripts\start_text_mode.bat
```

### 5. Mobil Uygulama
```bash
cd mobile
npm install
# Android:
npx react-native run-android
# iOS:
npx react-native run-ios
```
Ayarlar ekranından PC'nizin yerel IP'sini girin.

---

## Özellikler

| Özellik | Durum |
|---------|-------|
| Wake word algılama | ✅ |
| Türkçe/İngilizce STT | ✅ |
| Gemini AI beyin | ✅ |
| Metin-ses (TTS) | ✅ |
| Web arama | ✅ |
| Uygulama açma | ✅ |
| Sistem bilgisi (CPU, RAM, pil) | ✅ |
| Hava durumu | ✅ |
| Hatırlatıcı | ✅ |
| Medya kontrolü | ✅ |
| Ekran görüntüsü | ✅ |
| PC client | ✅ |
| Mobil (React Native) | ✅ |
| Konuşma hafızası | ✅ |
| Arka plan görev ajanı (araştırma+rapor, dosya işleri) | ✅ |
| Riskli adımlarda sesli onay | ✅ |

## Gelişmiş TTS

Varsayılan olarak `pyttsx3` (ücretsiz, offline) kullanılır.
Yüksek kalite için ElevenLabs:
```
ELEVENLABS_API_KEY=your_key
TTS_ENGINE=elevenlabs
```

## Görev Ajanı

"Jarvis, dinozorları araştır ve masaüstündeki klasöre rapor yaz" gibi çok adımlı
işler arka planda çalışan görev ajanına devredilir; sen bu sırada Jarvis'le
konuşmaya devam edebilirsin. Çıktılar `Masaüstü/Jarvis-Workspace/` klasörüne yazılır.
Riskli adımlarda (silme, taşıma, workspace dışına yazma, komut çalıştırma) Jarvis
sesli onay ister; kısa bir "evet" veya "hayır" yeterlidir (yalnızca PC istemcisinden).
Detaylı tasarım: `docs/superpowers/specs/2026-07-22-gorev-ajani-design.md`

## Yeni Yetenek Eklemek

`backend/skills/executor.py` dosyasına yeni bir metod ekleyin,
ardından `backend/core/brain.py` içindeki `_define_tools()` listesine tanımını ekleyin.

## Proje Yapısı

```
Jarvis/
├── backend/
│   ├── core/
│   │   ├── brain.py      # Gemini AI entegrasyonu
│   │   ├── memory.py     # Konuşma hafızası
│   │   ├── stt.py        # Whisper STT
│   │   └── tts.py        # Ses sentezi
│   ├── skills/
│   │   └── executor.py   # Araçlar (hava, arama, sistem...)
│   ├── server.py         # FastAPI + WebSocket sunucu
│   ├── config.py         # Tüm ayarlar
│   └── requirements.txt
├── pc-client/
│   └── jarvis_pc.py      # Windows masaüstü client
├── mobile/
│   ├── App.tsx
│   └── src/
│       ├── screens/      # Ana ekran, ayarlar
│       └── services/     # WebSocket servisi
├── scripts/
│   ├── setup.bat
│   ├── start_server.bat
│   └── start_pc_client.bat
└── .env.example
```

## Lisans

Bu proje MIT lisansi ile lisanslanmistir, detaylar icin LICENSE dosyasina bakabilirsiniz.

## Gelistirici

Egemen Bozca tarafindan gelistirilmektedir.
Portfolyo: https://egebo.github.io | GitHub: https://github.com/Egebo
