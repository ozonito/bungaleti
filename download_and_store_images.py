import os
import json
import hashlib
import urllib.request
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

script_dir = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(script_dir, "data.json")
IMG_DIR = os.path.join(script_dir, "images")

os.makedirs(IMG_DIR, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Referer": "https://www.google.com/"
}

def get_hash(url):
    return hashlib.md5(url.encode('utf-8')).hexdigest()[:10]

def save_image_file(image_url, filepath):
    try:
        req = urllib.request.Request(image_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
        })
        with urllib.request.urlopen(req, timeout=12) as response, open(filepath, 'wb') as out_file:
            out_file.write(response.read())
        return True
    except Exception as e:
        print(f"    Error guardando archivo {image_url}: {e}")
        return False

def extract_photo_from_page(page, url):
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=25000)
        page.wait_for_timeout(1500)
        
        # Buscar og:image
        meta_img = page.query_selector('meta[property="og:image"], meta[name="og:image"]')
        if meta_img:
            content = meta_img.get_attribute("content")
            if content and "logo" not in content.lower():
                return content

        # Buscar primera imagen grande de galería
        images = page.query_selector_all('img')
        for img in images:
            src = img.get_attribute("src") or img.get_attribute("data-src")
            if src and ("multimedia" in src or "foto" in src or "xl" in src or "ads" in src) and "logo" not in src.lower():
                return src if src.startswith("http") else f"https:{src}"
    except Exception as e:
        print(f"    Error navegando a {url}: {e}")
    return None

def main():
    if not os.path.exists(DATA_FILE):
        print("No se encontró data.json")
        return

    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        items = json.load(f)

    print(f"Descargando imágenes reales físicamente para {len(items)} inmuebles/garajes...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800}
        )
        page = context.new_page()
        Stealth().apply_stealth_sync(page)

        saved_count = 0
        for idx, item in enumerate(items):
            url = item.get("enlace", "")
            title = item.get("titulo", "")
            
            img_filename = f"prop_{idx+1}_{get_hash(url)}.jpg"
            img_filepath = os.path.join(IMG_DIR, img_filename)
            rel_img_path = f"images/{img_filename}"

            print(f"[{idx+1}/{len(items)}] Navegando al anuncio: {title[:45]}...")

            target_img_url = extract_photo_from_page(page, url)

            if target_img_url and target_img_url.startswith("http"):
                print(f"  -> Foto remota encontrada: {target_img_url[:60]}...")
                if save_image_file(target_img_url, img_filepath):
                    item["imagen"] = rel_img_path
                    saved_count += 1
                    print(f"  -> [OK] Guardada imagen física en: {rel_img_path}")
                else:
                    item["imagen"] = ""
            else:
                print("  -> No se pudo extraer imagen directa.")
                item["imagen"] = ""

        browser.close()

    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

    print(f"\n¡Descarga completada! {saved_count} fotos físicas guardadas en 'images/'.")

if __name__ == "__main__":
    main()

