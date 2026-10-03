# Law Station Content Agent

Agent yang membuat konten carousel hukum (gaya hitam-emas Law Station) secara otomatis:

**riset web → draft → cek fakta ke sumber resmi → render slide PNG → caption + hashtag + daftar sumber**

Hasil akhirnya tinggal kamu cek dan upload sendiri ke TikTok / Instagram.

## Gratis atau berbayar?

| Bagian | Biaya |
|---|---|
| Render slide (Python + Pillow), pengiriman Telegram, semua kode | Gratis |
| Riset + penulisan otomatis lewat API Claude (`plan`, `today`, `make`) | **Berbayar per pemakaian**: token (Sonnet 5.5: $2 / $10 per juta token masuk / keluar) + web search $10 per 1.000 pencarian |

Perkiraan kasar $0,2-0,7 per konten (estimasi, belum diukur; `--no-verify` lebih murah tapi kurang aman).

### Cara 100% gratis

**A. Lewat chat Claude (tanpa install apa pun).** Kirim "buatkan konten untuk <topik atau tanggal>" dan lampirkan `agent.py`
(plus `plan.json`). Claude riset, cek fakta, render slide PNG + caption, kamu tinggal download. Biaya hanya kuota paket Claude-mu.
Lampirkan ulang `agent.py` di setiap chat baru.

**B. Di komputer sendiri, mode prompt (tanpa API key).** Hanya butuh `pip install pillow`.
1. `python agent.py prompt` (otomatis mengambil topik hari ini dari `plan.json`)
2. Tempel `prompts/..._1_draft.txt` ke chat AI gratis yang punya pencarian web (Claude, Gemini, ChatGPT)
3. Setelah AI membalas, kirim isi `prompts/..._2_cekfakta.txt` di chat yang sama
4. Simpan balasan terakhir AI ke `balasan.txt`, lalu `python agent.py render balasan.txt`

Rencana mingguan: `python agent.py prompt --plan`, simpan balasannya, lalu `python agent.py plan --from-file balasan.txt`.

**Kenapa bukan API gratis seperti Gemini?** Tier gratisnya ada, tetapi laporan pengukuran September 2026 menunjukkan kuota sekitar
20 permintaan/hari per model dan Google Search grounding gratis tidak bisa diandalkan (Google juga tidak lagi menerbitkan angka kuotanya).
Tanpa pencarian web, model bisa memakai aturan usang atau salah pasal, jadi tidak cocok untuk konten hukum.

## Isi folder

| File | Fungsi |
|---|---|
| `agent.py` | Seluruh agent (satu file) |
| `plan.json` | Rencana konten 3-9 Oktober 2026 (bisa diedit) |
| `requirements.txt` | Library yang dibutuhkan |
| `history.json` | Dibuat otomatis: topik yang sudah dibuat, supaya tidak diulang |
| `output/` | Dibuat otomatis: satu folder per konten |
| `prompts/` | Dibuat otomatis (mode gratis): prompt siap-tempel untuk chat AI |

## Setup (±5 menit)

1. Python 3.10 atau lebih baru, lalu:
   ```
   pip install -r requirements.txt
   ```
   (Mode gratis B hanya butuh `pip install pillow`.)
2. Hanya untuk mode berbayar (API): buat file `.env` di folder yang sama:
   ```
   ANTHROPIC_API_KEY=sk-ant-xxxx
   # opsional
   CLAUDE_MODEL=claude-sonnet-5-5
   TELEGRAM_BOT_TOKEN=xxxx
   TELEGRAM_CHAT_ID=xxxx
   SLIDE_SIZE=1080x1350
   ```
3. Font (opsional tapi sangat disarankan agar mirip brand): buat folder `fonts/` lalu taruh
   `title.ttf` (serif tebal, mis. Playfair Display Bold atau Cinzel Bold) dan `body.ttf` (mis. Inter atau Lato Regular).
   Tanpa itu, agent memakai font sistem.
4. Foto latar cover (opsional): taruh gambar gedung MK / palu hakim di `assets/backgrounds/`.
   Agent otomatis menggelapkannya agar teks tetap terbaca.
5. Tes tampilan tanpa biaya API:
   ```
   python agent.py demo
   ```
   Buka `output/demo/` dan cek slide-nya.

## Pemakaian

| Perintah | Hasil |
|---|---|
| `python agent.py plan` | Rencana 7 hari ke depan (riset berita/regulasi terbaru) → `plan.json` |
| `python agent.py today` | Konten untuk hari ini sesuai `plan.json` |
| `python agent.py today --date 2026-10-05` | Konten untuk tanggal tertentu |
| `python agent.py make "topik bebas"` | Konten untuk topik yang kamu tentukan |
| `python agent.py make "topik" --format mitos-fakta` | Format lain: `carousel`, `mitos-fakta`, `kuis` |
| `python agent.py render output/xxx/content.json` | Render ulang setelah kamu edit teks di `content.json` |
| `python agent.py prompt` | **Gratis**: tulis prompt siap-tempel untuk chat AI (topik dari `plan.json`, atau `prompt "topik"`) |
| `python agent.py render balasan.txt` | **Gratis**: ubah balasan chat AI (yang berisi tag `<json>`) menjadi slide + caption |
| `python agent.py prompt --plan` | **Gratis**: prompt rencana mingguan; impor hasilnya dengan `plan --from-file balasan.txt` |

Tambahan: `--telegram` (kirim slide + caption ke Telegram), `--no-verify` (lewati cek fakta, lebih murah tapi kurang aman).

Setiap konten menghasilkan folder `output/TANGGAL_judul/` berisi:
`slide_01.png ...`, `caption.txt`, `sources.md` (dasar hukum, catatan cek manual, halaman yang dibaca agent), dan `content.json`.

## Otomatis (jadwal)

Linux/Mac (`crontab -e`), jam server WIB:

```
0 6 * * *  cd /path/law-station-agent && python3 agent.py today --telegram >> agent.log 2>&1
0 20 * * 5 cd /path/law-station-agent && python3 agent.py plan >> agent.log 2>&1
```

Jika server memakai UTC, 06:00 WIB = 23:00 UTC hari sebelumnya. Di Windows pakai Task Scheduler dengan perintah yang sama.

Alur harian: pagi konten terkirim ke Telegram → cek (2 menit) → upload jam 19.00-21.00 WIB.

## Cek sebelum posting (wajib)

1. Baca `sources.md`, terutama bagian **Cek manual sebelum posting**.
2. Buka 1-2 sumber resmi dan cocokkan nomor aturan, pasal, dan tanggal.
3. Pastikan teks di slide terbaca di layar HP dan tidak terpotong.
4. Biarkan slide terakhir (disclaimer "edukasi, bukan nasihat hukum") tetap ada.

Agent diinstruksikan untuk tidak mengarang nomor pasal/putusan, tetapi model tetap bisa keliru atau memakai sumber yang salah.
Konten hukum yang salah kutip merusak kredibilitas akun, jadi langkah cek manual jangan dilewati.

## Kustomisasi

- Brand (nama, tagline, handle, CTA, disclaimer): blok `BRAND` di atas `agent.py`.
- Warna: konstanta `GOLD`, `GOLD_LIGHT`, `GOLD_DARK`, `WHITE`.
- Gaya bahasa dan aturan akurasi: fungsi `system_prompt()`.
- Pelajaran dari performa akun yang dipakai saat menyusun rencana: `ACCOUNT_INSIGHT`.
- Rasio slide: `SLIDE_SIZE=1080x1920` di `.env` bila ingin 9:16.
- Tanpa kode: isi `system_prompt()` dan `SCHEMA` bisa ditempel ke Claude Project untuk dipakai manual.

## Kenapa tidak auto-post?

Posting otomatis ke TikTok/Instagram butuh API resmi (TikTok perlu audit aplikasi; Instagram perlu akun Business dan Graph API).
Pengiriman ke Telegram lebih praktis: slide tinggal disimpan ke galeri lalu diupload.

## Masalah umum

- **Teks tampil dengan font standar**: taruh `fonts/title.ttf` dan `fonts/body.ttf`.
- **Error model / web search**: ganti `CLAUDE_MODEL` di `.env`, atau `SEARCH_TOOL` bila nama versi tool berubah.
- **JSON tidak valid**: agent mencoba memperbaiki sendiri; jika tetap gagal, jalankan ulang perintahnya.
- **Tanggal berlaku beda antar sumber**: agent mencatatnya di `verify_notes`; pakai sumber resmi (peraturan.go.id, mkri.id, situs kementerian).
