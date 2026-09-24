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

async def extraer_y_enviar():
    print("Iniciando proceso de scraping en Swappa...")
    
    async with async_playwright() as p:
        # Lanzar navegador Chromium en modo headless
        browser = await p.chromium.launch(headless=True)
        
        # Crear contexto con configuraciones anti-detección humanas nativas
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York"
        )
        
        page = await context.new_page()

        # Script ligero de evasión de detección de automatización (webdriver flag)
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        try:
            print("Navegando a la sección de laptops en Swappa...")
            await page.goto("https://swappa.com/laptops", wait_until="domcontentloaded", timeout=60000)

            # Esperar a que los elementos de productos estén disponibles
            await page.wait_for_selector(".listing_card", timeout=20000)
            items = await page.query_selector_all(".listing_card")
            print(f"Se encontraron {len(items)} productos.")

            for index, item in enumerate(items[:15]):  # Procesar los primeros 15 productos
                try:
                    title_elem = await item.query_selector(".title")
                    price_elem = await item.query_selector(".price")
                    link_elem = await item.query_selector("a")
                    img_elem = await item.query_selector("img")

                    title_text = await title_elem.inner_text() if title_elem else "Sin título"
                    raw_price = await price_elem.inner_text() if price_elem else "$0"
                    
                    # Limpiar el precio y convertir a float
                    cost_price = float(raw_price.replace("$", "").replace(",", "").strip())
                    
                    # Calcular precio de venta con el 30% de margen
                    sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                    href = await link_elem.get_attribute("href") if link_elem else ""
                    source_url = "https://swappa.com" + href if href.startswith("/") else href

                    image_url = await img_elem.get_attribute("src") if img_elem else ""

                    # Estructuración de datos para Base44
                    producto = {
                        "title": title_text.strip(),
                        "brand": "Genérico",
                        "model": title_text.strip(),
                        "condition": "Good",
                        "cost_price": cost_price,
                        "sale_price": sale_price,
                        "storage": "N/A",
                        "image_url": image_url,
                        "source_url": source_url
                    }

                    # Petición POST al Webhook de Base44
                    headers = {
                        "Content-Type": "application/json",
                        "x-api-key": SCRAPER_API_KEY
                    }
                    
                    res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                    print(f"[{index + 1}] '{title_text.strip()}' | Costo: ${cost_price} -> Venta (30%): ${sale_price} | Base44 Status: {res.status_code}")

                except Exception as item_error:
                    print(f"Error procesando producto {index + 1}: {item_error}")

        except Exception as nav_error:
            print(f"Error durante la navegación en Swappa: {nav_error}")

        finally:
            await browser.close()
            print("Navegador cerrado. Proceso finalizado.")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())