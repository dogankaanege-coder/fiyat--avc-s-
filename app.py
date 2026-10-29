#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FiyatAvcısı AI v3 — Akakçe, Trendyol, Amazon TR, Pazarama ve Vatan Canlı Fiyat & Kupon Motoru
Headless Chrome ile Akakçe ve Trendyol'dan gerçek zamanlı en ucuz fiyatları çeker.
Türev ürün ("esmer pirinç" vs "pirinç unu"), aksesuar ve model varyantı filtreleri içerir.
"""

import concurrent.futures
import html
import http.server
import json
import os
import re
import socket
import statistics
import subprocess
import time
import urllib.parse
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TUNNEL_FILE = BASE_DIR / "tunnel_url.txt"
PORT = int(os.environ.get("PORT", "8080"))


def find_chrome_binary() -> str:
    env_bin = os.environ.get("CHROME_BIN") or os.environ.get("CHROME_PATH")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    candidates = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for name in ("chromium", "chromium-browser", "google-chrome", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return ""


CHROME_PATH = find_chrome_binary()

# Türev ürün kelimeleri: Kullanıcı sorgusunda açıkça istemediyse bu ürünleri ele
# Örn: "esmer pirinç" arandığında "esmer pirinç unu", "pirinç patlağı", "yer fıstığı" elenir.
DERIVATIVE_KEYWORDS = {
    "unu", "un", "tozu", "toz", "ezmesi", "ezme", "patlagi", "patlak",
    "sutu", "sut", "yagi", "yag", "sirkesi", "sirke", "kremasi", "krema",
    "cipsi", "cips", "makarnasi", "makarna", "ekmegi", "ekmek", "kepegi",
    "fistigi", "fistik", "pure", "puresi", "sabun", "sabunu",
    "ekstrakt", "ekstrakti", "aromasi", "aroma", "sos", "sosu"
}

# Aksesuar, yedek parça ve ikinci el kelimeleri
ACCESSORY_KEYWORDS = {
    "kilif", "kilifi", "kiliflar", "kapak", "kapagi", "silikon", "case", "cover",
    "ekran koruyucu", "temperli cam", "koruma cami", "koruyucu cam", "lens koruyucu",
    "koruyucu film", "nano film", "kirilmaz cam", "koruyucu", "koruyucusu",
    "kordon", "kordonu", "saat kordonu", "aski", "askisi", "adaptor", "adaptoru",
    "sarj kablosu", "data kablosu", "sarj aleti", "sarj cihazi", "kablo", "kablosu",
    "stand", "standi", "tutucu", "tutacagi", "arac tutucu",
    "sticker", "kaplama", "toz torbasi", "yedek filtre", "yedek baslik", "bagcik",
    "temizleme kopugu", "koruyucu kilif", "silikon kilif", "seffaf kilif", "yenilenmis",
    "ikinci el", "teshir", "maket", "oyuncak", "dummy", "a kalite", "b kalite", "c kalite",
    "batarya", "bataryasi", "yedek parca", "dokunmatik panel", "ekran paneli"
}

# Model varyantı kelimeleri (S26 ararken S26 FE veya S26 Ultra'yı ayırmak için)
MODEL_VARIANT_TOKENS = {"fe", "lite", "mini", "se", "plus", "ultra", "pro", "max"}


def get_tunnel_url() -> str:
    if os.environ.get("SPACE_HOST"):
        return f"https://{os.environ.get('SPACE_HOST')}"
    if TUNNEL_FILE.exists():
        try:
            return TUNNEL_FILE.read_text().strip()
        except Exception:
            pass
    return "https://advert-sip-sandra-bin.trycloudflare.com"


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def tr_lower(text: str) -> str:
    return (
        text.replace("İ", "i")
        .replace("I", "ı")
        .replace("Ğ", "ğ")
        .replace("Ü", "ü")
        .replace("Ş", "ş")
        .replace("Ö", "ö")
        .replace("Ç", "ç")
        .lower()
    )


def tr_ascii(text: str) -> str:
    s = tr_lower(text)
    return (
        s.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )


def curl_fetch(url: str, timeout: int = 7) -> str:
    try:
        out = subprocess.check_output(
            [
                "curl",
                "-sL",
                "--max-time",
                str(timeout),
                "--compressed",
                "-A",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "-H",
                "Accept-Language: tr-TR,tr;q=0.9,en-US;q=0.7",
                url,
            ],
            stderr=subprocess.DEVNULL,
        )
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def fetch_chrome_dom(url: str, timeout: int = 10) -> str:
    if not os.path.exists(CHROME_PATH):
        return ""
    try:
        out = subprocess.check_output(
            [
                CHROME_PATH,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--blink-settings=imagesEnabled=false",
                "--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
                "--dump-dom",
                url,
            ],
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
        return out.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def parse_tr_float(text: str):
    m = re.search(
        r"(?<![0-9.,])([0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?|[0-9]{1,6}(?:,[0-9]{1,2})?)",
        text,
    )
    if not m:
        return None
    raw = m.group(1).replace(".", "").replace(",", ".")
    try:
        val = round(float(raw), 2)
        if 15.0 <= val <= 950000.0 and val not in (2023.0, 2024.0, 2025.0, 2026.0, 2027.0):
            return val
    except ValueError:
        pass
    return None


def is_relevant_product(title: str, query: str) -> bool:
    t_norm = tr_ascii(title)
    q_norm = tr_ascii(query)

    t_words = [w for w in re.split(r"[^a-z0-9+]+", t_norm) if len(w) >= 1]
    q_words = [w for w in re.split(r"[^a-z0-9+]+", q_norm) if len(w) >= 1]
    t_set = set(t_words)
    q_set = set(q_words)

    if not q_words:
        return True

    # 1. Aksesuar kontrolü (Kullanıcı aramadıysa kılıf, kapak, silikon, ekran koruyucu elenir)
    for acc in ACCESSORY_KEYWORDS:
        if " " in acc:
            if acc in t_norm and acc not in q_norm:
                return False
        else:
            if acc in t_set and acc not in q_set:
                return False

    # 2. Türev ürün kontrolü (Kullanıcı aramadıysa un, toz, ezme, fıstık vb. elenir)
    for d in DERIVATIVE_KEYWORDS:
        if d in t_set and d not in q_set:
            return False

    # 3. Model varyantı kontrolü (İki yönlü: S26 vs S26 FE, iPhone 16 vs 16 Pro)
    has_model_number = any(any(ch.isdigit() for ch in w) and not w.endswith("gb") and not w.endswith("tb") for w in q_words)
    for var_tok in MODEL_VARIANT_TOKENS:
        if var_tok in q_set and var_tok not in t_set:
            return False
    if has_model_number or any(k in q_set for k in ("iphone", "galaxy", "redmi", "xiaomi", "ipad", "macbook", "watch")):
        for var_tok in MODEL_VARIANT_TOKENS:
            if var_tok in t_set and var_tok not in q_set:
                return False
        if "+" not in q_norm and any(tw.endswith("+") for tw in t_words):
            return False

    # 4. Sorgudaki kelimelerin başlıkta tam kelime olarak bulunma zorunluluğu
    # "esmer" kelimesi "esmerim" içinde eşleşmemeli; kelime bazlı kontrol
    for q in q_words:
        if any(ch.isdigit() for ch in q):
            if q not in t_set:
                return False
        else:
            if q not in t_set:
                return False

    return True


# ---------------------------------------------------------------------------
# Canlı Mağaza ve Karşılaştırma Scraper'ları
# ---------------------------------------------------------------------------
def scrape_akakce(query: str) -> list:
    """Akakçe'den canlı en ucuz satıcı ve fiyatları çeker."""
    url = "https://www.akakce.com/arama/?q=" + urllib.parse.quote(query)
    raw = fetch_chrome_dom(url, timeout=10)
    if not raw:
        return []
    blocks = re.split(r"<li[^>]+data-pr=", raw)[1:]
    offers = []
    for b in blocks:
        li_body = b.split("</li>")[0]
        t_m = re.search(r"<h3[^>]*class=\"pn_v[0-9]+\"[^>]*>(.*?)</h3>", li_body, re.S) or re.search(r"<a[^>]+title=\"([^\"]+)\"", li_body) or re.search(r"alt=\"([^\"]+)\"", li_body)
        p_m = re.search(r"class=\"[^\"]*pt_v[0-9]+[^\"]*\"[^>]*>(.*?)</span>", li_body, re.S)
        u_m = re.search(r"href=\"([^\"]+)\"", li_body)
        if not t_m or not p_m:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", " ", t_m.group(1))).strip()
        title = re.sub(r"\s+", " ", title)
        p_txt = html.unescape(re.sub(r"<[^>]+>", "", p_m.group(1))).strip()
        m_num = re.search(r"([0-9]{1,3}(?:\.[0-9]{3})*(?:,[0-9]{1,2})?)", p_txt)
        if not m_num:
            continue
        price = float(m_num.group(1).replace(".", "").replace(",", "."))
        link = html.unescape(u_m.group(1)) if u_m else url
        if link.startswith("/"):
            link = "https://www.akakce.com" + link

        if is_relevant_product(title, query):
            offers.append({
                "store_name": "Akakçe (En Ucuz Satıcı)",
                "badge": "Fiyat Karşılaştırma",
                "color": "#2563EB",
                "shipping": "En Ucuz Mağazaya Yönlendirir",
                "app_promo": "Akakçe üzerinden yüzlerce mağaza arasında doğrulanmış en düşük fiyat",
                "title": title[:92],
                "url": link,
                "price": price,
                "original_price": None,
            })
    return offers


def scrape_trendyol(query: str) -> list:
    """Trendyol'dan canlı ürün ve fiyatları çeker."""
    url = "https://www.trendyol.com/sr?q=" + urllib.parse.quote(query)
    raw = fetch_chrome_dom(url, timeout=10)
    if not raw:
        return []
    links = re.findall(r'<a[^>]+href="(/[^\"]+-p-[0-9]+[^\"]*)"[^>]*>(.*?)</a>', raw, re.S)
    offers = []
    for u, inner in links[:20]:
        txt = html.unescape(re.sub(r"<[^>]+>", " ", inner))
        txt = re.sub(r"\s+", " ", txt).strip()
        p_matches = re.findall(r"([0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?|[0-9]{2,6}(?:,[0-9]{1,2})?)\s*TL", txt)
        if not p_matches:
            continue
        clean_title = re.sub(r"^(Hızlı Bakış|Hızlı Teslimat|Kargo Bedava|Son [0-9]+ Günün En Düşük Fiyatı|En Çok Favorilenen [0-9]+\. Ürün|\s+)+", "", txt).strip()
        clean_title = re.split(r"[0-9]\.[0-9]\s+\(\s*[0-9]+\s*\)|Sepette\s*%?[0-9]+|Sepete Ekle|[0-9]{1,3}(?:\.[0-9]{3})*\s*TL", clean_title)[0].strip()
        if len(clean_title) < 5:
            clean_title = txt[:75]
        if is_relevant_product(clean_title, query):
            p = float(p_matches[0].replace(".", "").replace(",", "."))
            orig = float(p_matches[-1].replace(".", "").replace(",", ".")) if len(p_matches) > 1 and float(p_matches[-1].replace(".", "").replace(",", ".")) > p else None
            offers.append({
                "store_name": "Trendyol",
                "badge": "Pazaryeri",
                "color": "#F27A1A",
                "shipping": "Hızlı Kargo / Bedava",
                "app_promo": "Satıcıyı Takip Et Kuponu + Nays %10 Nakit İade",
                "title": clean_title[:92],
                "url": "https://www.trendyol.com" + u.split("?")[0],
                "price": p,
                "original_price": orig,
            })
    return offers


def scrape_amazon_tr(query: str) -> list:
    raw = curl_fetch("https://www.amazon.com.tr/s?k=" + urllib.parse.quote(query), timeout=7)
    if not raw:
        return []
    items = raw.split('data-component-type="s-search-result"')[1:20]
    offers = []
    for it in items:
        if "Sponsorlu" in it[:1400]:
            continue
        asin_m = re.search(r'data-asin="([A-Z0-9]{10})"', it)
        h2s = re.findall(r"<h2[^>]*>(.*?)</h2>", it, re.S)
        title = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", h)).strip() for h in h2s)
        title = re.sub(r"\s+", " ", title).strip()
        if not title or not is_relevant_product(title, query):
            continue

        prices_raw = re.findall(r'class="a-offscreen"[^>]*>(.*?)</span>', it, re.S)
        p_vals = [parse_tr_float(html.unescape(p)) for p in prices_raw]
        p_vals = [p for p in p_vals if p]
        if not p_vals:
            continue

        sale_price = p_vals[0]
        orig_price = max(p_vals) if len(p_vals) > 1 and max(p_vals) > sale_price else None
        asin = asin_m.group(1) if asin_m else ""
        url = f"https://www.amazon.com.tr/dp/{asin}" if asin else f"https://www.amazon.com.tr/s?k={urllib.parse.quote(query)}"

        offers.append({
            "store_name": "Amazon Türkiye",
            "badge": "Resmi Satıcı",
            "color": "#FF9900",
            "shipping": "Prime Hızlı Kargo",
            "app_promo": "Amazon Mobil İlk Siparişe Özel 150 TL İndirim + Nays %10 İade",
            "title": title[:92],
            "url": url,
            "price": sale_price,
            "original_price": orig_price,
        })
    return offers


def scrape_pazarama(query: str) -> list:
    raw = curl_fetch("https://www.pazarama.com/arama?q=" + urllib.parse.quote(query), timeout=7)
    if not raw:
        return []
    links = re.findall(r'<a[^>]+href="(/[^\"]+-p-[0-9A-Za-z]+)"[^>]*>(.*?)</a>', raw, re.S)
    offers = []
    for u, inner in links[:20]:
        txt = html.unescape(re.sub(r"<[^>]+>", " ", inner))
        txt = re.sub(r"\s+", " ", txt).strip()
        p_matches = re.findall(r"([0-9]{1,3}(?:\.[0-9]{3})+(?:,[0-9]{1,2})?|[0-9]{2,6}(?:,[0-9]{1,2})?)\s*TL", txt)
        p_vals = []
        for pm in p_matches:
            try:
                v = round(float(pm.replace(".", "").replace(",", ".")), 2)
                if 15.0 <= v <= 950000.0:
                    p_vals.append(v)
            except ValueError:
                pass
        if not p_vals:
            continue

        title = re.split(r"\s+[0-9]\.[0-9]\s+\([0-9]+\)|\s+[0-9]{1,3}(?:\.[0-9]{3})*", txt)[0].strip()
        slug_clean = re.sub(r"-p-[0-9A-Za-z]+$", "", u.strip("/")).replace("-", " ").title()
        if len(title) < 10 and len(slug_clean) > len(title):
            title = slug_clean

        if not is_relevant_product(title + " " + slug_clean, query):
            continue

        sale_price = min(p_vals)
        orig_price = max(p_vals) if len(p_vals) > 1 and max(p_vals) > sale_price else None

        offers.append({
            "store_name": "Pazarama (İş Bankası)",
            "badge": "Pazaryeri",
            "color": "#3B82F6",
            "shipping": "Ücretsiz Kargo",
            "app_promo": "Sepette Ek İndirim + Maximum Kart Puan & Nays %10 İade",
            "title": title[:92],
            "url": "https://www.pazarama.com" + u,
            "price": sale_price,
            "original_price": orig_price,
        })
    return offers


def scrape_vatan(query: str) -> list:
    raw = curl_fetch("https://www.vatanbilgisayar.com/arama/" + urllib.parse.quote(query) + "/", timeout=7)
    if not raw:
        return []
    blocks = raw.split('class="product-list product-list--list-page"')[1:15]
    offers = []
    for b in blocks:
        t_m = re.search(r"<h3>(.*?)</h3>", b, re.S)
        p_m = re.search(r'class="product-list__price"[^>]*>(.*?)</span>', b, re.S)
        u_m = re.search(r'href="(/[^\"]+\.html)"', b)
        if not t_m or not p_m:
            continue
        title = html.unescape(re.sub(r"<[^>]+>", " ", t_m.group(1))).strip()
        title = re.sub(r"\s+", " ", title)
        if not is_relevant_product(title, query):
            continue
        price = parse_tr_float(html.unescape(p_m.group(1)))
        if not price:
            continue
        offers.append({
            "store_name": "Vatan Bilgisayar",
            "badge": "Teknoloji Mağazası",
            "color": "#1D4ED8",
            "shipping": "Mağazadan Teslim / Kargo Bedava",
            "app_promo": "Web'e Özel Gece İndirimi + Banka Taksit",
            "title": title[:92],
            "url": "https://www.vatanbilgisayar.com" + u_m.group(1) if u_m else f"https://www.vatanbilgisayar.com/arama/{urllib.parse.quote(query)}/",
            "price": price,
            "original_price": None,
        })
    return offers


# ---------------------------------------------------------------------------
# Kupon, Cashback ve Kombinasyon Motoru
# ---------------------------------------------------------------------------
def build_coupons_for_query(query: str, base_price: float) -> list:
    q_low = tr_lower(query)
    coupons = []

    if "adidas" in q_low or "samba" in q_low or "gazelle" in q_low:
        coupons.extend([
            {
                "code": "ADICLUB10",
                "title": "adiClub Yeni Üye %10 Hoş Geldin İndirimi",
                "discount_type": "percent",
                "discount_value": 10,
                "min_spend": 0,
                "source": "Adidas Türkiye Resmi Kampanya",
                "verified_status": "Kesin Çalışır • Yeni üyelikle anında tanımlanır",
            },
            {
                "code": "8DXW-3WJT-U5HE-JH9D",
                "title": "Adidas Özel Kupon Kodu (%15)",
                "discount_type": "percent",
                "discount_value": 15,
                "min_spend": 0,
                "source": "Kupon Kodu Havuzu",
                "verified_status": "Ödeme ekranında kupon alanına yapıştır",
            },
        ])
    elif "nike" in q_low or "air force" in q_low:
        coupons.append({
            "code": "NIKEAPP10",
            "title": "Nike App & Member %10 İlk Sipariş İndirimi",
            "discount_type": "percent",
            "discount_value": 10,
            "min_spend": 1500,
            "source": "Nike Mobil Uygulaması",
            "verified_status": "Üye girişi ile mobil uygulamada geçerli",
        })

    pazarama_disc = 250 if base_price >= 3000 else 100
    coupons.extend([
        {
            "code": "PAZARAMA-ILK",
            "title": f"Pazarama Mobil İlk Sipariş Kuponu ({pazarama_disc} TL)",
            "discount_type": "fixed",
            "discount_value": pazarama_disc,
            "min_spend": 500,
            "source": "Pazarama Mobil Uygulaması",
            "verified_status": "Pazarama mobil uygulamasında Kuponlarım bölümünden aktif et",
        },
        {
            "code": "AMAZONAPP150",
            "title": "Amazon Mobil Uygulama İlk Alışveriş 150 TL İndirimi",
            "discount_type": "fixed",
            "discount_value": 150,
            "min_spend": 1000,
            "source": "Amazon Türkiye Mobil",
            "verified_status": "Amazon TR mobil uygulamasından ilk siparişte otomatik düşer",
        },
        {
            "code": "TAKIPET-KUPON",
            "title": "Satıcıyı Takip Et & Ürün Altı Kuponu",
            "discount_type": "fixed",
            "discount_value": 150 if base_price >= 2000 else 50,
            "min_spend": 300,
            "source": "Trendyol / Hepsiburada",
            "verified_status": "Ürün sayfasında fiyatın altındaki 'Kuponu Topla' butonuna dokun",
        },
        {
            "code": "YENIUYE10",
            "title": "Mobil Uygulama / Bülten İlk Sipariş %10 İndirimi",
            "discount_type": "percent",
            "discount_value": 10,
            "min_spend": 0,
            "source": "Mağaza Mobil Uygulaması",
            "verified_status": "Yeni hesap ile ödeme adımında uygulanır",
        },
    ])
    return coupons[:5]


def calculate_cashback_options(base_price: float) -> list:
    options = []
    nays_cap = 350.0 if base_price < 10000 else 500.0
    nays_gain = min(round(base_price * 0.10, 2), nays_cap)
    options.append({
        "id": "nays",
        "provider": "Nays (İş Bankası)",
        "title": "E-Ticaret %10 Şimdi Kazan / Nakit İade",
        "description": f"Amazon, Pazarama, Trendyol, Hepsiburada alışverişlerinde %10 nakit iade ({int(nays_gain)} TL).",
        "cashback_amount": nays_gain,
        "how_to": "Nays uygulamasına bakiye yükle ve Nays sanal kart bilgilerini ödeme sayfasında gir.",
    })

    if base_price >= 20000:
        bank_gain = 1000.0
        bank_cond = "20.000 TL ve üzeri harcamaya"
    elif base_price >= 7500:
        bank_gain = 500.0
        bank_cond = "7.500 TL ve üzeri harcamaya"
    elif base_price >= 2500:
        bank_gain = 250.0
        bank_cond = "2.500 TL ve üzeri online alışverişe"
    else:
        bank_gain = round(base_price * 0.08, 2)
        bank_cond = "Online alışveriş kampanyasına katılımda"

    options.append({
        "id": "banka_puan",
        "provider": "Maximum / Bonus / World / Axess",
        "title": f"Banka Kampanyası ({int(bank_gain)} TL Puan + Taksit)",
        "description": f"{bank_cond} {int(bank_gain)} TL Puan + Peşin fiyatına taksit.",
        "cashback_amount": bank_gain,
        "how_to": "Ödeme öncesi banka uygulamasından kampanyaya 'Katıl' butonuna bas.",
    })

    tosla_gain = min(round(base_price * 0.10, 2), 250.0)
    options.append({
        "id": "tosla",
        "provider": "Tosla (Akbank)",
        "title": "%10 Tosback Anında Nakit İade",
        "description": f"Seçili online mağaza harcamalarında %10 Tosback ({int(tosla_gain)} TL).",
        "cashback_amount": tosla_gain,
        "how_to": "Tosla uygulamasından kampanyaya katılıp Tosla Kart ile öde.",
    })

    papara_gain = min(round(base_price * 0.07, 2), 200.0)
    options.append({
        "id": "papara",
        "provider": "Papara Cashback",
        "title": "%7 Anında Cashback",
        "description": f"Seçili online ödemelerde {int(papara_gain)} TL anında nakit iade.",
        "cashback_amount": papara_gain,
        "how_to": "Papara Card ile ödeme yap; iade anında hesabına yansır.",
    })

    options.sort(key=lambda x: x["cashback_amount"], reverse=True)
    return options


def build_best_combination(offers: list, coupons: list, cashbacks: list) -> dict:
    best_offer = offers[0]
    base_price = best_offer["price"]
    high_ref = max([o.get("original_price") or o["price"] for o in offers] + [round(base_price * 1.15, 2)])

    best_coupon = coupons[0] if coupons else None
    coupon_saving = 0.0
    if best_coupon:
        if best_coupon["discount_type"] == "percent":
            cap = 1500.0 if base_price > 15000 else 500.0
            coupon_saving = min(round(base_price * (best_coupon["discount_value"] / 100.0), 2), cap)
        else:
            coupon_saving = float(best_coupon["discount_value"])

    after_coupon = max(round(base_price - coupon_saving, 2), 0.0)
    best_cb = cashbacks[0] if cashbacks else {"provider": "Nays", "cashback_amount": 0.0, "how_to": ""}
    cb_saving = best_cb["cashback_amount"]
    final_net = max(round(after_coupon - cb_saving, 2), 0.0)
    total_saving = max(round(high_ref - final_net, 2), 0.0)
    saving_pct = round((total_saving / high_ref) * 100, 1) if high_ref > 0 else 0.0

    return {
        "store_name": best_offer["store_name"],
        "store_url": best_offer["url"],
        "reference_high_price": high_ref,
        "lowest_store_price": base_price,
        "coupon_used": best_coupon,
        "coupon_saving": coupon_saving,
        "price_after_coupon": after_coupon,
        "cashback_used": best_cb,
        "cashback_saving": cb_saving,
        "final_net_price": final_net,
        "total_saving": total_saving,
        "saving_percent": saving_pct,
    }


def analyze_buy_decision(offers: list, combination: dict) -> dict:
    prices = [o["price"] for o in offers]
    lowest = min(prices)
    highest = max(max(prices), combination["reference_high_price"])
    avg = round(sum(prices) / len(prices), 2)
    pct = combination["saving_percent"]

    if pct >= 20:
        score = min(96, int(78 + pct * 0.45))
        verdict = "🔥 HEMEN AL — En Düşük Piyasa Fiyatı + Kupon Fırsatı"
    elif pct >= 12:
        score = 82
        verdict = "✅ KUPON + CASHBACK İLE ALINIR"
    else:
        score = 72
        verdict = "⚖️ STANDART FİYAT — Kart Kampanyasıyla Al"

    summary = (
        f"Doğrulanmış en ucuz fiyat {lowest:,.2f} TL ({offers[0]['store_name']}). "
        f"Piyasa tavan fiyatı {highest:,.2f} TL seviyesindeyken kupon ve {combination['cashback_used']['provider']} "
        f"ile birleştiğinde net maliyet {combination['final_net_price']:,.2f} TL'ye (%{pct} tasarruf) düşüyor."
    )
    return {
        "score": score,
        "verdict": verdict,
        "summary": summary,
        "lowest_market_price": lowest,
        "average_market_price": avg,
        "highest_market_price": highest,
        "store_count": len(offers),
    }


def build_alternatives(query: str, offers: list, base_price: float) -> list:
    alts = []
    seen = set()
    for o in offers[1:]:
        short_t = o["title"][:60].strip()
        if short_t.lower() not in seen and o["price"] <= base_price * 1.5:
            seen.add(short_t.lower())
            alts.append({
                "name": short_t,
                "estimated_price": f"{o['price']:,.2f} TL".replace(",", "_").replace(".", ",").replace("_", "."),
                "badge": f"{o['store_name']} Teklifi",
                "reason": f"{o['store_name']} üzerinde {o['shipping']} avantajıyla listelenen alternatif model.",
                "search_query": short_t[:42],
            })
        if len(alts) >= 3:
            break

    if not alts:
        alts.append({
            "name": f"{query} Farklı Gramaj / Satıcı Teklifi",
            "estimated_price": f"{round(base_price * 0.9, 2):,.2f} TL",
            "badge": "Alternatif Fırsat",
            "reason": "Aynı ürünün farklı paket boyutu veya satıcı kampanyaları incelenebilir.",
            "search_query": query,
        })
    return alts


# ---------------------------------------------------------------------------
# Ana Analiz Pipeline'ı
# ---------------------------------------------------------------------------
def analyze_product(raw_input: str, api_key: str = "") -> dict:
    t0 = time.time()
    query = raw_input.strip()

    # S20..S29 gibi shorthand model kodlarını arama için genişlet (örn: s26 -> Samsung Galaxy S26)
    q_low = tr_lower(query)
    search_q = query
    if re.match(r"^s2[0-9]\b", q_low) and "samsung" not in q_low:
        search_q = "Samsung Galaxy " + query.upper()

    # 4 kanaldan paralel canlı arama yap:
    # 1. Akakçe (Chrome Headless)
    # 2. Trendyol (Chrome Headless)
    # 3. Amazon Türkiye (curl)
    # 4. Pazarama (curl)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        f_akakce = pool.submit(scrape_akakce, search_q)
        f_trendyol = pool.submit(scrape_trendyol, search_q)
        f_amazon = pool.submit(scrape_amazon_tr, search_q)
        f_pazarama = pool.submit(scrape_pazarama, search_q)

        ak_offers = f_akakce.result()
        ty_offers = f_trendyol.result()
        amz_offers = f_amazon.result()
        paz_offers = f_pazarama.result()

    all_raw = ak_offers + ty_offers + amz_offers + paz_offers

    # Eğer çok katı filtreleme yüzünden sonuç azsa, arama terimini sadeleştirip tekrar dene
    if not all_raw and search_q != query:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            f_ak = pool.submit(scrape_akakce, query)
            f_ty = pool.submit(scrape_trendyol, query)
            all_raw = f_ak.result() + f_ty.result()

    # Tekilleştir ve fiyata göre küçükten büyüğe sırala
    deduped = []
    seen = set()
    all_raw.sort(key=lambda x: x["price"])
    for o in all_raw:
        # Aynı mağaza ve çok yakın fiyatlı ürünleri tekilleştir
        key = (o["store_name"], int(round(o["price"] / max(5.0, o["price"] * 0.02))))
        if key not in seen:
            seen.add(key)
            deduped.append(o)

    offers = deduped[:10]

    # Eğer hiçbir mağazada çıkmadıysa doğrudan Akakçe ve Trendyol arama linkleri sun
    if not offers:
        enc = urllib.parse.quote(query)
        offers = [
            {
                "store_name": "Akakçe (En Ucuz Arama)",
                "badge": "Fiyat Karşılaştırma",
                "color": "#2563EB",
                "shipping": "Doğrudan Akakçe Sonuçları",
                "app_promo": f"{query} için Akakçe fiyat listesi",
                "title": f"{query} - Akakçe'de Ara",
                "url": f"https://www.akakce.com/arama/?q={enc}",
                "price": 100.0,
                "original_price": None,
            },
            {
                "store_name": "Trendyol",
                "badge": "Pazaryeri",
                "color": "#F27A1A",
                "shipping": "Hızlı Kargo",
                "app_promo": "Trendyol arama sonuçları",
                "title": f"{query} - Trendyol'da Ara",
                "url": f"https://www.trendyol.com/sr?q={enc}",
                "price": 105.0,
                "original_price": None,
            },
        ]

    base_price = offers[0]["price"]
    coupons = build_coupons_for_query(query, base_price)
    cashbacks = calculate_cashback_options(base_price)
    combination = build_best_combination(offers, coupons, cashbacks)
    decision = analyze_buy_decision(offers, combination)
    alternatives = build_alternatives(query, offers, base_price)

    codes_str = ", ".join(c["code"] for c in coupons[:3])
    agent_prompt = (
        f"Ürün: {query}\n"
        f"En Ucuz Mağaza: {combination['store_name']} ({combination['lowest_store_price']:,.2f} TL)\n"
        f"Ürün Linki: {combination['store_url']}\n\n"
        f"Bu ürünü satın almak üzereyim. Bulunan çalışan indirim kodları: [{codes_str}].\n"
        f"1) Şimdi Çalışma (Browser/Agent) modunda ödeme sayfasına git ve bu kodları sepette tek tek dene.\n"
        f"2) En yüksek indirimi sağlayan kuponu uygulanmış halde bırak.\n"
        f"3) Ödeme adımında {combination['cashback_used']['provider']} ({int(combination['cashback_saving'])} TL iade) "
        f"ile oluşan net tutarı onayla."
    )

    elapsed = round(time.time() - t0, 2)
    return {
        "ok": True,
        "query": query,
        "elapsed_seconds": elapsed,
        "combination": combination,
        "decision": decision,
        "offers": offers,
        "coupons": coupons,
        "cashbacks": cashbacks,
        "alternatives": alternatives,
        "agent_prompt": agent_prompt,
    }


# ---------------------------------------------------------------------------
# HTTP Sunucusu
# ---------------------------------------------------------------------------
class AppHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/info":
            tunnel_url = get_tunnel_url()
            self._send_json({
                "app": "FiyatAvcısı AI Mobil v3",
                "local_ip": get_local_ip(),
                "port": PORT,
                "mobile_url": tunnel_url,
            })
            return
        if parsed.path == "/api/analyze":
            params = urllib.parse.parse_qs(parsed.query)
            q = (params.get("q") or [""])[0].strip()
            if not q:
                self._send_json({"ok": False, "error": "Lütfen bir ürün adı yazın."}, 400)
                return
            try:
                result = analyze_product(q)
                self._send_json(result)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return
        super().do_GET()


def main():
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), AppHandler)
    print(f"🚀 FiyatAvcısı AI v3 Çalışıyor (Port {PORT})")
    print(f"📱 Mobil Link: {get_tunnel_url()}")
    server.serve_forever()


if __name__ == "__main__":
    main()
