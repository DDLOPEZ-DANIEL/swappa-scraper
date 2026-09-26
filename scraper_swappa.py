import asyncio
import os
import re
import json
import sys
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Forzar salida en vivo en la consola de Docker / Railway
sys.stdout.reconfigure(line_buffering=True)

BASE44_WEBHOOK_URL = os.getenv(
    "BASE44_WEBHOOK_URL", 
    "https://rebit-smart-grid.base44.app/functions/swappaWebhook"
)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")
MARGEN_GANANCIA = 1.30

# Límite por modelo: 0 significa SIN LÍMITE (extrae todas las publicaciones encontradas)
MAX_PUBLICATIONS_PER_MODEL = int(os.getenv("MAX_PUBLICATIONS_PER_MODEL", "0"))

EXCLUDE_KEYWORDS = [
    "printer", "rtx", "gtx", "geforce", "radeon", "graphics card", 
    "desktop", "optiplex", "prodesk", "ally", "legion go", "xg mobile"
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
        "gallery_images": []
    }
    
    try:
        detail_page = await context.new_page()
        await detail_page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(0.5)
        content = await detail_page.content()
        soup = BeautifulSoup(content, 'html.parser')

        # Extraer datos JSON-LD estructurados
        json_ld_scripts = soup.find_all('script', type='application/ld+json')
        for script in json_ld_scripts:
            if not script.string:
                continue
            try:
                schema_data = json.loads(script.string)
                if isinstance(schema_data, dict) and schema_data.get("@type") in ["Product", "IndividualProduct", "Offer"]:
                    datos_producto["swappa_id"] = str(schema_data.get("productID") or schema_data.get("sku") or listing_url.split("/")[-1])
                    datos_producto["title"] = schema_data.get("name", "")
                    datos_producto["description"] = schema_data.get("description", "")
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
                        elif isinstance(offers, list) and len(offers) > 0:
                            datos_producto["cost_price"] = float(offers[0].get("price", 0.0))
                            datos_producto["seller"] = offers[0].get("seller", {}).get("name", "")
                    break
            except Exception:
                continue

        # Fallback de precio en el DOM
        if datos_producto["cost_price"] <= 0:
            price_elem = soup.select_one("span.price, .listing-price, [itemprop='price'], .price")
            if price_elem:
                raw_price = re.sub(r'[^\d.]', '', price_elem.text)
                if raw_price:
                    datos_producto["cost_price"] = float(raw_price)

        # Extraer Galería de Fotos Reales
        images = []
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if src.startswith('//'):
                src = 'https:' + src
            if ('/media/listing/' in src or 'static.swappa.com/media/' in src or '/listing/' in src) and src not in images:
                images.append(src)

        datos_producto["gallery_images"] = images
        await detail_page.close()
    except Exception as e:
        print(f"      [!] Error leyendo detalle en {listing_url}: {e}", flush=True)
        
    return datos_producto

async def ejecutar_extraccion_diaria():
    print("Iniciando escaneo masivo de Swappa hacia Base44...", flush=True)
    if MAX_PUBLICATIONS_PER_MODEL <= 0:
        print("Modo de extracción: TODAS las publicaciones encontradas (Sin límite).", flush=True)
    else:
        print(f"Modo de extracción: Máximo {MAX_PUBLICATIONS_PER_MODEL} publicaciones por modelo.", flush=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox"
            ]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()
        total_enviados = 0

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
                    print(f" [!] No se pudo acceder a la URL: Status {response.status if response else 'None'}", flush=True)
                    continue

                for _ in range(3):
                    await page.evaluate("window.scrollBy(0, 1000);")
                    await asyncio.sleep(1)

                links = await page.query_selector_all("a[href*='/listing/'], a[href*='/buy/']")
                found_urls = []

                for l in links:
                    href = await l.get_attribute("href")
                    if href:
                        full_url = "https://swappa.com" + href if href.startswith("/") else href
                        if full_url not in found_urls and full_url != target_url and not full_url.endswith("/buy"):
                            found_urls.append(full_url)

                print(f" -> Se encontraron {len(found_urls)} enlaces a procesar.", flush=True)

                for source_url in found_urls:
                    try:
                        if "/listing/" not in source_url:
                            try:
                                model_page = await context.new_page()
                                await model_page.goto(source_url, wait_until="domcontentloaded", timeout=25000)
                                await asyncio.sleep(0.8)
                                sub_links = await model_page.query_selector_all("a[href*='/listing/']")
                                
                                # Aplicar o ignorar el límite según MAX_PUBLICATIONS_PER_MODEL
                                sub_links_to_process = sub_links if MAX_PUBLICATIONS_PER_MODEL <= 0 else sub_links[:MAX_PUBLICATIONS_PER_MODEL]

                                for sl in sub_links_to_process:
                                    shref = await sl.get_attribute("href")
                                    if shref:
                                        surl = "https://swappa.com" + shref if shref.startswith("/") else shref
                                        
                                        detalles = await extraer_detalles_json_ld(context, surl)
                                        cost_price = detalles["cost_price"]
                                        if cost_price <= 0:
                                            continue

                                        title_text = detalles["title"] or f"{brand} {categoria}"
                                        if any(k in title_text.lower() for k in EXCLUDE_KEYWORDS):
                                            continue

                                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)
                                        storage = "N/A"
                                        match_storage = re.search(r'\b(64|128|256|512|1|2)\s*(GB|TB)\b', title_text, re.I)
                                        if match_storage:
                                            storage = match_storage.group(0)

                                        galeria = detalles["gallery_images"]
                                        main_image = galeria[0] if galeria else detalles["catalog_image"]

                                        producto = {
                                            "swappa_id": detalles["swappa_id"] or surl.split("/")[-1],
                                            "title": title_text,
                                            "brand": brand,
                                            "category": categoria,
                                            "condition": "Used",
                                            "color": detalles["color"] or "N/A",
                                            "seller": detalles["seller"] or "Swappa Seller",
                                            "cost_price": cost_price,
                                            "sale_price": sale_price,
                                            "storage": storage,
                                            "description": detalles["description"],
                                            "image_url": main_image,
                                            "images": galeria,
                                            "source_url": surl,
                                            "status": "Available"
                                        }

                                        headers = {"Content-Type": "application/json", "x-api-key": SCRAPER_API_KEY}
                                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                                        total_enviados += 1
                                        print(f"[{total_enviados}] [{categoria} - {brand}] {title_text} | $${cost_price} -> $${sale_price} | Base44: {res.status_code}", flush=True)

                                await model_page.close()
                            except Exception as model_err:
                                continue
                        else:
                            detalles = await extraer_detalles_json_ld(context, source_url)
                            cost_price = detalles["cost_price"]
                            if cost_price <= 0:
                                continue

                            title_text = detalles["title"] or f"{brand} {categoria}"
                            if any(k in title_text.lower() for k in EXCLUDE_KEYWORDS):
                                continue

                            sale_price = round(cost_price * MARGEN_GANANCIA, 2)
                            storage = "N/A"
                            match_storage = re.search(r'\b(64|128|256|512|1|2)\s*(GB|TB)\b', title_text, re.I)
                            if match_storage:
                                storage = match_storage.group(0)

                            galeria = detalles["gallery_images"]
                            main_image = galeria[0] if galeria else detalles["catalog_image"]

                            producto = {
                                "swappa_id": detalles["swappa_id"] or source_url.split("/")[-1],
                                "title": title_text,
                                "brand": brand,
                                "category": categoria,
                                "condition": "Used",
                                "color": detalles["color"] or "N/A",
                                "seller": detalles["seller"] or "Swappa Seller",
                                "cost_price": cost_price,
                                "sale_price": sale_price,
                                "storage": storage,
                                "description": detalles["description"],
                                "image_url": main_image,
                                "images": galeria,
                                "source_url": source_url,
                                "status": "Available"
                            }

                            headers = {"Content-Type": "application/json", "x-api-key": SCRAPER_API_KEY}
                            res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                            total_enviados += 1
                            print(f"[{total_enviados}] [{categoria} - {brand}] {title_text} | $${cost_price} -> $${sale_price} | Base44: {res.status_code}", flush=True)

                    except Exception as item_err:
                        continue

            except Exception as nav_error:
                print(f"Error procesando sección {target_url}: {nav_error}", flush=True)

        await browser.close()
        print(f"\n=======================================================", flush=True)
        print(f" Ciclo completado. Equipos procesados y subidos: {total_enviados}", flush=True)
        print(f"=======================================================", flush=True)

async def main():
    SEGUNDOS_UN_DIA = 86400
    while True:
        await ejecutar_extraccion_diaria()
        print(f"Esperando 24 horas para la siguiente actualización...", flush=True)
        await asyncio.sleep(SEGUNDOS_UN_DIA)

if __name__ == "__main__":
    asyncio.run(main())