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

# Palabras clave para omitir productos que no son Laptops ni Celulares
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
    """
    Abre la publicación individual usando los selectores exactos del inspector:
    - section#section_media a.featured_image
    - section#section_media a.lightbox
    """
    image_urls = []
    main_image_url = ""
    description = ""
    specs = {}
    
    try:
        detail_page = await context.new_page()
        # Esperar a que htmx/red termine de cargar las miniaturas
        await detail_page.goto(listing_url, wait_until="networkidle", timeout=30000)
        
        # 1. Extraer Imagen Principal (Alta resolución desde el atributo 'href' del lightbox)
        featured_img_elem = await detail_page.query_selector("section#section_media a.featured_image")
        if featured_img_elem:
            main_image_url = await featured_img_elem.get_attribute("href") or ""
            if main_image_url.startswith("//"):
                main_image_url = "https:" + main_image_url

        # 2. Extraer TODAS las imágenes de la galería
        gallery_anchors = await detail_page.query_selector_all("section#section_media a.lightbox")
        for a in gallery_anchors:
            href = await a.get_attribute("href") or ""
            if href:
                if href.startswith("//"):
                    href = "https:" + href
                if href not in image_urls and "avatar" not in href:
                    image_urls.append(href)

        # Asegurar que la imagen principal esté al inicio si no fue capturada antes
        if main_image_url and main_image_url not in image_urls:
            image_urls.insert(0, main_image_url)

        # 3. Extraer Descripción
        desc_elem = await detail_page.query_selector("section#section_main .xui_card, .listing-description, .seller-notes")
        if desc_elem:
            description = (await desc_elem.inner_text()).strip()

        await detail_page.close()
    except Exception as e:
        print(f"      [!] Error en detalles de {listing_url}: {e}")
        
    return image_urls, main_image_url, description


async def extraer_y_enviar():
    print("Iniciando escaneo enriquecido hacia Base44...")
    
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
                        
                        # Filtro para omitir impresoras, GPUs y consolas
                        if any(k in title_text.lower() for k in EXCLUDE_KEYWORDS):
                            continue

                        # Obtener enlace a la publicación individual
                        link_elem = await item.query_selector("a.stretched-link, a[href*='/listing/'], a[href*='/buy/']")
                        href = await link_elem.get_attribute("href") if link_elem else ""
                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        # Precio
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

                        # Extraer imágenes y detalles entrando al listing
                        galeria_fotos = []
                        main_image = ""
                        descripcion_detallada = f"Equipo {brand} {title_text} listo para envío."

                        if source_url and "/listing/" in source_url:
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