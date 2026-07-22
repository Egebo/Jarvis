# Görev Ajanı (Faz 1) — Tasarım

**Tarih:** 2026-07-22
**Durum:** Onaylandı (Egemen, sesli tasarım oturumu)
**Hedef:** Jarvis'i "sesli komut oyuncağı"ndan gerçek iş yapabilen kişisel asistana ("Claude cowork" hissi) taşımanın ilk fazı.

## Vizyon ve fazlar

Egemen'in istediği üç yetenek (öncelik sırasıyla):

1. **Faz 1 — Görev Ajanı (bu spec):** Çok adımlı işleri baştan sona yapan arka plan ajanı: araştırma + rapor, dosya/klasör işleri, günlük asistanlık temelleri, kod/proje işleri.
2. **Faz 2 — Kalıcı hafıza:** Notlar, yapılacaklar, tercihler, konuşma geçmişi özeti.
3. **Faz 3 — Proaktiflik:** Sabah bröfingi, takip konuları, rutin hatırlatıcılar.

Kısıt: **Claude kotası kullanılmayacak** (Egemen'in kararı) — beyin Gemini ücretsiz katmanında kalır, tasarım kota-bilinçli olmalı.

## Mimari: arka plan görev ajanı (Seçenek B)

Sohbet beyni (flash-lite) hafif ve hızlı kalır; "görev" algılanınca işi arka planda
çalışan TaskAgent'a devreder. Kullanıcı görev sürerken Jarvis'le konuşmaya devam
edebilir. Jarvis görev sırasında yalnızca üç anda konuşur: başlangıç, onay isteği,
bitiş.

### Yeni bileşenler

**`backend/core/agent.py` — TaskAgent**
- Kendi Gemini istemcisi; model: `gemini-3.5-flash` (sohbetten güçlü; sohbet flash-lite'ta kalır).
- Döngü limiti: 25 adım. Limite gelince "elindekiyle özetle ve bitir" talimatı alır.
- Araç seti:
  | Araç | İzin |
  |---|---|
  | `list_dir`, `read_file` | serbest |
  | `write_file` | `Masaüstü/Jarvis-Workspace/` içine serbest; dışarıya onaylı |
  | `delete_path`, `move_path`, `copy_path` | her zaman onaylı |
  | `run_command` (PowerShell) | her zaman onaylı |
  | `web_search` | serbest (mevcut: Gemini grounding → ddgs yedeği) |
- `Jarvis-Workspace` klasörü ilk kullanımda otomatik oluşturulur; raporlar ve üretilen dosyalar varsayılan oraya yazılır.

**`backend/core/task_manager.py` — TaskManager**
- Görev kaydı ve yaşam döngüsü: `running / waiting_approval / done / failed`.
- Görevi `asyncio.Task` olarak başlatır; aynı anda **tek görev** (MVP).
- Olayları sunucuya iletir (başladı / onay istiyor / bitti / hata) — sunucu bunları sesli duyuruya çevirir.

**Sohbet beynine eklenen araçlar:** `start_task(description)`, `task_status()`.
Görev/sohbet ayrımını flash-lite yapar.

### Veri akışı

```
Kullanıcı: "Jarvis, dinozorları araştır, rapor hazırla"
→ Sohbet beyni: start_task("dinozorları araştır...") çağırır
→ Jarvis (anında, sesli): "Başlıyorum efendim, bitince haber veririm"
→ TaskAgent arka planda: web_search → düşün → write_file(rapor) → ...
→ Bitiş: Jarvis sesli özet + "Raporu Jarvis-Workspace'e kaydettim"
```

## Sesli onay mekanizması

- Riskli adımda görev `waiting_approval` durumuna geçer; Jarvis ne yapacağını
  açıkça söyleyip onay ister. PC client'ta takip penceresi açılır (wake word gerekmez).
- Onay bekleyen görev varken gelen ilk konuşma önce onay filtresinden geçer:
  - Onay kelimeleri: **evet, onayla, onaylıyorum, yap, tamam**
  - Red kelimeleri: **hayır, iptal, yapma, dur**
  - Hiçbiri yoksa normal sohbet olarak işlenir; onay sorusu beklemede kalır.
- Zaman aşımı: **120 saniye** cevapsız kalırsa adım otomatik REDDEDİLİR
  (sessizlik asla onay değildir). Ajan "kullanıcı onaylamadı" bilgisiyle o adımı
  atlayıp işi bitirmeye çalışır ve raporda belirtir.

## Hata durumları

- **Gemini 429/503:** 3 deneme, 5/15/30 sn bekleme. Yine olmazsa görev `failed`;
  kısmî sonuç workspace'e kaydedilir ve sesli bildirilir.
- **Araç hataları:** Metin olarak ajana döner; ajan kendini düzeltir (mevcut executor deseni).
- **Sunucu kapanması:** Çalışan görev kaybolur (MVP kabulü; kalıcılık Faz 2'de).

## Test planı

1. **Birim:** Riskli işlem sınıflandırması (hangi araç/yol onay ister) + onay kelime eşleştirici.
2. **Entegrasyon (websocket text):** "workspace'e deneme.txt yaz" görevi — olay sırası
   (start → done) ve dosyanın oluşumu doğrulanır; onaylı senaryo için "masaüstüne yaz"
   görevi ile approval akışı test edilir.
3. **Canlı sesli test:** Araştırma+rapor görevi ve onay gerektiren bir dosya görevi, Egemen'le.

## Uygulama sırasında alınan kararlar (22 Tem 2026, Egemen onaylı)

- **Onay kelime kuralı güncellendi:** Onay kelimeleri (evet/onayla/onaylıyorum/yap/tamam)
  yalnızca 3 kelime ve daha kısa cümlelerde onay sayılır; uzun cümledeki "tamam"
  yanlış onay üretmez. Red kelimeleri her uzunlukta geçerli (yanlış red zararsız).
- **Onaylar yalnızca PC istemcisinden:** `pc-` önekli client kimlikleri dışından
  gelen konuşmalar onay/red sayılmaz (ağdaki başka cihaz kendi görevini onaylayamaz).
  Kalıcı çözüm konuşmacı tanıma fazında.
- **Hassas dosya koruması:** `.env`, `.git`, `.ssh`, anahtar/kimlik dosyaları
  read_file ile okunmaz (prompt injection yoluyla sızdırma riskine karşı).
- **Tek başlangıç anonsu:** "started" olayı sesli okunmaz; başlangıç duyurusu sohbet
  beyninin ilettiği "Başlıyorum efendim" mesajıdır (çift anons önlenir).
- **Kısmî sonuç:** Görev yarıda kalırsa birikmiş içerik `kismi-sonuc-<zaman>.md`
  olarak workspace'e yazılır ve sesli bildirilir (spec'in verdiği söz uygulandı).
- **Takip penceresi mekanizması notu:** Onay sorusundan sonra wake word'süz cevap
  verme, PC client'ın mevcut ses kuyruğu bitişinde açılan takip penceresiyle sağlanır;
  client yeniden yazılırsa bu davranış korunmalı.

## Kapsam dışı (bilinçli)

- Birden fazla eşzamanlı görev, görev kalıcılığı (Faz 2), proaktif tetikleme (Faz 3),
  mobil bildirimler, Claude/başka LLM entegrasyonu.
- **Konuşmacı tanıma (gelecek faz, Egemen'in isteği):** Temel işlevler herkesin
  sesiyle; riskli komutlar ve görev onayları yalnızca Egemen'in ses imzasıyla.
  Onay akışı (waiting_approval) bu doğrulamanın ekleneceği nokta olacak şekilde
  tasarlandı.
