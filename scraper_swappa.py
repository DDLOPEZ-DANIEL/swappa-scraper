import asyncio
import os
import re
import requests
from playwright.async_api import async_playwright

# CONFIGURACIÓN
BASE44_WEBHOOK_URL = os.getenv(
    "BASE44_WEBHOOK_URL", 
    "https://rebit-smart-grid.base44.app/functions/swappaWebhook"
)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")
MARGEN_GANANCIA = 1.30

# URLs correctas de catálogo de modelos en Swappa
TARGET_URLS = [
    # CELULARES
    {"categoria": "Celular", "brand": "Apple", "url": "https://swappa.com/buy/unlocked/iphones"},
    {"categoria": "Celular", "brand": "Samsung", "url": "https://swappa.com/buy/unlocked/samsung"},
    {"categoria": "Celular", "brand": "Google", "url": "https://swappa.com/buy/unlocked/google"},
    # LAPTOPS
    {"categoria": "Laptop", "brand": "Apple", "url": "https://swappa.com/buy/macbooks"},
    {"categoria": "Laptop", "brand": "Dell", "url": "https://swappa.com/buy/laptops/dell"},
    {"categoria": "Laptop", "brand": "HP", "url": "https://swappa.com/buy/laptops/hp"},
    {"categoria": "Laptop", "brand": "Lenovo", "url": "https://swappa.com/buy/laptops/lenovo"},
    {"categoria": "Laptop", "brand": "Asus", "url": "https://swappa.com/buy/laptops/asus"}
]

async def extraer_y_enviar():
    print(f"Iniciando extracción masiva en Swappa hacia Webhook: {BASE44_WEBHOOK_URL}...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US"
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
                    print(f"Omitiendo por respuesta HTTP {response.status if response else 'Nula'}")
                    continue

                await asyncio.sleep(2)

                # Buscar tarjetas de producto (.card_product o .card)
                cards = await page.query_selector_all(".card_product, .card, div[class*='product']")
                print(f"Tarjetas de producto encontradas: {len(cards)}")

                for item in cards:
                    try:
                        text_content = await item.inner_text()
                        if not text_content:
                            continue

                        # Extraer enlace principal
                        link_elem = await item.query_selector("a.stretched-link, a[href*='/buy/'], a[href*='/listings/']")
                        href = ""
                        if link_elem:
                            href = await link_elem.get_attribute("href") or ""
                        
                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        # Buscar precio en dólares dentro de la tarjeta
                        prices = re.findall(r'\$\s*([0-9,]+(?:\.[0-9]{2})?)', text_content)
                        cost_price = 0.0

                        if prices:
                            for p_str in prices:
                                parsed = float(p_str.replace(',', ''))
                                if parsed >= 20: # Filtrar costos muy bajos o inválidos
                                    cost_price = parsed
                                    break

                        if cost_price <= 0:
                            continue

                        # Extraer Título/Modelo
                        lines = [l.strip() for l in text_content.split("\n") if l.strip()]
                        title_text = ""
                        for line in lines:
                            if not line.startswith("$") and len(line) > 3 and not any(bad in line.lower() for bad in ["from", "ver", "swappa", "sell", "buy"]):
                                title_text = line
                                break

                        if not title_text:
                            continue

                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Extraer Imagen
                        img_elem = await item.query_selector("img")
                        image_url = ""
                        if img_elem:
                            image_url = await img_elem.get_attribute("src") or await img_elem.get_attribute("data-src") or ""
                            if image_url.startswith("//"):
                                image_url = "https:" + image_url

                        storage = "Nicaragua / Unlocked" if categoria == "Celular" else "Estándar"
                        for line in lines:
                            if any(unit in line.upper() for unit in ["GB", "TB"]):
                                storage = line
                                break

                        nombre_completo = f"{brand} {title_text}" if brand.lower() not in title_text.lower() else title_text

                        producto = {
                            "title": nombre_completo,
                            "brand": brand,
                            "model": title_text,
                            "condition": "Good",
                            "cost_price": cost_price,
                            "sale_price": sale_price,
                            "storage": storage,
                            "image_url": image_url,
                            "source_url": source_url,
                            "status": "Draft"
                        }

                        headers = {
                            "Content-Type": "application/json",
                            "x-api-key": SCRAPER_API_KEY
                        }
                        
                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                        
                        total_enviados += 1
                        action_resp = res.json().get('action', 'ok') if res.status_code == 200 else res.text
                        print(f"[{total_enviados}] [{categoria} - {brand}] {nombre_completo} | Costo: ${cost_price} -> Venta: ${sale_price} | Base44: {res.status_code}")

                    except Exception:
                        continue

            except Exception as nav_error:
                print(f"Error cargando la sección {target_url}: {nav_error}")

        await browser.close()
        print(f"\n=======================================================")
        print(f" Proceso finalizado. Total de equipos registrados en Base44: {total_enviados}")
        print(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())