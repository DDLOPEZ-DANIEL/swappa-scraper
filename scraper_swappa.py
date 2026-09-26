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
        await asyncio.sleep(1.5)

        # 1. Buscar todas las imágenes de la galería (incluye LightGallery .lg-object e imágenes directas)
        img_elements = await detail_page.query_selector_all("img.lg-object, img.lg-image, section img, div.media img, img[src*='/media/listing/']")
        
        for img in img_elements:
            src = await img.get_attribute("src") or await img.get_attribute("data-src") or ""
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                # Filtrar avatares o iconos no deseados y verificar que pertenezca a listings
                if ("static.swappa.com/media/listing/" in src or "/media/listing/" in src) and src not in image_urls:
                    image_urls.append(src)

        # 2. Si no se hallaron por selector img directo, buscar enlaces a la galería
        if not image_urls:
            anchors = await detail_page.query_selector_all("a[href*='/media/listing/'], a.lightbox")
            for a in anchors:
                href = await a.get_attribute("href") or ""
                if href:
                    if href.startswith("//"):
                        href = "https:" + href
                    if href not in image_urls:
                        image_urls.append(href)

        if image_urls:
            main_image_url = image_urls[0]

        # 3. Extraer Descripción
        desc_elem = await detail_page.query_selector("section .xui_card, .listing-description, .seller-notes, div[class*='description']")
        if desc_elem:
            description = (await desc_elem.inner_text()).strip()

        await detail_page.close()
    except Exception as e:
        print(f"      [!] Error navegando a detalle {listing_url}: {e}")
        
    return image_urls, main_image_url, description


async def extraer_y_enviar():
    print("Iniciando escaneo optimizado hacia Base44...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
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
                
                response = await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
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

                        # Extraer foto preliminar del catálogo como respaldo
                        backup_images = []
                        cat_imgs = await item.query_selector_all("img")
                        for c_img in cat_imgs:
                            c_src = await c_img.get_attribute("src") or await c_img.get_attribute("data-src") or ""
                            if c_src and "avatar" not in c_src:
                                if c_src.startswith("//"):
                                    c_src = "https:" + c_src
                                if c_src not in backup_images:
                                    backup_images.append(c_src)

                        galeria_fotos = []
                        main_image = ""
                        descripcion_detallada = f"Equipo {brand} {title_text} disponible para compra."

                        # Si hay URL de publicación, extraemos la galería completa de la página individual
                        if source_url and ("/listing/" in source_url or "/buy/" in source_url):
                            galeria_fotos, main_image, descripcion_detallada = await extraer_galeria_y_detalles(context, source_url)

                        # Si la navegación individual no devolvió fotos, usamos las fotos de respaldo del catálogo
                        if not galeria_fotos and backup_images:
                            galeria_fotos = backup_images
                            main_image = backup_images[0]

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