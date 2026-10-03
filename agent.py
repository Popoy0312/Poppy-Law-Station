#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LAW STATION CONTENT AGENT
=========================
Riset (web search) -> draft carousel -> cek fakta -> render slide hitam-emas -> caption + sumber.
Hasil akhirnya tinggal kamu upload sendiri ke TikTok / Instagram.

  python agent.py demo                              # tes tampilan slide (tanpa API, gratis)
  python agent.py plan                              # rencana 7 konten (tiap 2 hari) -> plan.json
  python agent.py today [--telegram]                # buat konten untuk hari ini (dari plan.json)
  python agent.py make "topik" [--telegram]         # buat konten untuk topik bebas
  python agent.py render output/xxx/content.json    # render ulang setelah kamu edit teksnya

MODE GRATIS (tanpa API berbayar):
  python agent.py prompt [--date ...] ["topik"]     # tulis prompt siap-tempel untuk chat AI gratis
  python agent.py render balasan.txt                # ubah balasan AI jadi slide + caption (lokal, gratis)
  python agent.py prompt --plan                     # prompt rencana mingguan; hasilnya: plan --from-file balasan.txt

GITHUB (gratis, otomatis) - lihat SETUP-GITHUB.md:
  python agent.py issue                             # susun Issue berisi prompt di hari jadwal (dipanggil workflow)
  python agent.py inbox                             # ubah balasan AI di inbox/ jadi slide (dipanggil workflow)

Setup lengkap: lihat README.md
"""
import argparse
import json
import os
import random
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

try:  # supaya emoji/simbol aman di terminal Windows
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# =============================================================================
# KONFIGURASI
# =============================================================================
BASE = Path(__file__).resolve().parent
OUT_DIR = BASE / "output"
PLAN_FILE = BASE / "plan.json"
PROMPT_DIR = BASE / "prompts"             # prompt siap-tempel (mode gratis)
INBOX = BASE / "inbox"                    # taruh balasan chat AI di sini (GitHub: commit file ke folder ini)
REPORT_DIR = Path(os.getenv("REPORT_DIR", str(BASE / ".report")))  # laporan untuk GitHub Actions
HISTORY_FILE = BASE / "history.json"      # topik yang sudah dibuat -> agent tidak mengulang
FONT_DIR = BASE / "fonts"                 # taruh title.ttf (serif tebal) & body.ttf (sans)
BG_DIR = BASE / "assets" / "backgrounds"  # opsional: foto gedung MK / palu hakim untuk cover


def load_env():
    f = BASE / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

EVERY_DAYS = int(os.getenv("POST_EVERY_DAYS", "2"))  # jarak antar konten (hari): 2 = konten tiap 2 hari
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
SEARCH_TOOL = os.getenv("SEARCH_TOOL", "web_search_20250305")
W, H = (int(x) for x in os.getenv("SLIDE_SIZE", "1080x1350").lower().split("x"))

BRAND = {
    "name": "LAW STATION",
    "tagline": "LEGAL INSIGHT  •  PROFESSIONAL EXCELLENCE  •  TRUSTED ADVOCACY",
    "handle": "@law.station.offic",
    "cta": "Follow untuk update hukum tiap hari",
    "disclaimer": "Konten ini edukasi umum, bukan nasihat hukum. "
                  "Untuk kasus Anda, konsultasikan dengan advokat.",
}

# Pelajaran dari performa akun (edit kalau pola performamu berubah). Dipakai saat menyusun rencana.
ACCOUNT_INSIGHT = (
    "Pola yang paling viral di akun ini: pertanyaan praktis hukum acara/perdata "
    '(mis. "Bolehkah wanprestasi + PMH digabung dalam 1 gugatan?") dan penjelasan SEMA/PERMA yang spesifik '
    "(sekitar 15-17 ribu views), sedangkan berita putusan MK murni hanya ratusan views. "
    'Jadi walau topiknya berita, bungkus dengan sudut praktis "apa artinya buat kamu".'
)

SEED_HISTORY = [
    "Putusan bebas tidak dapat diajukan banding dan kasasi, apakah PK bisa?",
    "MK: UU Pensiun DPR harus diganti dalam 2 tahun",
    "Polemik audit kerugian negara: MK vs tafsir kejaksaan (Putusan MK 28/PUU-XXIV/2026)",
    "Wanprestasi + PMH, bolehkah digabung dalam 1 gugatan? (SEMA 1/2022)",
    "Putusan MK 282/PUU-XXIII/2025: pasal penghinaan pemerintah dan lembaga negara dinyatakan tidak berlaku",
    "SEMA No. 4 Tahun 2026: 6 keadaan upaya hukum tidak memenuhi syarat formal",
    "RUU Perampasan Aset",
    "Mekanisme plea bargaining",
    "Mekanisme restorative justice menurut UU 20/2025 (KUHAP)",
]

CAT_LABEL = {
    "pidana": "HUKUM PIDANA",
    "perdata": "HUKUM PERDATA",
    "bisnis": "HUKUM BISNIS",
    "tata negara": "HUKUM TATA NEGARA",
    "ketenagakerjaan": "KETENAGAKERJAAN",
    "konsumen": "HUKUM KONSUMEN",
}

# Warna
GOLD = (212, 175, 90)
GOLD_D = (150, 118, 52)
GOLD_DD = (88, 70, 34)
GOLD_LIGHT, GOLD_DARK = (250, 226, 156), (184, 140, 56)  # gradasi teks emas
WHITE = (240, 240, 238)
MUTED = (140, 134, 120)

HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

# Tata letak
MX = 110              # margin kiri-kanan area konten
CW = W - 2 * MX       # lebar area konten
TOP = 232
BOTTOM = H - 170


def today_wib():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Jakarta")).date()
    except Exception:
        return date.today()


# =============================================================================
# RENDER SLIDE (Pillow)
# =============================================================================
SYSTEM_FONTS = {
    "title": [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
        "C:/Windows/Fonts/georgiab.ttf",
        "C:/Windows/Fonts/timesbd.ttf",
    ],
    "body": [
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ],
}


TITLE_HINTS = ["playfair", "cinzel", "cormorant", "lora", "dmserif", "baskerville", "merriweather"]
BODY_HINTS = ["inter", "lato", "opensans", "roboto", "poppins", "montserrat", "worksans"]


def user_fonts(kind):
    """Font di folder fonts/: nama title.ttf / body.ttf, atau nama keluarga umum (PlayfairDisplay-Bold.ttf, Inter-Regular.ttf)."""
    if not FONT_DIR.exists():
        return []
    files = [p for p in FONT_DIR.iterdir() if p.suffix.lower() in (".ttf", ".otf")]
    exact = [p for p in files if p.stem.lower() == kind]
    hints = TITLE_HINTS if kind == "title" else BODY_HINTS
    norm = lambda p: p.stem.lower().replace(" ", "").replace("_", "").replace("-", "")
    hinted = [p for p in files if p not in exact and any(h in norm(p) for h in hints)]
    if kind == "title":
        hinted.sort(key=lambda p: ("bold" not in p.stem.lower(), "italic" in p.stem.lower(), p.name))
    else:
        hinted.sort(key=lambda p: ("regular" not in p.stem.lower() and "[" not in p.stem, "italic" in p.stem.lower(), p.name))
    return [str(p) for p in exact + hinted]


@lru_cache(maxsize=None)
def font(kind, size):
    """kind = 'title' (serif tebal) atau 'body'. Cari di fonts/ dulu, lalu font sistem."""
    paths = user_fonts(kind) + SYSTEM_FONTS[kind]
    for p in paths:
        if Path(p).exists():
            try:
                f = ImageFont.truetype(p, size)
            except OSError:
                continue
            if kind == "title":
                try:
                    f.set_variation_by_axes([700])  # kalau font variabel -> Bold
                except Exception:
                    pass
            return f
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


_M = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def tw(s, f):
    return _M.textlength(s, font=f)


def wrap(text, f, max_w):
    lines, cur = [], ""
    for word in str(text).split():
        t = f"{cur} {word}".strip()
        if cur and tw(t, f) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def wrap_tokens(tokens, f, max_w):
    """tokens = [(kata, is_gold)] -> baris-baris token."""
    lines, cur, cur_w, space = [], [], 0, tw(" ", f)
    for t, flag in tokens:
        w = tw(t, f)
        add = w if not cur else space + w
        if cur and cur_w + add > max_w:
            lines.append(cur)
            cur, cur_w = [(t, flag)], w
        else:
            cur.append((t, flag))
            cur_w += add
    if cur:
        lines.append(cur)
    return lines


def hook_tokens(hook, highlight):
    """Pecah hook jadi kata; kata di dalam `highlight` diberi warna emas."""
    words = hook.split()
    flags = [False] * len(words)
    h = (highlight or "").strip()
    if h and h in hook:
        start, end, pos = hook.index(h), hook.index(h) + len(h), 0
        for i, w in enumerate(words):
            s = hook.index(w, pos)
            pos = s + len(w)
            flags[i] = s >= start and pos <= end
    if not any(flags) and len(words) > 2:  # default: sepertiga kata terakhir
        for i in range(len(words) - max(1, len(words) // 3), len(words)):
            flags[i] = True
    return list(zip(words, flags))


def fit_title(text, max_w, max_h, start, minimum, spacing=1.14):
    size, lines, h = minimum, [str(text)], 0
    for size in range(start, minimum - 1, -2):
        f = font("title", size)
        lines = wrap(text, f, max_w)
        h = int(len(lines) * size * spacing)
        if h <= max_h and all(tw(l, f) <= max_w for l in lines):
            break
    return size, lines, h


def fit_tokens(tokens, max_w, max_h, start, minimum, spacing=1.12):
    size, f, lines, h = minimum, font("title", minimum), [], 0
    for size in range(start, minimum - 1, -4):
        f = font("title", size)
        lines = wrap_tokens(tokens, f, max_w)
        h = int(len(lines) * size * spacing)
        if h <= max_h:
            break
    return size, f, lines, h


def layout_body(text, size, max_w, spacing=1.32):
    """-> (rows, tinggi). rows = [(indent, teks, is_bullet_pertama, y)]."""
    f = font("body", size)
    lh, gap, y, rows = int(size * spacing), int(size * 0.55), 0, []
    paras = [p.strip() for p in str(text).split("\n") if p.strip()]
    for i, p in enumerate(paras):
        bullet = p[0] in "•-–*"
        if bullet:
            p = p.lstrip("•-–* ").strip()
        indent = int(size * 0.95) if bullet else 0
        if i:
            y += gap
        for j, ln in enumerate(wrap(p, f, max_w - indent)):
            rows.append((indent, ln, bullet and j == 0, y))
            y += lh
    return rows, y


def fit_body(text, max_w, max_h, start=52, minimum=30):
    rows, h = [], 0
    for size in range(start, minimum - 1, -2):
        rows, h = layout_body(text, size, max_w)
        if h <= max_h:
            return size, rows, h
    lh = int(minimum * 1.32)  # terlalu panjang: potong baris yang keluar area
    return minimum, [r for r in rows if r[3] + lh <= max_h], min(h, max_h)


def make_bg(path=None):
    if path:
        try:
            resample = getattr(Image, "Resampling", Image).LANCZOS
            im = ImageOps.fit(Image.open(path).convert("RGB"), (W, H), method=resample)
            shade = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(95 + v * 0.6))
            return Image.composite(Image.new("RGB", (W, H), (0, 0, 0)), im, shade)
        except Exception as e:
            print("⚠ background dilewati:", e)
    glow = Image.radial_gradient("L").resize((W, H))  # tengah gelap-hangat -> tepi hitam
    return ImageOps.colorize(glow, (26, 23, 18), (4, 4, 4))


def diamond(d, cx, cy, r, fill):
    d.polygon([(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)], fill=fill)


def ornament(d, cx, y, half=120):
    d.line([cx - half, y, cx - 16, y], fill=GOLD_D, width=2)
    d.line([cx + 16, y, cx + half, y], fill=GOLD_D, width=2)
    diamond(d, cx, y, 7, GOLD)


class Slide:
    def __init__(self, bg_path=None):
        self.img = make_bg(bg_path)
        self.d = ImageDraw.Draw(self.img)

    def gold_text(self, items):
        """items = [((x, y), teks, font)] digambar dengan gradasi emas."""
        m = Image.new("L", self.img.size, 0)
        md = ImageDraw.Draw(m)
        for xy, s, f in items:
            md.text(xy, s, font=f, fill=255)
        bb = m.getbbox()
        if not bb:
            return
        w, h = bb[2] - bb[0], bb[3] - bb[1]
        grad = ImageOps.colorize(Image.linear_gradient("L").resize((w, h)), GOLD_LIGHT, GOLD_DARK)
        self.img.paste(grad, (bb[0], bb[1]), m.crop(bb))

    def centered(self, lines, f, y, lh, fill=WHITE, gold=False):
        items = []
        for ln in lines:
            xy = ((W - tw(ln, f)) / 2, y)
            if gold:
                items.append((xy, ln, f))
            else:
                self.d.text(xy, ln, font=f, fill=fill)
            y += lh
        if gold:
            self.gold_text(items)
        return y


def chrome(s, idx, total):
    """Bingkai emas, header LAW STATION, footer (handle + nomor slide)."""
    d = s.d
    d.rectangle([34, 34, W - 35, H - 35], outline=GOLD_D, width=2)
    d.rectangle([48, 48, W - 49, H - 49], outline=GOLD_DD, width=1)
    f, gap = font("title", 40), 12
    ws = [tw(ch, f) for ch in BRAND["name"]]
    x = (W - (sum(ws) + gap * (len(ws) - 1))) / 2
    items = []
    for ch, w in zip(BRAND["name"], ws):
        items.append(((x, 80), ch, f))
        x += w + gap
    s.gold_text(items)
    ft = font("body", 17)
    d.text(((W - tw(BRAND["tagline"], ft)) / 2, 140), BRAND["tagline"], font=ft, fill=MUTED)
    ornament(d, W // 2, 178, 300)
    ff = font("body", 24)
    d.text((96, H - 98), BRAND["handle"], font=ff, fill=MUTED)
    if idx:
        label = f"{idx:02d} / {total:02d}"
        d.text((W - 96 - tw(label, ff), H - 98), label, font=ff, fill=MUTED)


def render_cover(c, bg, idx, total):
    s = Slide(bg)
    chrome(s, idx, total)
    d = s.d
    # pill kategori
    label = CAT_LABEL.get((c.get("category") or "").lower(), "EDUKASI HUKUM")
    f, gap = font("body", 24), 5
    ws = [tw(ch, f) for ch in label]
    pw, ph, y = int(sum(ws) + gap * (len(label) - 1) + 64), 54, TOP + 10
    x0 = (W - pw) // 2
    d.rounded_rectangle([x0, y, x0 + pw, y + ph], radius=27, outline=GOLD_D, width=2)
    x = x0 + 32
    for ch, w in zip(label, ws):
        d.text((x, y + 12), ch, font=f, fill=GOLD)
        x += w + gap
    # badge dasar hukum
    bf = font("body", 30)
    b_lines = wrap(c.get("cover_badge", ""), bf, CW - 120)[:2]
    b_h = len(b_lines) * 42 + 44 if b_lines else 0
    # judul
    area_top = y + ph + 40
    area_bottom = H - 200 - (b_h + 40 if b_h else 0) - 50
    tokens = hook_tokens(c["hook"].upper(), c.get("hook_highlight", "").upper())
    size, tf, lines, th = fit_tokens(tokens, CW, area_bottom - area_top, 112, 56)
    ty = area_top + (area_bottom - area_top - th) // 2
    lh, gold_items = int(size * 1.12), []
    space, yy = tw(" ", tf), ty
    for ln in lines:
        ws2 = [tw(t, tf) for t, _ in ln]
        x = (W - (sum(ws2) + space * (len(ln) - 1))) / 2
        for (t, flag), w in zip(ln, ws2):
            if flag:
                gold_items.append(((x, yy), t, tf))
            else:
                d.text((x, yy), t, font=tf, fill=WHITE)
            x += w + space
        yy += lh
    s.gold_text(gold_items)
    ornament(d, W // 2, ty + th + 34, 150)
    if b_lines:
        bw = int(max(tw(l, bf) for l in b_lines) + 80)
        bx0, by0 = (W - bw) // 2, H - 200 - b_h
        d.rounded_rectangle([bx0, by0, bx0 + bw, by0 + b_h], radius=18, outline=GOLD_D, width=2)
        yy = by0 + 22
        for l in b_lines:
            d.text(((W - tw(l, bf)) / 2, yy), l, font=bf, fill=GOLD)
            yy += 42
    hf, hint = font("body", 24), "G E S E R   >>"
    d.text(((W - tw(hint, hf)) / 2, H - 150), hint, font=hf, fill=GOLD_D)
    return s.img


def render_content(slide, label, idx, total, body_start=52):
    s = Slide()
    chrome(s, idx, total)
    d = s.d
    box_w, box_h = 104, 72
    t_size, t_lines, t_h = fit_title(slide.get("title", ""), CW, 260, 66, 40)
    fixed = box_h + 30 + t_h + 64
    b_size, rows, b_h = fit_body(slide.get("body", ""), CW, BOTTOM - TOP - fixed, body_start, 30)
    y0 = TOP + int(max(0, BOTTOM - TOP - (fixed + b_h)) * 0.3)
    # kotak nomor
    d.rectangle([MX, y0, MX + box_w, y0 + box_h], outline=GOLD, width=2)
    nf = font("title", 38)
    s.gold_text([((MX + (box_w - tw(label, nf)) / 2, y0 + 12), label, nf)])
    # judul
    ty, tf = y0 + box_h + 30, font("title", t_size)
    lh = int(t_size * 1.14)
    s.gold_text([((MX, ty + i * lh), ln, tf) for i, ln in enumerate(t_lines)])
    # garis pemisah
    ly = ty + t_h + 24
    d.line([MX, ly, MX + 200, ly], fill=GOLD_D, width=3)
    diamond(d, MX + 216, ly, 6, GOLD)
    # isi
    by, bf = ly + 40, font("body", b_size)
    for indent, text, is_bullet, ry in rows:
        yy = by + ry
        if is_bullet:
            diamond(d, MX + int(b_size * 0.3), yy + int(b_size * 0.62), 7, GOLD)
        d.text((MX + indent, yy), text, font=bf, fill=WHITE)
    return s.img


def render_closing(c, idx, total):
    s = Slide()
    chrome(s, idx, total)
    d = s.d
    t_size, t_lines, t_h = fit_title("Simpan & Bagikan", CW, 260, 100, 60)
    y = s.centered(t_lines, font("title", t_size), TOP + 90, int(t_size * 1.14), gold=True)
    ornament(d, W // 2, y + 30, 150)
    bf = font("body", 46)
    y = s.centered(wrap("Tag teman yang perlu tahu ini.", bf, CW), bf, y + 84, 62)
    y = s.centered(wrap(BRAND["cta"], bf, CW), bf, y + 4, 62)
    hf = font("title", 54)
    s.centered([BRAND["handle"]], hf, y + 40, 70, gold=True)
    df = font("body", 25)
    dl = wrap(BRAND["disclaimer"], df, 800)
    s.centered(dl, df, H - 170 - len(dl) * 36, 36, fill=MUTED)
    return s.img


def render(c, out_dir):
    """Render semua slide ke PNG. Kembalikan daftar path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    bgs = []
    if BG_DIR.exists():
        bgs = sorted(p for p in BG_DIR.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
    bg = random.Random(c.get("topic", "")).choice(bgs) if bgs else None
    content, basis = c.get("slides", []), c.get("legal_basis", [])
    total = 2 + len(content) + (1 if basis else 0)
    imgs = [render_cover(c, bg, 1, total)]
    for n, sl in enumerate(content, 1):
        imgs.append(render_content(sl, f"{n:02d}", len(imgs) + 1, total))
    if basis:
        body = "\n".join(
            "• " + b.get("name", "") + (f" — {b['detail']}" if b.get("detail") else "") for b in basis
        )
        imgs.append(render_content({"title": "Dasar Hukum", "body": body}, "§", len(imgs) + 1, total, 40))
    imgs.append(render_closing(c, len(imgs) + 1, total))
    paths = []
    for k, im in enumerate(imgs, 1):
        p = out_dir / f"slide_{k:02d}.png"
        im.save(p, optimize=True)
        paths.append(p)
    return paths


# =============================================================================
# CLAUDE (riset + draft + cek fakta)
# =============================================================================
def collect_sources(resp):
    out = []
    for b in resp.content:
        if getattr(b, "type", "") == "web_search_tool_result" and isinstance(b.content, list):
            for r in b.content:
                url = getattr(r, "url", None)
                if url:
                    out.append({"title": getattr(r, "title", None) or url, "url": url})
    return out


def claude(system, user, search=True, max_tokens=6000, max_searches=6):
    try:
        import anthropic
    except ImportError:
        sys.exit("Library belum terpasang. Jalankan: pip install -r requirements.txt")
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY belum diisi. Buat file .env (lihat README.md).")
    client = anthropic.Anthropic()
    tools = [{"type": SEARCH_TOOL, "name": "web_search", "max_uses": max_searches}] if search else None
    messages = [{"role": "user", "content": user}]
    sources, text = [], ""
    for _ in range(8):
        kwargs = dict(model=MODEL, max_tokens=max_tokens, system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools
        resp = client.messages.create(**kwargs)
        sources += collect_sources(resp)
        text = "".join(b.text for b in resp.content if b.type == "text")
        if resp.stop_reason == "pause_turn":  # giliran panjang dijeda server -> lanjutkan
            messages = messages + [{"role": "assistant", "content": resp.content}]
            continue
        if resp.stop_reason == "max_tokens":
            print("⚠ Jawaban terpotong (max_tokens) — hasil mungkin tidak lengkap.")
        break
    seen, uniq = set(), []
    for s in sources:
        if s["url"] not in seen:
            seen.add(s["url"])
            uniq.append(s)
    return text, uniq


def parse_json(text):
    blocks = re.findall(r"<json>(.*?)</json>", text, re.S)
    raw = blocks[-1] if blocks else text[text.find("{"): text.rfind("}") + 1]
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip())
    return json.loads(raw)


def get_json(text):
    try:
        return parse_json(text)
    except (json.JSONDecodeError, ValueError):
        fixed, _ = claude(
            "Kamu memperbaiki JSON rusak. Balas HANYA JSON valid di dalam tag <json></json>, tanpa teks lain.",
            text, search=False, max_tokens=6000)
        return parse_json(fixed)


def system_prompt():
    t = today_wib()
    return f"""Kamu adalah editor konten hukum untuk akun edukasi hukum Indonesia "Law Station" (TikTok & Instagram).
Audiens: masyarakat awam, mahasiswa hukum, dan pelaku usaha kecil. Tujuan: konten yang akurat, mudah dipahami, dan layak dibagikan.
Hari ini: {t.isoformat()} ({HARI[t.weekday()]}). Pengetahuanmu bisa usang, jadi cek aturan terbaru lewat web search.

GAYA
- Bahasa Indonesia yang jelas dan tegas, tanpa jargon berlebihan (istilah hukum dijelaskan singkat).
- Hook cover: pertanyaan atau klaim yang memancing rasa penasaran, maksimal 12 kata, spesifik (angka/nomor aturan jika ada).
  Contoh gaya: "Wanprestasi + PMH, Bolehkah Digabung dalam 1 Gugatan?" / "SEMA No. 4/2026: 6 Keadaan Upaya Hukum Tidak Memenuhi Syarat Formal".
- Satu slide = satu gagasan. Judul slide maks 8 kata. Isi slide maks 35 kata. Poin boleh diawali "• " dan dipisah baris baru.
- Utamakan manfaat praktis: apa artinya bagi pembaca, langkah konkret, contoh singkat.

AKURASI (WAJIB)
- Cari sumber primer/resmi: peraturan.go.id, jdih.*.go.id, mkri.id, putusan3.mahkamahagung.go.id, dpr.go.id, ojk.go.id, kemenkum.go.id; media hukum hanya sebagai pelengkap.
- JANGAN mengarang nomor/tahun peraturan, nomor putusan, atau nomor pasal. Jika tidak terverifikasi, jangan sebut nomornya dan catat di "verify_notes".
- Pastikan aturan masih berlaku (belum dicabut/diubah). KUHP baru (UU 1/2023) dan KUHAP baru (UU 20/2025) sudah berlaku: jangan memakai nomor pasal KUHP/KUHAP lama.
- Jika sumber saling bertentangan (mis. beda tanggal berlaku), pakai sumber resmi dan catat konfliknya di "verify_notes".
- Bedakan fakta (isi aturan/putusan) dari analisis/opini; tandai analisis sebagai "analisis".
- Hormati asas praduga tak bersalah; jangan menuduh individu. Isu politik: netral dan berbasis dokumen.
- Edukasi umum saja: jangan memberi nasihat untuk kasus pribadi.
"""


VERIFY_ROLE = """
PERANMU SEKARANG: pemeriksa fakta hukum yang teliti dan skeptis. Periksa DRAFT klaim demi klaim terhadap sumber resmi
(gunakan web search): nomor/tahun peraturan, nomor putusan, pasal, angka, tanggal, dan status berlaku.
Perbaiki langsung kesalahan, hapus klaim yang tidak bisa diverifikasi, pertahankan gaya dan panjang teks.
Jangan menambah klaim baru yang tidak kamu verifikasi. Isi "confidence" dan "verify_notes" dengan jujur."""

VERIFY_FOLLOWUP = (
    "Sekarang berperan sebagai pemeriksa fakta hukum yang skeptis. Periksa JSON di atas klaim demi klaim "
    "terhadap sumber resmi (cari lewat web): nomor/tahun peraturan, nomor putusan, pasal, angka, tanggal, dan status berlaku. "
    "Perbaiki yang salah, hapus yang tidak bisa diverifikasi, jangan menambah klaim baru. "
    'Balas HANYA JSON yang sudah diperbaiki di dalam tag <json></json> dengan skema yang sama '
    '(isi "confidence" dan "verify_notes" dengan jujur).'
)

SCHEMA = """Keluarkan HANYA JSON valid di dalam tag <json></json> (tanpa teks lain di luar tag) dengan skema:
<json>
{
  "topic": "topik singkat",
  "category": "pidana | perdata | bisnis | tata negara | ketenagakerjaan | konsumen | lainnya",
  "hook": "judul cover (maks 12 kata)",
  "hook_highlight": "bagian dari hook yang diberi warna emas (potongan persis dari hook)",
  "cover_badge": "dasar hukum singkat untuk badge cover, mis. 'UU No. 20 Tahun 2025 (KUHAP)', atau kosong",
  "slides": [{"title": "...", "body": "..."}],
  "legal_basis": [{"name": "nama lengkap peraturan/putusan", "detail": "pasal/amar yang dirujuk", "url": "sumber resmi"}],
  "caption": "caption siap posting: 1 baris hook + 2-3 kalimat inti + 1 pertanyaan pemancing komentar. Maks 500 karakter, tanpa hashtag",
  "hashtags": ["#hukum", "..."],
  "confidence": "high | medium | low",
  "verify_notes": ["hal yang perlu dicek manusia sebelum posting"]
}
</json>"""


def draft_prompt(topic, angle, category, fmt, note):
    return f"""Buat 1 konten carousel untuk topik berikut.

TOPIK: {topic}
SUDUT/HOOK YANG DISARANKAN: {angle or '-'}
KATEGORI: {category or '-'}
FORMAT: {fmt} (carousel = penjelasan runtut; mitos-fakta = tiap slide satu mitos lalu faktanya; kuis = pertanyaan di slide isi, jawaban di slide isi terakhir)
CATATAN KHUSUS: {note or '-'}

Slide isi: 4-6 buah. Cover, slide "Dasar Hukum", dan slide penutup dibuat otomatis oleh sistem — jangan masukkan ke "slides".
Urutan yang disarankan: masalah/konteks -> jawaban inti -> penjelasan poin -> contoh singkat -> tips/kesalahan umum.

{SCHEMA}"""


def draft(topic, angle, category, fmt, note, search=True):
    text, srcs = claude(system_prompt(), draft_prompt(topic, angle, category, fmt, note), search=search)
    return get_json(text), srcs


def verify(data):
    user = ("DRAFT YANG HARUS DIPERIKSA:\n" + json.dumps(data, ensure_ascii=False, indent=1)
            + '\n\nKembalikan versi yang sudah diperbaiki dengan skema yang SAMA, ditambah field '
              '"corrections": [daftar singkat perbaikan yang kamu lakukan].\n\n' + SCHEMA)
    text, srcs = claude(system_prompt() + VERIFY_ROLE, user, search=True, max_tokens=7000, max_searches=6)
    return get_json(text), srcs


def plan_prompt(start, count, history, every=None):
    every = every or EVERY_DAYS
    dates = [start + timedelta(days=every * i) for i in range(count)]
    dates_txt = ", ".join(f"{d.isoformat()} ({HARI[d.weekday()]})" for d in dates)
    return f"""Susun rencana {count} konten untuk akun Law Station, satu konten setiap {every} hari.
Pakai TEPAT tanggal berikut, satu topik per tanggal: {dates_txt}.

PILAR: pidana, perdata, bisnis/UMKM, tata negara & putusan MK, ketenagakerjaan, hukum praktis sehari-hari.
{ACCOUNT_INSIGHT}
KOMPOSISI: kira-kira separuh evergreen praktis, sepertiga topik berita/regulasi yang sedang hangat (CARI lewat web search:
putusan MK, UU/PP/Perpres/SEMA/PERMA baru, tenggat atau ketentuan yang mulai berlaku dalam waktu dekat; taruh yang tenggatnya
paling dekat di tanggal paling awal), dan 1 mitos-vs-fakta atau kuis (idealnya di akhir pekan).
Sebarkan kategori; jangan dua konten berturut-turut kategori yang sama.
SUDAH PERNAH DIBUAT (hindari topik yang sama): {json.dumps(history, ensure_ascii=False)}

Keluarkan HANYA JSON di dalam tag <json></json>:
<json>{{"items": [{{"date": "YYYY-MM-DD", "time": "19:30", "category": "pidana | perdata | bisnis | tata negara | ketenagakerjaan | konsumen",
"format": "carousel | mitos-fakta | kuis", "topic": "...", "hook": "...",
"note": "hal yang harus dicek / aturan terbaru yang harus dipakai", "why": "alasan singkat (1 kalimat)"}}]}}</json>"""


def normalize(d, topic):
    c = dict(d)
    c.setdefault("topic", topic)
    c["hook"] = str(c.get("hook") or topic).strip()
    c["hook_highlight"] = str(c.get("hook_highlight") or "").strip()
    c["cover_badge"] = str(c.get("cover_badge") or "").strip()
    c["slides"] = [
        {"title": str(s.get("title", "")).strip(), "body": str(s.get("body", "")).strip()}
        for s in c.get("slides", []) if isinstance(s, dict) and (s.get("title") or s.get("body"))
    ][:7]
    c["legal_basis"] = [b for b in c.get("legal_basis", []) if isinstance(b, dict) and b.get("name")][:5]
    c["hashtags"] = [h if str(h).startswith("#") else f"#{h}" for h in c.get("hashtags", [])][:12]
    c["caption"] = str(c.get("caption") or "").strip()
    c["confidence"] = c.get("confidence", "medium")
    c["verify_notes"] = [str(x) for x in c.get("verify_notes", [])]
    return c


# =============================================================================
# OUTPUT, RIWAYAT, TELEGRAM
# =============================================================================
def load_history():
    if not HISTORY_FILE.exists():
        HISTORY_FILE.write_text(json.dumps(SEED_HISTORY, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))


def add_history(title):
    h = load_history()
    if title not in h:
        h.append(title)
        HISTORY_FILE.write_text(json.dumps(h, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text_outputs(c, srcs, corrections, out_dir):
    (out_dir / "content.json").write_text(json.dumps(c, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "caption.txt").write_text(c["caption"] + "\n\n" + " ".join(c["hashtags"]), encoding="utf-8")
    L = [f"# {c['hook']}", "", f"Tingkat keyakinan: **{c['confidence']}**", ""]
    if c["verify_notes"]:
        L += ["## ⚠ Cek manual sebelum posting"] + [f"- {n}" for n in c["verify_notes"]] + [""]
    if corrections:
        L += ["## Koreksi dari cek fakta otomatis"] + [f"- {n}" for n in corrections] + [""]
    L += ["## Dasar hukum"]
    for b in c["legal_basis"]:
        L.append(f"- {b['name']}" + (f" — {b['detail']}" if b.get("detail") else "")
                 + (f" ({b['url']})" if b.get("url") else ""))
    L += ["", "## Halaman yang dibaca agent"] + [f"- {s['title']} — {s['url']}" for s in srcs]
    (out_dir / "sources.md").write_text("\n".join(L), encoding="utf-8")


def send_telegram(paths, caption, notes):
    import requests
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (token and chat):
        print("⚠ TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID belum diisi — lewati kirim Telegram.")
        return
    api = f"https://api.telegram.org/bot{token}"
    for i in range(0, len(paths), 10):  # maks 10 foto per album
        media, files = [], {}
        for k, p in enumerate(paths[i:i + 10]):
            media.append({"type": "photo", "media": f"attach://f{k}"})
            files[f"f{k}"] = open(p, "rb")
        r = requests.post(f"{api}/sendMediaGroup", data={"chat_id": chat, "media": json.dumps(media)},
                          files=files, timeout=180)
        for fh in files.values():
            fh.close()
        if not r.ok:
            print("⚠ Telegram gagal:", r.text[:200])
    msg = caption
    if notes:
        msg += "\n\n⚠️ CEK SEBELUM POSTING:\n" + "\n".join(f"- {n}" for n in notes)
    requests.post(f"{api}/sendMessage", data={"chat_id": chat, "text": msg[:4000]}, timeout=60)
    print("✔ Terkirim ke Telegram")


# =============================================================================
# PERINTAH
# =============================================================================
def make(topic, angle="", category="", fmt="carousel", note="", date_str=None,
         search=True, do_verify=True, telegram=False):
    print(f"▶ Riset & draft: {topic}")
    data, srcs = draft(topic, angle, category, fmt, note, search)
    corrections = []
    if do_verify and search:
        print("▶ Cek fakta ke sumber resmi …")
        try:
            fixed, srcs2 = verify(data)
            corrections = fixed.pop("corrections", [])
            data, srcs = fixed, srcs + srcs2
        except Exception as e:  # draft tetap dipakai, tapi diberi peringatan
            data = normalize(data, topic)
            data["verify_notes"].append(f"Cek fakta otomatis gagal ({e}) — cek manual semua nomor aturan dan pasal.")
    srcs = list({x["url"]: x for x in srcs}.values())  # buang duplikat URL
    c = normalize(data, topic)
    slug = slugify(c["hook"])
    out_dir = OUT_DIR / f"{date_str or today_wib().isoformat()}_{slug}"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = render(c, out_dir)
    write_text_outputs(c, srcs, corrections, out_dir)
    add_history(c["hook"])
    print(f"✔ {len(paths)} slide + caption + sumber -> {out_dir}")
    print(f"  keyakinan: {c['confidence']}")
    for n in c["verify_notes"]:
        print(f"  ⚠ cek: {n}")
    if telegram:
        send_telegram(paths, c["caption"] + "\n\n" + " ".join(c["hashtags"]), c["verify_notes"])
    return out_dir


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")[:50] or "konten"


def find_plan_item(d, quiet=False):
    if not PLAN_FILE.exists():
        if quiet:
            return {"items": []}, None
        sys.exit("plan.json belum ada. Jalankan dulu: python agent.py plan")
    plan = json.loads(PLAN_FILE.read_text(encoding="utf-8"))
    item = next((i for i in plan["items"] if i["date"] == d), None)
    if not item and not quiet:
        sys.exit(f"Tidak ada rencana untuk {d}. Jalankan: python agent.py plan")
    return plan, item


def import_plan(items):
    for it in items:
        it["day"] = HARI[date.fromisoformat(it["date"]).weekday()]
        it.setdefault("time", "19:30")
        it["status"] = "pending"
    if PLAN_FILE.exists():
        PLAN_FILE.replace(BASE / "plan.bak.json")
    PLAN_FILE.write_text(json.dumps({"generated": today_wib().isoformat(), "items": items},
                                    ensure_ascii=False, indent=2), encoding="utf-8")
    return items


def cmd_plan(a):
    start = date.fromisoformat(a.start) if a.start else today_wib() + timedelta(days=1)
    if a.from_file:  # mode gratis: balasan AI disimpan manual
        try:
            items = parse_json(Path(a.from_file).read_text(encoding="utf-8"))["items"]
        except Exception as e:
            sys.exit(f"Tidak bisa membaca rencana dari {a.from_file}: {e}")
    else:
        print(f"▶ Menyusun rencana {a.count} konten (tiap {a.every} hari) mulai {start} …")
        text, _ = claude(system_prompt(), plan_prompt(start, a.count, load_history(), a.every),
                         search=True, max_tokens=5000, max_searches=8)
        items = get_json(text)["items"]
    import_plan(items)
    for it in items:
        print(f"{it['date']} {it['day']:<7} [{it.get('category', '')}] {it['topic']}\n    hook: {it['hook']}")
    print(f"✔ Tersimpan di {PLAN_FILE.name}")


def cmd_today(a):
    d = a.date or today_wib().isoformat()
    plan, item = find_plan_item(d, quiet=True)
    if not item:
        later = sorted(i["date"] for i in plan["items"] if i["date"] > d)
        print(f"{d} bukan jadwal konten." + (f" Jadwal berikutnya: {later[0]}." if later else
              " Rencana habis — jalankan: python agent.py plan"))
        return
    if item.get("status") == "done" and not a.force:
        sys.exit(f"Konten {d} sudah dibuat. Pakai --force untuk membuat ulang.")
    make(item["topic"], item.get("hook", ""), item.get("category", ""), item.get("format", "carousel"),
         item.get("note", ""), d, not a.no_search, not a.no_verify, a.telegram)
    item["status"] = "done"
    PLAN_FILE.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_make(a):
    make(a.topic, a.angle, a.category, a.format, "", None, not a.no_search, not a.no_verify, a.telegram)


def cmd_render(a):
    """Render dari content.json (edit manual) ATAU dari balasan mentah chat AI (ada tag <json>)."""
    p = Path(a.json_file)
    try:
        data = parse_json(p.read_text(encoding="utf-8"))
    except Exception as e:
        sys.exit(f"Tidak bisa membaca JSON dari {p.name}: {e}")
    corrections = data.pop("corrections", [])
    c = normalize(data, "konten")
    in_place = p.name == "content.json"
    out_dir = p.parent if in_place else OUT_DIR / f"{today_wib().isoformat()}_{slugify(c['hook'])}"
    paths = render(c, out_dir)
    if in_place:
        (out_dir / "caption.txt").write_text(c["caption"] + "\n\n" + " ".join(c["hashtags"]), encoding="utf-8")
    else:
        write_text_outputs(c, [], corrections, out_dir)
        add_history(c["hook"])
    print(f"✔ {len(paths)} slide + caption -> {out_dir}")
    for n in c["verify_notes"]:
        print(f"  ⚠ cek: {n}")


def cmd_prompt(a):
    """MODE GRATIS: tulis prompt siap-tempel untuk chat AI gratis yang punya pencarian web."""
    PROMPT_DIR.mkdir(exist_ok=True)
    if a.plan:
        start = date.fromisoformat(a.start) if a.start else today_wib() + timedelta(days=1)
        path = PROMPT_DIR / f"rencana_{start.isoformat()}.txt"
        path.write_text(system_prompt() + "\n\n" + plan_prompt(start, a.count, load_history(), a.every), encoding="utf-8")
        print(f"✔ {path}\n1) Tempel isinya ke chat AI (aktifkan pencarian web)\n"
              "2) Simpan balasannya ke balasan.txt\n3) python agent.py plan --from-file balasan.txt")
        return
    if a.topic:
        topic, angle, category, fmt, note = a.topic, a.angle, a.category, a.format, ""
        d = today_wib().isoformat()
    else:
        d = a.date or today_wib().isoformat()
        _, it = find_plan_item(d)
        topic, angle, category = it["topic"], it.get("hook", ""), it.get("category", "")
        fmt, note = it.get("format", "carousel"), it.get("note", "")
    base = PROMPT_DIR / f"{d}_{slugify(angle or topic)}"
    f1, f2 = Path(f"{base}_1_draft.txt"), Path(f"{base}_2_cekfakta.txt")
    f1.write_text(system_prompt() + "\n\n" + draft_prompt(topic, angle, category, fmt, note), encoding="utf-8")
    f2.write_text(VERIFY_FOLLOWUP, encoding="utf-8")
    print(f"✔ {f1}\n✔ {f2}\n"
          "1) Tempel file _1_draft ke chat AI (aktifkan pencarian web)\n"
          "2) Setelah AI membalas, kirim isi file _2_cekfakta di chat yang sama\n"
          "3) Simpan balasan TERAKHIR AI ke balasan.txt, lalu: python agent.py render balasan.txt")


def gh_url(kind, path, raw=False):
    repo = os.getenv("GITHUB_REPOSITORY")
    if not repo:
        return None
    branch = os.getenv("GITHUB_REF_NAME") or "main"
    return f"https://github.com/{repo}/{kind}/{branch}/{path}" + ("?raw=true" if raw else "")


def write_report(title, body):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "report_title.txt").write_text(title, encoding="utf-8")
    (REPORT_DIR / "report_body.md").write_text(body, encoding="utf-8")


def report_section(c, out_dir, paths):
    rel = out_dir.relative_to(BASE).as_posix()
    L = [f"## {c['hook']}", "", f"Tingkat keyakinan: **{c['confidence']}**"]
    if c["verify_notes"]:
        L += ["", "**⚠ Cek manual sebelum posting:**"] + [f"- {n}" for n in c["verify_notes"]]
    L += ["", "**Caption (salin):**", "", "````", c["caption"] + "\n\n" + " ".join(c["hashtags"]), "````"]
    folder = gh_url("tree", rel)
    if folder:
        L += ["", f"📁 [Buka folder slide dan sumber]({folder})", "", "**Slide** (tahan gambar → simpan):", ""]
        L += [f"![{p.stem}]({gh_url('blob', rel + '/' + p.name, raw=True)})" for p in paths]
    return "\n".join(L)


def cmd_inbox(a):
    """GitHub Actions: proses balasan chat AI di inbox/ (rencana -> plan.json, konten -> slide + caption)."""
    INBOX.mkdir(exist_ok=True)
    files = sorted(p for p in INBOX.iterdir()
                   if p.is_file() and p.suffix.lower() in {".txt", ".json", ".md"}
                   and not p.name.lower().startswith("readme"))
    if not files:
        print("inbox kosong - tidak ada yang diproses")
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    sections, new_dirs, hooks, plans, errors = [], [], [], 0, 0
    for f in files:
        dest = INBOX / "done"
        try:
            data = parse_json(f.read_text(encoding="utf-8"))
            if isinstance(data.get("items"), list):
                items = import_plan(data["items"])
                plans += 1
                sections.append("## 📅 Rencana mingguan diimpor\n\n" + "\n".join(
                    f"- {i['date']} ({i['day']}): {i['topic']}" for i in items))
            else:
                corrections = data.pop("corrections", [])
                c = normalize(data, "konten")
                if not c["slides"]:
                    raise ValueError("JSON tidak berisi 'slides'")
                out_dir = OUT_DIR / f"{today_wib().isoformat()}_{slugify(c['hook'])}"
                paths = render(c, out_dir)
                write_text_outputs(c, [], corrections, out_dir)
                add_history(c["hook"])
                new_dirs.append(out_dir)
                hooks.append(c["hook"])
                sections.append(report_section(c, out_dir, paths))
        except Exception as e:
            dest = INBOX / "error"
            errors += 1
            why = ("isinya bukan JSON yang valid (tanda kutip/koma salah, atau balasan AI terpotong)"
                   if isinstance(e, json.JSONDecodeError) else e)
            sections.append(f"## ⚠ Gagal memproses `{f.name}`\n\n{why}\n\nFile dipindah ke `inbox/error/`. "
                            'Minta AI: "Perbaiki menjadi JSON valid saja", lalu tambahkan lagi ke `inbox/`.')
        dest.mkdir(exist_ok=True)
        f.replace(dest / f"{stamp}_{f.name}")
        print(f"{'OK ' if dest.name == 'done' else 'GAGAL'} {f.name} -> inbox/{dest.name}/")
    shutil.rmtree(REPORT_DIR / "latest", ignore_errors=True)
    for d in new_dirs:
        shutil.copytree(d, REPORT_DIR / "latest" / d.name)
    if hooks:
        title = "✅ Konten siap: " + "; ".join(hooks)[:90]
    elif errors:
        title = "⚠ Gagal memproses inbox"
    else:
        title = "📅 Rencana mingguan diimpor"
    footer = ""
    repo, run = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_RUN_ID")
    if repo and run and new_dirs:
        footer = (f"\n\n---\n📦 [Unduh semua slide sekaligus (ZIP)](https://github.com/{repo}/actions/runs/{run})"
                  " — lihat bagian *Artifacts* di bawah halaman itu.")
    write_report(title, "\n\n".join(sections) + footer)


def cmd_issue(a):
    """GitHub Actions: susun Issue berisi prompt siap-tempel pada hari jadwal konten (tiap EVERY_DAYS hari)."""
    for f in ("report_title.txt", "report_body.md"):  # buang laporan lama agar tidak terposting ulang
        (REPORT_DIR / f).unlink(missing_ok=True)
    d = a.date or today_wib().isoformat()
    plan = json.loads(PLAN_FILE.read_text(encoding="utf-8")) if PLAN_FILE.exists() else {"items": []}
    items = sorted(plan.get("items", []), key=lambda i: i["date"])
    item = next((i for i in items if i["date"] == d), None)
    if not item:
        if items and d < items[-1]["date"]:
            nxt_item = next((i for i in items if i["date"] > d), None)
            print(f"{d} bukan jadwal konten (jadwal berikutnya: {nxt_item['date'] if nxt_item else '-'}) - tidak ada Issue.")
            return
        if items:  # rencana sudah habis: ingatkan hanya pada hari yang seharusnya ada konten
            gap = (date.fromisoformat(d) - date.fromisoformat(items[-1]["date"])).days
            if gap % EVERY_DAYS:
                print(f"{d}: rencana habis, pengingat berikutnya di hari jadwal - tidak ada Issue.")
                return
    repo, branch = os.getenv("GITHUB_REPOSITORY"), os.getenv("GITHUB_REF_NAME") or "main"
    paste = (f"[buat file baru di inbox](https://github.com/{repo}/new/{branch}?filename=inbox/{d}.txt)"
             if repo else f"buat file baru `inbox/{d}.txt`")
    block = lambda text: f"````\n{text}\n````"
    plan_steps = ("1. Salin prompt di bawah → tempel ke chat AI (aktifkan pencarian web).\n"
                  f"2. Salin balasan AI → {paste} (nama bebas, mis. `inbox/rencana.txt`) → *Commit changes*.\n"
                  "3. Rencana terdeteksi otomatis dan `plan.json` diperbarui.")
    if item:
        title = f"📝 Prompt konten {d}: {item.get('hook') or item['topic']}"
        draft_txt = system_prompt() + "\n\n" + draft_prompt(
            item["topic"], item.get("hook", ""), item.get("category", ""), item.get("format", "carousel"), item.get("note", ""))
        body = [f"**Topik:** {item['topic']}", f"**Hook:** {item.get('hook', '-')}", "",
                "### Langkah (±5 menit)",
                "1. Salin **Prompt 1** → tempel ke chat AI yang punya pencarian web (Claude, Gemini, ChatGPT).",
                "2. Setelah AI membalas, salin **Prompt 2** → kirim di chat yang sama (cek fakta).",
                f"3. Salin balasan TERAKHIR AI → {paste} → tempel → *Commit changes*.",
                '4. Tunggu ±1 menit: Issue "✅ Konten siap" berisi slide dan caption akan muncul.', "",
                "### Prompt 1 (draft)", block(draft_txt), "",
                "### Prompt 2 (cek fakta)", block(VERIFY_FOLLOWUP)]
        if d >= items[-1]["date"]:
            nxt = date.fromisoformat(d) + timedelta(days=EVERY_DAYS)
            body += ["", "---", f"### 📅 Ini konten terakhir di rencana — buat rencana mulai {nxt.isoformat()}", plan_steps, "",
                     block(system_prompt() + "\n\n" + plan_prompt(nxt, 7, load_history()))]
    else:
        title = f"📅 Rencana konten habis ({d}) — buat rencana baru"
        body = ["Belum ada rencana untuk hari ini di `plan.json`.", "", "### Langkah", plan_steps, "",
                block(system_prompt() + "\n\n" + plan_prompt(date.fromisoformat(d), 7, load_history()))]
    write_report(title, "\n".join(body))
    print(title)


DEMO = {
    "topic": "Perjanjian tanpa meterai",
    "category": "perdata",
    "hook": "Perjanjian Tanpa Meterai Itu Tidak Sah?",
    "hook_highlight": "Tidak Sah?",
    "cover_badge": "KUHPerdata Pasal 1320 • UU Bea Meterai",
    "slides": [
        {"title": "Mitos yang Sering Dipercaya",
         "body": "Banyak orang mengira surat perjanjian otomatis batal kalau tidak ada meterai.\nBenarkah begitu?"},
        {"title": "Fakta: Sah Tidaknya Bukan Soal Meterai",
         "body": "Sah atau tidaknya perjanjian ditentukan syarat Pasal 1320 KUHPerdata:\n"
                 "• Sepakat\n• Cakap\n• Hal tertentu\n• Sebab yang halal"},
        {"title": "Lalu, Apa Fungsi Meterai?",
         "body": "Meterai adalah pajak atas dokumen (UU Bea Meterai), bukan syarat sahnya perjanjian.\n"
                 "Pengaruhnya ada pada penggunaan dokumen sebagai alat bukti."},
        {"title": "Kalau Lupa Pasang Meterai?",
         "body": "Perjanjian tetap mengikat para pihak. Dokumen bisa dimeteraikan belakangan lewat mekanisme "
                 "pemeteraian kemudian sebelum dipakai sebagai bukti."},
        {"title": "Tips Aman",
         "body": "• Tetap bubuhkan meterai pada perjanjian penting\n• Tulis hak dan kewajiban dengan jelas\n"
                 "• Simpan salinan yang ditandatangani semua pihak"},
    ],
    "legal_basis": [
        {"name": "Kitab Undang-Undang Hukum Perdata", "detail": "Pasal 1320 (syarat sah perjanjian)"},
        {"name": "UU No. 10 Tahun 2020 tentang Bea Meterai", "detail": "meterai sebagai pajak atas dokumen"},
    ],
    "caption": "Perjanjian tanpa meterai = batal? Ternyata tidak sesederhana itu. Sah tidaknya perjanjian "
               "ditentukan Pasal 1320 KUHPerdata, sedangkan meterai terkait pajak dokumen dan kekuatannya "
               "sebagai alat bukti. Pernah mengalami? Ceritakan di komentar!",
    "hashtags": ["#hukum", "#edukasihukum", "#hukumperdata", "#perjanjian", "#lawstation", "#hukumindonesia"],
    "confidence": "medium",
    "verify_notes": ["CONTOH DEMO — verifikasi ke sumber resmi sebelum diposting"],
}


def cmd_demo(a):
    out = OUT_DIR / "demo"
    c = normalize(DEMO, DEMO["topic"])
    paths = render(c, out)
    write_text_outputs(c, [], [], out)
    print(f"✔ {len(paths)} slide contoh -> {out}  (buka dan cek tampilannya)")


def main():
    ap = argparse.ArgumentParser(description="Law Station Content Agent")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--telegram", action="store_true", help="kirim hasil ke Telegram")
        p.add_argument("--no-verify", action="store_true", help="lewati cek fakta (lebih murah, kurang aman)")
        p.add_argument("--no-search", action="store_true", help="tanpa web search (tidak disarankan)")

    sub.add_parser("demo", help="render slide contoh tanpa API")
    sub.add_parser("inbox", help="GitHub Actions: proses balasan chat AI di inbox/")
    p = sub.add_parser("issue", help="GitHub Actions: susun Issue harian berisi prompt")
    p.add_argument("--date", help="YYYY-MM-DD (default: hari ini WIB)")
    p = sub.add_parser("plan", help="susun rencana konten ke depan")
    p.add_argument("--start", help="tanggal mulai YYYY-MM-DD (default: besok)")
    p.add_argument("--count", type=int, default=7, help="jumlah konten dalam rencana")
    p.add_argument("--every", type=int, default=EVERY_DAYS, help="jarak antar konten (hari)")
    p.add_argument("--from-file", help="impor rencana dari balasan chat AI (mode gratis)")
    p = sub.add_parser("today", help="buat konten hari ini dari plan.json")
    common(p)
    p.add_argument("--date", help="YYYY-MM-DD (default: hari ini WIB)")
    p.add_argument("--force", action="store_true", help="buat ulang walau sudah berstatus done")
    p = sub.add_parser("make", help="buat konten untuk topik bebas")
    common(p)
    p.add_argument("topic")
    p.add_argument("--angle", default="", help="sudut/hook yang diinginkan")
    p.add_argument("--category", default="")
    p.add_argument("--format", default="carousel", choices=["carousel", "mitos-fakta", "kuis"])
    p = sub.add_parser("render", help="render slide dari content.json yang diedit, atau dari balasan chat AI")
    p.add_argument("json_file")
    p = sub.add_parser("prompt", help="MODE GRATIS: buat prompt siap-tempel untuk chat AI")
    p.add_argument("topic", nargs="?", help="topik bebas (kosong = ambil dari plan.json)")
    p.add_argument("--date", help="YYYY-MM-DD dari plan.json (default: hari ini WIB)")
    p.add_argument("--plan", action="store_true", help="prompt untuk menyusun rencana mingguan")
    p.add_argument("--start", help="tanggal mulai rencana (dengan --plan)")
    p.add_argument("--count", type=int, default=7, help="jumlah konten dalam rencana (dengan --plan)")
    p.add_argument("--every", type=int, default=EVERY_DAYS, help="jarak antar konten (hari)")
    p.add_argument("--angle", default="")
    p.add_argument("--category", default="")
    p.add_argument("--format", default="carousel", choices=["carousel", "mitos-fakta", "kuis"])

    a = ap.parse_args()
    {"demo": cmd_demo, "plan": cmd_plan, "today": cmd_today, "make": cmd_make, "render": cmd_render,
     "prompt": cmd_prompt, "inbox": cmd_inbox, "issue": cmd_issue}[a.cmd](a)


if __name__ == "__main__":
    main()
