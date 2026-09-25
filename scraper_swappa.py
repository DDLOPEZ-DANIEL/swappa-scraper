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

async def extraer_detalles_completos(page, listing_url):
    """Navega a la página del producto para extraer la galería y ficha técnica detallada."""
    images = []
    specs = {}
    description = ""
    
    try:
        detail_page = await page.context.new_page()
        await detail_page.goto(listing_url, wait_until="domcontentloaded", timeout=30000)
        
        # Extraer todas las imágenes de la galería
        img_elements = await detail_page.query_selector_all("a[data-lightbox='listing-images'] img, .carousel-item img, img.listing-image")
        for img in img_elements:
            src = await img.get_attribute("src") or await img.get_attribute("data-src") or ""
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                if src not in images:
                    images.append(src)

        # Extraer descripción del vendedor o estado
        desc_elem = await detail_page.query_selector(".listing-description, .condition-description, .seller-notes")
        if desc_elem:
            description = (await desc_elem.inner_text()).strip()

        # Extraer especificaciones de la tabla o lista técnica
        spec_rows = await detail_page.query_selector_all("table.table-specs tr, div.spec-item, ul.specs-list li")
        for row in spec_rows:
            text = (await row.inner_text()).strip()
            if ":" in text:
                key, val = text.split(":", 1)
                specs[key.strip().lower()] = val.strip()

        await detail_page.close()
    except Exception as e:
        print(f"   [!] No se pudieron extraer detalles profundos de {listing_url}: {e}")
        
    return images, description, specs


async def extraer_y_enviar():
    print(f"Iniciando extracción enriquecida hacia Webhook: {BASE44_WEBHOOK_URL}...")
    
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

                        link_elem = await item.query_selector("a.stretched-link, a[href*='/buy/'], a[href*='/listings/'], a[href*='/listing/view/']")
                        href = await link_elem.get_attribute("href") if link_elem else ""
                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        # Extraer Precio Base
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

                        # Extracción básica en tarjeta
                        lines = [l.strip() for l in text_content.split("\n") if l.strip()]
                        title_text = lines[0] if lines else f"{brand} Device"
                        
                        storage = "N/A"
                        ram = "N/A"
                        color = "N/A"
                        processor = "N/A"

                        for line in lines:
                            if re.search(r'\b(64|128|256|512)\s*(GB|TB)\b', line, re.I):
                                storage = line
                            elif re.search(r'\b(4|8|12|16|32|64)\s*GB\b', line, re.I) and storage != line:
                                ram = line
                            elif any(c in line.lower() for c in ["black", "white", "silver", "blue", "green", "gold", "gray", "plata", "verde", "negro"]):
                                color = line
                            elif any(p in line.lower() for p in ["intel", "core", "ryzen", "m1", "m2", "m3", "snapdragon", "bionic"]):
                                processor = line

                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Extraer imagen principal de la tarjeta
                        img_elem = await item.query_selector("img")
                        main_image = ""
                        if img_elem:
                            main_image = await img_elem.get_attribute("src") or await img_elem.get_attribute("data-src") or ""
                            if main_image.startswith("//"):
                                main_image = "https:" + main_image

                        # Obtener imágenes adicionales y detalles de la página del producto
                        images = [main_image] if main_image else []
                        description = f"Equipo {brand} {title_text} en condición garantizada."
                        
                        if source_url and "/listing/" in source_url:
                            extra_imgs, extra_desc, extra_specs = await extraer_detalles_completos(page, source_url)
                            if extra_imgs:
                                images = extra_imgs
                            if extra_desc:
                                description = extra_desc
                            
                            # Actualizar especificaciones si fueron encontradas
                            ram = extra_specs.get("memoria ram instalada", extra_specs.get("ram", ram))
                            processor = extra_specs.get("modelo de cpu", extra_specs.get("processor", processor))
                            color = extra_specs.get("color", color)

                        nombre_completo = f"{brand} {title_text}" if brand.lower() not in title_text.lower() else title_text

                        # Estructura del objeto JSON hacia Base44
                        producto = {
                            "title": nombre_completo,
                            "brand": brand,
                            "model": title_text,
                            "condition": "Good",
                            "cost_price": cost_price,
                            "sale_price": sale_price,
                            "storage": storage,
                            "ram": ram,
                            "color": color,
                            "processor": processor,
                            "description": description,
                            "image_url": images[0] if images else "",
                            "images": images,
                            "source_url": source_url,
                            "status": "Draft"
                        }

                        headers = {"Content-Type": "application/json", "x-api-key": SCRAPER_API_KEY}
                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                        
                        total_enviados += 1
                        print(f"[{total_enviados}] [{categoria} - {brand}] {nombre_completo} | Fotos: {len(images)} | Base44: {res.status_code}")

                    except Exception as e:
                        continue

            except Exception as nav_error:
                print(f"Error cargando la sección {target_url}: {nav_error}")

        await browser.close()
        print(f"\n=======================================================")
        print(f" Proceso finalizado. Total de equipos enriquecidos en Base44: {total_enviados}")
        print(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())