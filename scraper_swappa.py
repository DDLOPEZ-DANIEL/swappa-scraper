import asyncio
import os
import re
import requests
from playwright.async_api import async_playwright

BASE44_WEBHOOK_URL = os.getenv(
    "BASE44_WEBHOOK_URL", 
    "https://rebit-smart-grid.base44.app/functions/swappaWebhook"
)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")
MARGEN_GANANCIA = 1.30

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

async def extraer_galeria_y_detalles(context, listing_url):
    image_urls = []
    main_image_url = ""
    description = ""
    
    try:
        detail_page = await context.new_page()
        await detail_page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
        
        # Esperar a que el contenedor de imágenes o el cuerpo de la página cargue
        try:
            await detail_page.wait_for_selector("section#section_media, div#medias_content, a.lightbox", timeout=5000)
        except Exception:
            pass

        # 1. Extraer Imagen Principal
        featured_elem = await detail_page.query_selector("section#section_media a.featured_image, a.lightbox.featured_image, img.featured_image")
        if featured_elem:
            main_image_url = await featured_elem.get_attribute("href") or await featured_elem.get_attribute("src") or ""

        # 2. Extraer todas las imágenes disponibles en la galería
        img_anchors = await detail_page.query_selector_all("section#section_media a.lightbox, div#medias_content a, a[data-lightbox]")
        for a in img_anchors:
            href = await a.get_attribute("href") or await a.get_attribute("data-src") or ""
            if href:
                if href.startswith("//"):
                    href = "https:" + href
                if href not in image_urls and "avatar" not in href:
                    image_urls.append(href)

        # Buscar imágenes <img> directamente si no se encontraron enlaces <a>
        if not image_urls:
            imgs = await detail_page.query_selector_all("section#section_media img, div#medias_content img")
            for img in imgs:
                src = await img.get_attribute("src") or await img.get_attribute("data-src") or ""
                if src:
                    if src.startswith("//"):
                        src = "https:" + src
                    if src not in image_urls and "avatar" not in src:
                        image_urls.append(src)

        if main_image_url:
            if main_image_url.startswith("//"):
                main_image_url = "https:" + main_image_url
            if main_image_url not in image_urls:
                image_urls.insert(0, main_image_url)

        # 3. Extraer Descripción del Vendedor
        desc_elem = await detail_page.query_selector("section#section_main .xui_card, .listing-description, .seller-notes")
        if desc_elem:
            description = (await desc_elem.inner_text()).strip()

        await detail_page.close()
    except Exception as e:
        print(f"      [!] Error en extracción de {listing_url}: {e}")
        
    return image_urls, main_image_url, description


async def extraer_y_enviar():
    print("Iniciando escaneo corregido hacia Base44...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            viewport={"width": 1440, "height": 900}
        )
        page = await context.new_page()
        total_enviados = 0

        for target in TARGET_URLS:
            categoria = target["categoria"]
            brand = target["brand"]
            target_url = target["url"]
            
            try:
                print(f"\n=======================================================")
                print(f" Escaneando {categoria}s ({brand}) en: {target_url}")
                print(f"=======================================================")
                
                response = await page.goto(target_url, wait_until="networkidle", timeout=60000)
                if not response or response.status != 200:
                    continue

                await asyncio.sleep(2)
                cards = await page.query_selector_all(".card_product, .card, div[class*='product']")

                for item in cards:
                    try:
                        text_content = await item.inner_text()
                        if not text_content:
                            continue

                        lines = [l.strip() for l in text_content.split("\n") if l.strip()]
                        title_text = lines[0] if lines else f"{brand} Device"
                        
                        if any(k in title_text.lower() for k in EXCLUDE_KEYWORDS):
                            continue

                        link_elem = await item.query_selector("a.stretched-link, a[href*='/listing/'], a[href*='/buy/']")
                        href = await link_elem.get_attribute("href") if link_elem else ""
                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        prices = re.findall(r'\$\s*([0-9,]+(?:\.[0-9]{2})?)', text_content)
                        cost_price = 0.0
                        if prices:
                            for p_str in prices:
                                parsed = float(p_str.replace(',', ''))
                                if parsed >= 20:
                                    cost_price = parsed
                                    break
                        if cost_price <= 0:
                            continue

                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        storage = "N/A"
                        for line in lines:
                            if re.search(r'\b(64|128|256|512)\s*(GB|TB)\b', line, re.I):
                                storage = line
                                break

                        galeria_fotos = []
                        main_image = ""
                        descripcion_detallada = f"Equipo {brand} {title_text} listo para envío."

                        # Extraer fotos si la URL apunta a un producto/listing
                        if source_url and ("/listing/" in source_url or "/buy/" in source_url):
                            galeria_fotos, main_image, descripcion_detallada = await extraer_galeria_y_detalles(context, source_url)

                        nombre_completo = f"{brand} {title_text}" if brand.lower() not in title_text.lower() else title_text

                        producto = {
                            "title": nombre_completo,
                            "brand": brand,
                            "model": title_text,
                            "condition": "Good",
                            "cost_price": cost_price,
                            "sale_price": sale_price,
                            "storage": storage,
                            "description": descripcion_detallada,
                            "image_url": main_image or (galeria_fotos[0] if galeria_fotos else ""),
                            "images": galeria_fotos,
                            "source_url": source_url,
                            "status": "Draft"
                        }

                        headers = {"Content-Type": "application/json", "x-api-key": SCRAPER_API_KEY}
                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                        
                        total_enviados += 1
                        print(f"[{total_enviados}] [{categoria} - {brand}] {nombre_completo} | Fotos: {len(galeria_fotos)} | Base44: {res.status_code}")

                    except Exception:
                        continue

            except Exception as nav_error:
                print(f"Error procesando la sección {target_url}: {nav_error}")

        await browser.close()
        print(f"\n=======================================================")
        print(f" Proceso finalizado. Total de equipos procesados: {total_enviados}")
        print(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())