import asyncio
import os
import re
import json
import requests
from bs4 import BeautifulSoup
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

async def extraer_detalles_json_ld(context, listing_url):
    """
    Extrae la información precisa analizando el JSON-LD de la página del producto.
    """
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
        await asyncio.sleep(1)
        content = await detail_page.content()
        soup = BeautifulSoup(content, 'html.parser')

        # 1. Extraer JSON-LD
        json_ld_script = soup.find('script', type='application/ld+json')
        if json_ld_script and json_ld_script.string:
            try:
                schema_data = json.loads(json_ld_script.string)
                datos_producto["swappa_id"] = schema_data.get("productID", "")
                datos_producto["title"] = schema_data.get("name", "")
                datos_producto["description"] = schema_data.get("description", "")
                datos_producto["color"] = schema_data.get("color", "")
                datos_producto["catalog_image"] = schema_data.get("image", "")
                
                if "offers" in schema_data:
                    datos_producto["cost_price"] = float(schema_data["offers"].get("price", 0.0))
                    datos_producto["seller"] = schema_data["offers"].get("seller", {}).get("name", "")
            except Exception as e_json:
                print(f"      [!] Error parseando JSON-LD: {e_json}")

        # 2. Extraer Galería de Fotos Reales
        images = []
        for img in soup.find_all('img'):
            src = img.get('src') or img.get('data-src') or ''
            if src.startswith('//'):
                src = 'https:' + src
            if ('/media/listing/' in src or 'static.swappa.com/media/' in src) and src not in images:
                images.append(src)
                
        # Buscar en enlaces a imágenes si no se hallaron por tag img
        if not images:
            for a in soup.find_all('a', class_='lightbox'):
                href = a.get('href') or ''
                if href.startswith('//'):
                    href = 'https:' + href
                if href and href not in images:
                    images.append(href)

        datos_producto["gallery_images"] = images
        await detail_page.close()
    except Exception as e:
        print(f"      [!] Error en página de detalle {listing_url}: {e}")
        
    return datos_producto

async def ejecutar_extraccion_diaria():
    print("Iniciando escaneo optimizado de Swappa hacia Base44...")
    
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
                        link_elem = await item.query_selector("a.stretched-link, a[href*='/listing/'], a[href*='/buy/']")
                        href = await link_elem.get_attribute("href") if link_elem else ""
                        if not href:
                            continue

                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        # Extraer detalle desde la vista individual mediante JSON-LD
                        detalles = await extraer_detalles_json_ld(context, source_url)

                        cost_price = detalles["cost_price"]
                        if cost_price <= 0:
                            continue

                        title_text = detalles["title"] or f"{brand} Device"
                        if any(k in title_text.lower() for k in EXCLUDE_KEYWORDS):
                            continue

                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Extraer almacenamiento
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
                        print(f"[{total_enviados}] [{categoria} - {brand}] {title_text} | ID: {producto['swappa_id']} | Base44: {res.status_code}")

                    except Exception:
                        continue

            except Exception as nav_error:
                print(f"Error procesando la sección {target_url}: {nav_error}")

        await browser.close()
        print(f"\n=======================================================")
        print(f" Ciclo completado. Equipos procesados: {total_enviados}")
        print(f"=======================================================")

async def main():
    # Ejecución en bucle de 24 horas (86,400 segundos)
    SEGUNDOS_UN_DIA = 86400
    while True:
        await ejecutar_extraccion_diaria()
        print(f"Esperando 24 horas para la siguiente actualización...")
        await asyncio.sleep(SEGUNDOS_UN_DIA)

if __name__ == "__main__":
    asyncio.run(main())