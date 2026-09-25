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

async def extraer_galeria_y_detalles(context, listing_url):
    """Abre la publicación individual del producto para extraer todas sus fotos y especificaciones técnicas."""
    images = []
    specs = {}
    description = ""
    
    try:
        detail_page = await context.new_page()
        await detail_page.goto(listing_url, wait_until="domcontentloaded", timeout=25000)
        
        # 1. Extraer todas las fotos reales de la galería del vendedor
        img_elements = await detail_page.query_selector_all("a[data-lightbox='listing-images'] img, .carousel-item img, img.listing-image, div.gallery img")
        for img in img_elements:
            src = await img.get_attribute("src") or await img.get_attribute("data-src") or ""
            if src:
                if src.startswith("//"):
                    src = "https:" + src
                if src not in images and "avatar" not in src:
                    images.append(src)

        # 2. Extraer descripción/notas del vendedor
        desc_elem = await detail_page.query_selector(".listing-description, .condition-description, .seller-notes, div.section-body")
        if desc_elem:
            description = (await desc_elem.inner_text()).strip()

        # 3. Extraer tabla de especificaciones (RAM, Procesador, Color, etc.)
        rows = await detail_page.query_selector_all("table.table-specs tr, div.spec-item, tr.spec_row")
        for row in rows:
            text = (await row.inner_text()).strip()
            if ":" in text or "\t" in text:
                parts = text.split(":" if ":" in text else "\t", 1)
                specs[parts[0].strip().lower()] = parts[1].strip()

        await detail_page.close()
    except Exception as e:
        print(f"      [!] Error leyendo detalles de {listing_url}: {e}")
        
    return images, description, specs


async def extraer_y_enviar():
    print(f"Iniciando escaneo enriquecido de imágenes y specs hacia Base44...")
    
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

                        # Obtener enlace a la publicación específica
                        link_elem = await item.query_selector("a.stretched-link, a[href*='/listing/'], a[href*='/buy/']")
                        href = await link_elem.get_attribute("href") if link_elem else ""
                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        # Calcular precio
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

                        lines = [l.strip() for l in text_content.split("\n") if l.strip()]
                        title_text = lines[0] if lines else f"{brand} Device"
                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Valores por defecto
                        storage = "N/A"
                        ram = "N/A"
                        color = "N/A"
                        processor = "N/A"

                        for line in lines:
                            if re.search(r'\b(64|128|256|512)\s*(GB|TB)\b', line, re.I):
                                storage = line
                            elif re.search(r'\b(4|8|12|16|32|64)\s*GB\b', line, re.I) and storage != line:
                                ram = line

                        # Obtener galería completa y especificaciones detalladas entrando a la publicación
                        galeria_fotos = []
                        descripcion_detallada = f"Equipo {brand} {title_text} disponible en inventario."

                        if source_url:
                            galeria_fotos, descripcion_detallada, extra_specs = await extraer_galeria_y_detalles(context, source_url)
                            
                            # Asignar atributos si se encontraron en la página del producto
                            ram = extra_specs.get("memoria ram instalada", extra_specs.get("ram", ram))
                            processor = extra_specs.get("modelo de cpu", extra_specs.get("processor", processor))
                            color = extra_specs.get("color", color)

                        # Si la galería falló, usar la foto de la portada
                        if not galeria_fotos:
                            img_elem = await item.query_selector("img")
                            if img_elem:
                                main_img = await img_elem.get_attribute("src") or await img_elem.get_attribute("data-src") or ""
                                if main_img:
                                    galeria_fotos.append("https:" + main_img if main_img.startswith("//") else main_img)

                        nombre_completo = f"{brand} {title_text}" if brand.lower() not in title_text.lower() else title_text

                        # Objeto estructurado para Base44
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
                            "description": descripcion_detallada,
                            "image_url": galeria_fotos[0] if galeria_fotos else "",
                            "images": galeria_fotos,
                            "source_url": source_url,
                            "status": "Draft"
                        }

                        headers = {"Content-Type": "application/json", "x-api-key": SCRAPER_API_KEY}
                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                        
                        total_enviados += 1
                        print(f"[{total_enviados}] [{categoria} - {brand}] {nombre_completo} | Fotos: {len(galeria_fotos)} | Base44: {res.status_code}")

                    except Exception as e:
                        continue

            except Exception as nav_error:
                print(f"Error procesando la sección {target_url}: {nav_error}")

        await browser.close()
        print(f"\n=======================================================")
        print(f" Proceso finalizado. Equipos con imágenes y ficha completa en Base44: {total_enviados}")
        print(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())