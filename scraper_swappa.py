import asyncio
import os
import requests
from playwright.async_api import async_playwright

# CONFIGURACIÓN Y VARIABLES DE ENTORNO
BASE44_WEBHOOK_URL = os.getenv(
    "BASE44_WEBHOOK_URL", 
    "https://flexi-fleet-grow.base44.app/functions/swappaWebhook"
)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")

# MARGEN DE GANANCIA: 30% (Precio Base * 1.30)
MARGEN_GANANCIA = 1.30

# URLs directas a los feeds de ofertas activas para Celulares y Laptops
TARGET_URLS = [
    # --- CELULARES ---
    {"categoria": "Celular", "url": "https://swappa.com/mobile/buy/apple/iphone"},
    {"categoria": "Celular", "url": "https://swappa.com/mobile/buy/samsung"},
    {"categoria": "Celular", "url": "https://swappa.com/mobile/buy/google"},
    # --- LAPTOPS ---
    {"categoria": "Laptop", "url": "https://swappa.com/laptops/buy/apple-macbook"},
    {"categoria": "Laptop", "url": "https://swappa.com/laptops/buy/windows"}
]

async def extraer_y_enviar():
    print("Iniciando extracción de LAPTOPS y CELULARES en Swappa...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York"
        )
        
        page = await context.new_page()

        # Evasión de WebDriver
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        for target in TARGET_URLS:
            categoria = target["categoria"]
            target_url = target["url"]
            
            try:
                print(f"\n--- Escaneando {categoria}s en: {target_url} ---")
                response = await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                print(f"Estado HTTP: {response.status if response else 'Sin respuesta'}")

                await asyncio.sleep(3)

                # Buscar bloques o enlaces de ofertas
                items = await page.query_selector_all("a[href*='/listing/'], .listing_card, .product_card")
                print(f"Ofertas encontradas: {len(items)}")

                for index, item in enumerate(items[:10]):  # Procesar 10 por cada categoría
                    try:
                        href = await item.get_attribute("href") or ""
                        
                        # Si el elemento no es el enlace principal, buscar la etiqueta <a> dentro
                        if not href:
                            link_elem = await item.query_selector("a[href*='/listing/']")
                            if link_elem:
                                href = await link_elem.get_attribute("href") or ""

                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        text_content = await item.inner_text()
                        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
                        
                        if not lines:
                            continue

                        title_text = lines[0]
                        
                        # Extraer el precio en USD
                        cost_price = 0.0
                        for line in lines:
                            if "$" in line:
                                cleaned = "".join(c for c in line if c.isdigit() or c == '.')
                                if cleaned:
                                    cost_price = float(cleaned)
                                    break

                        # Si no encontramos un precio válido, omitir
                        if cost_price <= 0:
                            continue

                        # Calcular precio de venta con el 30% de ganancia
                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Buscar la imagen del producto
                        img_elem = await item.query_selector("img")
                        image_url = await img_elem.get_attribute("src") if img_elem else ""

                        # Definir la marca aproximada
                        brand = "Apple" if "iphone" in target_url or "macbook" in target_url else ("Samsung" if "samsung" in target_url else "Genérico")

                        producto = {
                            "title": title_text,
                            "brand": brand,
                            "model": title_text,
                            "condition": "Good",
                            "cost_price": cost_price,
                            "sale_price": sale_price,
                            "storage": "N/A",
                            "image_url": image_url,
                            "source_url": source_url
                        }

                        headers = {
                            "Content-Type": "application/json",
                            "x-api-key": SCRAPER_API_KEY
                        }
                        
                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                        print(f"  [{categoria}] '{title_text}' | Costo: ${cost_price} -> Venta (30%): ${sale_price} | Base44 Status: {res.status_code}")

                    except Exception as item_error:
                        print(f"  Error procesando item {index + 1}: {item_error}")

            except Exception as nav_error:
                print(f"Error en sección {target_url}: {nav_error}")

        await browser.close()
        print("\nExtracción completada exitosamente.")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())