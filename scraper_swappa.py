import asyncio
import requests
from playwright.async_api import async_playwright
from playwright_stealth import stealth_async
import os

# CONFIGURACIÓN
BASE44_WEBHOOK_URL = os.getenv("BASE44_WEBHOOK_URL", "https://flexi-fleet-grow.base44.app/functions/swappaWebhook")
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")
MARGEN_GANANCIA = 1.15  # 15% de margen sobre el precio de costo

async def extraer_y_enviar():
    async with async_playwright() as p:
        # Lanzar navegador en modo stealth
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_async(page)

        print("Navegando a Swappa...")
        # Ejemplo: Categoria de Laptops o Celulares Unlocked
        await page.goto("https://swappa.com/laptops", wait_until="networkidle")

        # Seleccionar elementos de productos
        items = await page.query_selector_all(".listing_card")

        for item in items[:10]: # Procesar los primeros 10 productos
            try:
                title_elem = await item.query_selector(".title")
                price_elem = await item.query_selector(".price")
                link_elem = await item.query_selector("a")
                img_elem = await item.query_selector("img")

                title = await title_elem.inner_text() if title_elem else "Sin título"
                raw_price = await price_elem.inner_text() if price_elem else "$0"
                cost_price = float(raw_price.replace("$", "").replace(",", "").strip())
                source_url = "https://swappa.com" + (await link_elem.get_attribute("href") if link_elem else "")
                image_url = await img_elem.get_attribute("src") if img_elem else ""

                # Estructurar objeto para Base44
                producto = {
                    "title": title.strip(),
                    "brand": "Genérico",
                    "model": title.strip(),
                    "condition": "Good",
                    "cost_price": cost_price,
                    "sale_price": round(cost_price * MARGEN_GANANCIA, 2),
                    "image_url": image_url,
                    "source_url": source_url
                }

                # Enviar a Base44
                headers = {
                    "Content-Type": "application/json",
                    "x-api-key": SCRAPER_API_KEY
                }
                res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers)
                print(f"Producto '{title}' enviado. Status Base44: {res.status_code}")

            except Exception as e:
                print(f"Error procesando item: {e}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())