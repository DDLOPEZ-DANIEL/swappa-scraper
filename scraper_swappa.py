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

        try:
            print("Navegando a Swappa (Laptops)...")
            response = await page.goto("https://swappa.com/laptops", wait_until="domcontentloaded", timeout=60000)
            print(f"Estado HTTP de la página: {response.status if response else 'Sin respuesta'}")

            # Espera corta para carga de scripts
            await asyncio.sleep(5)

            # Intentar buscar tarjetas con múltiples selectores posibles de Swappa
            selectors = [".listing_card", "[data-product]", ".product-card", "a[href*='/listing/']"]
            found_selector = None

            for sel in selectors:
                count = len(await page.query_selector_all(sel))
                if count > 0:
                    found_selector = sel
                    print(f"Selector encontrado: '{sel}' con {count} elementos.")
                    break

            if not found_selector:
                print("No se encontraron productos con los selectores estándar. Imprimiendo título de página...")
                title = await page.title()
                print(f"Título de la página cargada: '{title}'")
                return

            items = await page.query_selector_all(found_selector)

            for index, item in enumerate(items[:15]):
                try:
                    # Búsqueda flexible de elementos dentro de la tarjeta
                    title_elem = await item.query_selector(".title, h3, .name")
                    price_elem = await item.query_selector(".price, .amount, [data-price]")
                    link_elem = await item.query_selector("a") if item.tag_name != "a" else item
                    img_elem = await item.query_selector("img")

                    title_text = await title_elem.inner_text() if title_elem else "Laptop Usada Swappa"
                    raw_price = await price_elem.inner_text() if price_elem else "$0"
                    
                    # Extraer únicamente números y puntos del precio
                    cleaned_price = "".join(c for c in raw_price if c.isdigit() or c == '.')
                    cost_price = float(cleaned_price) if cleaned_price else 0.0

                    if cost_price == 0:
                        continue

                    sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                    href = await link_elem.get_attribute("href") if link_elem else ""
                    source_url = "https://swappa.com" + href if href.startswith("/") else href

                    image_url = await img_elem.get_attribute("src") if img_elem else ""

                    producto = {
                        "title": title_text.strip().replace("\n", " "),
                        "brand": "Genérico",
                        "model": title_text.strip().replace("\n", " "),
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
                    print(f"[{index + 1}] '{title_text.strip()}' | Costo: ${cost_price} -> Venta: ${sale_price} | Base44 Status: {res.status_code}")

                except Exception as item_error:
                    print(f"Error procesando producto {index + 1}: {item_error}")

        except Exception as nav_error:
            print(f"Error durante la navegación: {nav_error}")

        finally:
            await browser.close()
            print("Navegador cerrado. Proceso finalizado.")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())