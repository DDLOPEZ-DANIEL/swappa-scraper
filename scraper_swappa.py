import asyncio
import os
import re
import json
import sys
import requests
from datetime import datetime, timedelta
import zoneinfo
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

sys.stdout.reconfigure(line_buffering=True)

# URL por defecto (Actualízala con la nueva URL de tu dominio en la variable de entorno BASE44_WEBHOOK_URL)
BASE44_WEBHOOK_URL = os.getenv(
    "BASE44_WEBHOOK_URL", 
    "https://rebit-ad09a6b3.base44.app/functions/swappaWebhook"
)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")

MAX_PUBLICATIONS_PER_MODEL = int(os.getenv("MAX_PUBLICATIONS_PER_MODEL", "0"))

EXCLUDE_KEYWORDS = [
    "printer", "rtx", "gtx", "geforce", "radeon", "graphics card", 
    "desktop", "optiplex", "prodesk", "ally", "legion go", "xg mobile", "vision pro"
]

TARGET_URLS = [
    {"categoria": "Celular", "brand": "Apple", "url": "https://swappa.com/buy/unlocked/iphones"},
    {"categoria": "Celular", "brand": "Samsung", "url": "https://swappa.com/buy/unlocked/samsung"},
    {"categoria": "Celular", "brand": "Google", "url": "https://swappa.com/buy/unlocked/google"},
    {"categoria": "Laptop", "brand": "Apple", "url": "https://swappa.com/buy/macbooks"},
    {"categoria": "Laptop", "brand": "Dell", "url": "https://swappa.com/buy/b/dell"},
    {"categoria": "Laptop", "brand": "HP", "url": "https://swappa.com/buy/b/hp"},
    {"categoria": "Laptop", "brand": "Lenovo", "url": "https://swappa.com/buy/b/lenovo"},
    {"categoria": "Laptop", "brand": "Asus", "url": "https://swappa.com/buy/b/asus"}
]

async def extraer_detalles_json_ld(context, listing_url):
    datos_producto = {
        "swappa_id": "",
        "title": "",
        "description": "",
        "cost_price": 0.0,
        "color": "",
        "seller": "",
        "catalog_image": "",
        "gallery_images": [],
        "is_available": True
    }
    
    try:
        detail_page = await context.new_page()
        await detail_page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(0.5)
        content = await detail_page.content()
        soup = BeautifulSoup(content, 'html.parser')

        text_content_lower = soup.get_text().lower()
        sold_indicators = ["listing sold", "this listing has been sold", "out of stock", "no longer available"]
        status_badges = soup.select(".badge, .status, .label, .listing-status")
        badge_text = " ".join([b.get_text().lower() for b in status_badges])
        
        if any(ind in text_content_lower for ind in sold_indicators) or "sold" in badge_text:
            datos_producto["is_available"] = False
            await detail_page.close()
            return datos_producto

        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                schema_data = json.loads(script.string)
                if isinstance(schema_data, dict) and schema_data.get("@type") in ["Product", "IndividualProduct", "Offer"]:
                    datos_producto["swappa_id"] = str(schema_data.get("productID") or schema_data.get("sku") or listing_url.split("/")[-1])
                    datos_producto["title"] = schema_data.get("name", "")
                    datos_producto["color"] = schema_data.get("color", "")
                    
                    img = schema_data.get("image")
                    if isinstance(img, list) and img:
                        datos_producto["catalog_image"] = img[0]
                    elif isinstance(img, str):
                        datos_producto["catalog_image"] = img

                    if "offers" in schema_data:
                        offers = schema_data["offers"]
                        if isinstance(offers, dict):
                            datos_producto["cost_price"] = float(offers.get("price", 0.0))
                            datos_producto["seller"] = offers.get("seller", {}).get("name", "")
                            if offers.get("availability", "").endswith("OutOfStock") or offers.get("availability", "").endswith("SoldOut"):
                                datos_producto["is_available"] = False
                        elif isinstance(offers, list) and len(offers) > 0:
                            datos_producto["cost_price"] = float(offers[0].get("price", 0.0))
                            datos_producto["seller"] = offers[0].get("seller", {}).get("name", "")
                    break
            except Exception:
                continue

        desc_parts = []
        attr_elements = soup.select(".attrs .attr, .listing-attrs .attr, .specs .spec, .tech-specs .spec")
        if attr_elements:
            attrs_text = " - ".join([a.get_text(strip=True) for a in attr_elements if a.get_text(strip=True)])
            if attrs_text:
                desc_parts.append(f"Atributos / Especificaciones del equipo: {attrs_text}")

        headline_elem = soup.select_one("#section_headline, .headline, #seller_notes, .listing-description, #listing_description, .seller-notes")
        if headline_elem:
            text_hl = headline_elem.get_text(separator=" ", strip=True)
            if text_hl and text_hl not in desc_parts:
                desc_parts.append(f"Notas del vendedor: {text_hl}")

        damage_elem = soup.select_one("#seller_damage_description, .damage-description, #section_description, .condition-notes")
        if damage_elem:
            text_dmg = damage_elem.get_text(separator=" ", strip=True)
            if text_dmg and text_dmg not in desc_parts:
                desc_parts.append(f"Detalles adicionales / Estado estético: {text_dmg}")

        if not desc_parts:
            meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta_desc and meta_desc.get("content"):
                desc_parts.append(meta_desc["content"].strip())

        datos_producto["description"] = "\n\n".join(desc_parts) if desc_parts else "Sin descripción provista por el vendedor."

        if datos_producto["cost_price"] <= 0:
            price_elem = soup.select_one("span.price, .listing-price, [itemprop='price'], .price, .val-price")
            if price_elem:
                raw_price = re.sub(r'[^\d.]', '', price_elem.text)
                if raw_price:
                    datos_producto["cost_price"] = float(raw_price)

        if not datos_producto["title"]:
            title_elem = soup.select_one("h1, .listing-title, title")
            if title_elem:
                datos_producto["title"] = title_elem.text.strip().split(" - ")[0]

        images = []
        for a in soup.select('#section_media a.lightbox, #section_media a[href*="/media/listing/"]'):
            href = a.get('href') or ''
            if href.startswith('//'):
                href = 'https:' + href
            if '/media/listing/' in href and href not in images:
                images.append(href)

        if not images:
            for img in soup.find_all('img'):
                src = img.get('src') or img.get('data-src') or ''
                if src.startswith('//'):
                    src = 'https:' + src
                if '/media/listing/' in src and src not in images:
                    images.append(src)

        datos_producto["gallery_images"] = images
        await detail_page.close()
    except Exception as e:
        print(f"      [!] Error leyendo detalle en {listing_url}: {e}", flush=True)
        
    return datos_producto

async def extraer_producto_objeto(context, surl, categoria, brand):
    try:
        detalles = await extraer_detalles_json_ld(context, surl)
        if not detalles["is_available"] or detalles["cost_price"] <= 0:
            return None

        title_text = detalles["title"] or f"{brand} {categoria}"
        if any(k in title_text.lower() for k in EXCLUDE_KEYWORDS):
            return None

        storage = "N/A"
        match_storage = re.search(r'\b(64|128|256|512|1|2)\s*(GB|TB)\b', title_text, re.I)
        if match_storage:
            storage = match_storage.group(0)

        galeria = detalles["gallery_images"]
        main_image = galeria[0] if galeria else detalles["catalog_image"]

        return {
            "swappa_id": detalles["swappa_id"] or surl.split("/")[-1],
            "title": title_text,
            "brand": brand,
            "category": categoria,
            "condition": "Used",
            "color": detalles["color"] or "N/A",
            "seller": detalles["seller"] or "Swappa Seller",
            "cost_price": detalles["cost_price"],
            "storage": storage,
            "description": detalles["description"],
            "image_url": main_image,
            "images": galeria,
            "source_url": surl,
            "status": "Available"
        }
    except Exception as e:
        print(f"      [!] Error procesando objeto {surl}: {e}", flush=True)
        return None

async def ejecutar_extraccion_diaria():
    print("Iniciando escaneo masivo de Swappa hacia Base44...", flush=True)
    productos_recolectados = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()

        for target in TARGET_URLS:
            categoria = target["categoria"]
            brand = target["brand"]
            target_url = target["url"]
            
            try:
                print(f"\n=======================================================", flush=True)
                print(f" Escaneando {categoria}s ({brand}) en: {target_url}", flush=True)
                print(f"=======================================================", flush=True)
                
                response = await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                if not response or response.status != 200:
                    continue

                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1000);")
                    await asyncio.sleep(1)

                links = await page.query_selector_all("a[href]")
                found_urls = []

                for l in links:
                    href = await l.get_attribute("href")
                    if href:
                        full_url = "https://swappa.com" + href if href.startswith("/") else href
                        if any(pattern in full_url for pattern in ["/buy/", "/listing/", "/listings/"]):
                            if full_url not in found_urls and full_url != target_url and not full_url.endswith("/buy"):
                                found_urls.append(full_url)

                for source_url in found_urls:
                    if "/listing/" in source_url and "/buy/" not in source_url:
                        p_obj = await extraer_producto_objeto(context, source_url, categoria, brand)
                        if p_obj:
                            productos_recolectados.append(p_obj)
                    else:
                        try:
                            model_page = await context.new_page()
                            await model_page.goto(source_url, wait_until="domcontentloaded", timeout=25000)
                            await asyncio.sleep(1)
                            await model_page.evaluate("window.scrollBy(0, 800);")
                            await asyncio.sleep(0.5)

                            sub_links = await model_page.query_selector_all("a[href*='/listing/']")
                            sub_urls = []
                            for sl in sub_links:
                                shref = await sl.get_attribute("href")
                                if shref:
                                    surl = "https://swappa.com" + shref if shref.startswith("/") else shref
                                    if surl not in sub_urls:
                                        sub_urls.append(surl)

                            sub_urls_to_process = sub_urls if MAX_PUBLICATIONS_PER_MODEL <= 0 else sub_urls[:MAX_PUBLICATIONS_PER_MODEL]

                            for surl in sub_urls_to_process:
                                p_obj = await extraer_producto_objeto(context, surl, categoria, brand)
                                if p_obj:
                                    productos_recolectados.append(p_obj)

                            await model_page.close()
                        except Exception:
                            continue

            except Exception as nav_error:
                print(f"Error procesando sección {target_url}: {nav_error}", flush=True)

        await browser.close()

        # ENVÍO EN LOTE (RECONCILE) A BASE44
        print(f"\n[ENVIANDO LOTE] Total de productos recolectados: {len(productos_recolectados)}", flush=True)
        if productos_recolectados:
            try:
                headers = {"Content-Type": "application/json", "x-api-key": SCRAPER_API_KEY}
                res = requests.post(BASE44_WEBHOOK_URL, json=productos_recolectados, headers=headers, timeout=60)
                print(f"[BASE44 RES] Código: {res.status_code} | Respuesta: {res.text}", flush=True)
            except Exception as req_err:
                print(f"[!] Error enviando lote a Base44: {req_err}", flush=True)

async def esperar_hasta_10_30_pm():
    tz_nicaragua = zoneinfo.ZoneInfo("America/Managua")
    ahora = datetime.now(tz_nicaragua)
    meta = ahora.replace(hour=22, minute=30, second=0, microsecond=0)
    if ahora >= meta:
        meta += timedelta(days=1)
    segundos_espera = (meta - ahora).total_seconds()
    print(f"\n[PROGRAMADO] Esperando {segundos_espera / 3600:.2f} horas...", flush=True)
    await asyncio.sleep(segundos_espera)

async def main():
    while True:
        await ejecutar_extraccion_diaria()
        await esperar_hasta_10_30_pm()

if __name__ == "__main__":
    asyncio.run(main())