import os
import re
import sys
import time
import json
import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
from bs4 import BeautifulSoup

# Configurar encoding de salida para la consola de Windows
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Cargar variables de entorno relativas al directorio del script
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(script_dir, '.env'))


SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "ozonito@gmail.com")

SEEN_FILE = os.path.join(script_dir, "seen_properties.json")

# Criterios de búsqueda multi-portal:
# 1. Viviendas en Sonnenland / Maspalomas (máx 300.000€, 35-100m²)
# 2. Plazas de garaje en San Agustín / Avda. de los Jazmines (Cualquier precio)

SEARCH_TARGETS = [
    # Fotocasa
    {"portal": "Fotocasa", "zone": "Sonnenland (Viviendas)", "url": "https://www.fotocasa.es/es/comprar/viviendas/san-bartolome-de-tirajana/sonnenland/l", "type": "vivienda"},
    {"portal": "Fotocasa", "zone": "Maspalomas (Viviendas)", "url": "https://www.fotocasa.es/es/comprar/viviendas/san-bartolome-de-tirajana/maspalomas-campo-de-golf/l", "type": "vivienda"},
    {"portal": "Fotocasa", "zone": "San Agustín (Garajes)", "url": "https://www.fotocasa.es/es/comprar/garajes/san-bartolome-de-tirajana/san-agustin/l", "type": "garaje"},
    
    # Pisos.com
    {"portal": "Pisos.com", "zone": "Sonnenland / Maspalomas (Viviendas)", "url": "https://www.pisos.com/venta/casas_pisos-san_bartolome_de_tirajana/", "type": "vivienda"},
    {"portal": "Pisos.com", "zone": "San Agustín (Garajes)", "url": "https://www.pisos.com/venta/garajes-san_bartolome_de_tirajana/", "type": "garaje"},

    # Habitaclia
    {"portal": "Habitaclia", "zone": "San Bartolomé (Viviendas)", "url": "https://www.habitaclia.com/comprar-vivienda-en-san_bartolome_de_tirajana/buscador.htm", "type": "vivienda"},
    {"portal": "Habitaclia", "zone": "San Agustín (Garajes)", "url": "https://www.habitaclia.com/comprar-garaje-en-san_bartolome_de_tirajana/buscador.htm", "type": "garaje"},

    # YaEncontre
    {"portal": "YaEncontre", "zone": "San Bartolomé (Viviendas)", "url": "https://www.yaencontre.com/venta/viviendas/san-bartolome-de-tirajana", "type": "vivienda"},

    # Idealista
    {"portal": "Idealista", "zone": "Sonnenland (Viviendas)", "url": "https://www.idealista.com/venta-viviendas/san-bartolome-de-tirajana/sonnenland/con-precio-hasta_300000,precio-desde_150000/", "type": "vivienda"},
    {"portal": "Idealista", "zone": "Maspalomas (Viviendas)", "url": "https://www.idealista.com/venta-viviendas/san-bartolome-de-tirajana/maspalomas-campo-de-golf/con-precio-hasta_300000,precio-desde_150000/", "type": "vivienda"},
    {"portal": "Idealista", "zone": "San Agustín (Garajes)", "url": "https://www.idealista.com/garajes-venta/san-bartolome-de-tirajana/san-agustin/", "type": "garaje"}
]

def load_seen_urls():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except Exception as e:
            print(f"Error leyendo {SEEN_FILE}: {e}")
    return set()

def save_seen_urls(seen_set):
    try:
        with open(SEEN_FILE, 'w', encoding='utf-8') as f:
            json.dump(list(seen_set), f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error guardando {SEEN_FILE}: {e}")

def clean_text(text):
    if not text:
        return ""
    text = re.sub(r'[\u200b\u200c\u200d\ufeff]', '', text)
    return re.sub(r'\s+', ' ', text).strip()

def check_compatibility(card_text, item_type="vivienda"):
    """
    Filtro de compatibilidad:
    - Garaje: Exclusivo en San Agustín (Av. los Jazmines y alrededores). Acepta cualquier precio.
    - Vivienda: Sonnenland / Maspalomas, Máx 300.000 €, superficie 35m² - 100m².
    """
    text_lower = card_text.lower()

    if item_type == "garaje":
        # Descartar localidades lejanas devueltas por los portales en búsquedas amplias
        for exc in ["vecindario", "doctoral", "sardina", "mogan", "arguineguin", "santa lucia"]:
            if exc in text_lower:
                return False
        return True

    # Comprobar precio para viviendas
    price_match = re.search(r'(\d[\d\.]*)\s*€', card_text)
    if price_match:
        try:
            price_val = int(price_match.group(1).replace('.', ''))
            if price_val > 300000 or price_val < 100000:
                return False
        except ValueError:
            pass

    # Comprobar tamaño para viviendas si se indica
    size_match = re.search(r'(\d+)\s*(?:m²|m2)', card_text, re.I)
    if size_match:
        try:
            size_val = int(size_match.group(1))
            if size_val < 30 or size_val > 110:
                return False
        except ValueError:
            pass

    return True


def parse_articles(soup, portal_name, zone, item_type, seen_urls):
    results = []
    
    if portal_name == "Idealista":
        articles = soup.select("article.item")
        for art in articles:
            try:
                link_el = art.select_one(".item-link")
                if not link_el: continue
                title = clean_text(link_el.text)
                href = link_el.get("href", "")
                link = f"https://www.idealista.com{href}" if href.startswith("/") else href
                if link in seen_urls: continue
                price_el = art.select_one(".item-price")
                price = clean_text(price_el.text) if price_el else "No especificado"
                details_el = art.select(".item-detail")
                details = ", ".join([clean_text(d.text) for d in details_el]) if details_el else ""
                if check_compatibility(f"{title} {price} {details} {art.text}", item_type):
                    results.append({"portal": portal_name, "zona": zone, "tipo": item_type, "titulo": title, "precio": price, "detalles": details, "enlace": link})
            except Exception: pass

    elif portal_name == "Fotocasa":
        articles = soup.select("article, div[class*='Card'], article[class*='Card']")
        for art in articles:
            try:
                link_el = art.select_one("a")
                if not link_el: continue
                href = link_el.get("href", "")
                if not href or ("/comprar/" not in href and "/es/comprar/" not in href):
                    for l in art.select("a"):
                        h = l.get("href", "")
                        if "/comprar/" in h or "/es/comprar/" in h:
                            link_el = l; href = h; break
                if not href: continue
                link = f"https://www.fotocasa.es{href}" if href.startswith("/") else href
                if link in seen_urls: continue
                title_el = art.select_one("h2, h3, [class*='title']")
                title = clean_text(title_el.text) if title_el else clean_text(link_el.text)
                if not title: title = f"Inmueble en {zone}"
                price_el = art.select_one('[class*="price"], [class*="Price"]')
                price = clean_text(price_el.text) if price_el else "No especificado"
                details_el = art.select('[class*="features"], [class*="Features"], [class*="detail"]')
                details = ", ".join([clean_text(d.text) for d in details_el]) if details_el else ""
                if check_compatibility(f"{title} {price} {details} {art.text}", item_type):
                    if not any(r["enlace"] == link for r in results):
                        results.append({"portal": portal_name, "zona": zone, "tipo": item_type, "titulo": title, "precio": price, "detalles": details, "enlace": link})
            except Exception: pass

    elif portal_name == "Pisos.com":
        articles = soup.select("div.grid-search-element, div.ad-preview, div[class*='ad-preview']")
        for art in articles:
            try:
                link_el = art.select_one("a.ad-preview__title, a.title, a[href*='/venta/'], a[href*='/comprar/']")
                if not link_el: continue
                href = link_el.get("href", "")
                link = f"https://www.pisos.com{href}" if href.startswith("/") else href
                if link in seen_urls: continue
                title = clean_text(link_el.text)
                price_el = art.select_one(".ad-preview__price, .price, [class*='price']")
                price = clean_text(price_el.text) if price_el else "No especificado"
                details_el = art.select(".ad-preview__characteristics, .characteristics, [class*='charac']")
                details = ", ".join([clean_text(d.text) for d in details_el]) if details_el else ""
                if check_compatibility(f"{title} {price} {details} {art.text}", item_type):
                    if not any(r["enlace"] == link for r in results):
                        results.append({"portal": portal_name, "zona": zone, "tipo": item_type, "titulo": title, "precio": price, "detalles": details, "enlace": link})
            except Exception: pass

    elif portal_name == "Habitaclia":
        articles = soup.select("article.list-item, section.list-item, div.list-item-info")
        for art in articles:
            try:
                link_el = art.select_one("a.list-item-title, a[href*='comprar']")
                if not link_el: continue
                href = link_el.get("href", "")
                link = f"https://www.habitaclia.com{href}" if href.startswith("/") else href
                if link in seen_urls: continue
                title = clean_text(link_el.text)
                price_el = art.select_one(".price, span.font-2, [class*='price']")
                price = clean_text(price_el.text) if price_el else "No especificado"
                details_el = art.select(".list-item-feature, p.list-item-description")
                details = ", ".join([clean_text(d.text) for d in details_el]) if details_el else ""
                if check_compatibility(f"{title} {price} {details} {art.text}", item_type):
                    if not any(r["enlace"] == link for r in results):
                        results.append({"portal": portal_name, "zona": zone, "tipo": item_type, "titulo": title, "precio": price, "detalles": details, "enlace": link})
            except Exception: pass

    elif portal_name == "YaEncontre":
        articles = soup.select("article, div[class*='property-card']")
        for art in articles:
            try:
                link_el = art.select_one("a[href*='/venta/'], a[href*='/alquiler/']")
                if not link_el: continue
                href = link_el.get("href", "")
                link = f"https://www.yaencontre.com{href}" if href.startswith("/") else href
                if link in seen_urls: continue
                title_el = art.select_one("h2, h3, [class*='title']")
                title = clean_text(title_el.text) if title_el else clean_text(link_el.text)
                price_el = art.select_one("[class*='price']")
                price = clean_text(price_el.text) if price_el else "No especificado"
                if check_compatibility(f"{title} {price} {art.text}", item_type):
                    if not any(r["enlace"] == link for r in results):
                        results.append({"portal": portal_name, "zona": zone, "tipo": item_type, "titulo": title, "precio": price, "detalles": "", "enlace": link})
            except Exception: pass

    return results

def scrape_multi_portal(p, targets, seen_urls):
    print("=== INICIANDO BÚSQUEDA MULTI-PORTAL (FOTOCASA, PISOS.COM, HABITACLIA, YAENCONTRE, IDEALISTA) ===")
    all_results = []
    
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-web-security"
        ]
    )
    
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        viewport={"width": 1366, "height": 768},
        locale="es-ES",
        timezone_id="Atlantic/Canary",
        extra_http_headers={
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"'
        }
    )
    
    page = context.new_page()
    Stealth().apply_stealth_sync(page)
    
    for item in targets:
        portal_name = item["portal"]
        zone = item["zone"]
        url = item["url"]
        item_type = item["type"]
        
        print(f"Consultando [{portal_name}] - {zone}...")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(2 + int(time.time() % 3))
            
            page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2);")
            time.sleep(1)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            if portal_name == "Idealista":
                if "blocked" in page.url or soup.find(string=re.compile("error 403|captcha|human", re.I)):
                    print(f"  [AVISO] Detectado captcha/bloqueo en Idealista para {zone}. Saltando...")
                    continue
                    
            res = parse_articles(soup, portal_name, zone, item_type, seen_urls)
            print(f"  -> Encontrados {len(res)} nuevos inmuebles target en [{portal_name}] ({zone}).")
            all_results.extend(res)
            
        except Exception as e:
            print(f"  [AVISO] Error consultando {portal_name} ({zone}): {e}")
            
    browser.close()
    return all_results



def send_email(subject, html_content, text_content):
    if not SMTP_USER or not SMTP_PASSWORD or SMTP_USER == "tu_correo@gmail.com" or SMTP_PASSWORD == "tu_contrasena_de_aplicacion":
        print("\n[AVISO] No se han configurado las credenciales reales de correo en .env.")
        print("Por favor, introduce tu correo SMTP y contraseña en el archivo .env para enviar los mails automáticos.")
        print("\nContenido del mensaje que se habría enviado:\n")
        print(text_content)
        return False
        
    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = SMTP_USER
        msg['To'] = EMAIL_TO
        msg['Subject'] = Header(subject, 'utf-8')
        
        msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
        server.quit()
        print("Correo electrónico enviado con éxito a:", EMAIL_TO)
        return True
    except Exception as e:
        print(f"[ERROR] Error al enviar el correo electrónico: {e}")
        return False

DATA_JSON_FILE = os.path.join(script_dir, "data.json")

def load_all_properties():
    if os.path.exists(DATA_JSON_FILE):
        try:
            with open(DATA_JSON_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error leyendo {DATA_JSON_FILE}: {e}")
    return []

def save_all_properties(items):
    try:
        with open(DATA_JSON_FILE, 'w', encoding='utf-8') as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        print(f"Actualizado {DATA_JSON_FILE} con {len(items)} inmuebles/garajes.")
    except Exception as e:
        print(f"Error guardando {DATA_JSON_FILE}: {e}")

def update_github_repo():
    """Intenta hacer commit y push si hay un repositorio de Git/GitHub configurado."""
    try:
        if os.path.exists(os.path.join(script_dir, ".git")):
            print("Sincronizando cambios con GitHub...")
            os.system(f'git -C "{script_dir}" add data.json index.html')
            os.system(f'git -C "{script_dir}" commit -m "Actualizacion automatica de inmuebles [ci skip]"')
            os.system(f'git -C "{script_dir}" push')
            print("Sincronización con GitHub completada.")
    except Exception as e:
        print(f"Aviso en sincronización Git: {e}")

def main():
    print("=== INICIANDO BÚSQUEDA MULTI-PORTAL PARA LA WEB EN GITHUB ===")
    
    existing_items = load_all_properties()
    seen_urls = set(item["enlace"] for item in existing_items)
    print(f"Historial cargado: {len(existing_items)} inmuebles/garajes en la web.")
    
    with sync_playwright() as p:
        new_results = scrape_multi_portal(p, SEARCH_TARGETS, seen_urls)
        
    if new_results:
        print(f"\n¡Se han añadido {len(new_results)} nuevos inmuebles a la web!")
        existing_items = new_results + existing_items
        save_all_properties(existing_items)
        update_github_repo()
    else:
        print("\nNo hay nuevas ofertas. La web se mantiene actualizada.")
        # Guardar por si se inicializó data.json de cero
        if not os.path.exists(DATA_JSON_FILE):
            save_all_properties(existing_items)

if __name__ == "__main__":
    main()


