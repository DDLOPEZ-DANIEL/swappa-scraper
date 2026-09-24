import asyncio
import os
import requests
from playwright.async_api import async_playwright

# CONFIGURACIÓN Y VARIABLES DE ENTORNO
BASE44_WEBHOOK_URL = os.getenv(
    "BASE44_WEBHOOK_URL", 
    "https://rebit-smart-grid.base44.app/functions/swappaWebhook"
)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")

# MARGEN DE GANANCIA: 30% (Precio Base * 1.30)
MARGEN_GANANCIA = 1.30

# URLs directas según la estructura observada en Swappa
TARGET_URLS = [
    # --- CELULARES DESBLOQUEADOS (Para Nicaragua) ---
    {"categoria": "Celular", "url": "https://swappa.com/buy/unlocked"},
    {"categoria": "Celular", "url": "https://swappa.com/buy/unlocked/apple"},
    {"categoria": "Celular", "url": "https://swappa.com/buy/unlocked/samsung"},
    # --- LAPTOPS ---
    {"categoria": "Laptop", "url": "https://swappa.com/laptops/macbooks"},
    {"categoria": "Laptop", "url": "https://swappa.com/laptops/dell"},
    {"categoria": "Laptop", "url": "https://swappa.com/laptops/hp"},
    {"categoria": "Laptop", "url": "https://swappa.com/laptops/lenovo"}
]

async def extraer_y_enviar():
    print("Iniciando extracción en Swappa (Celulares Desbloqueados y Laptops)...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York"
        )
        
        page = await context.new_page()

        # Evasión de atributo webdriver
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

                await asyncio.sleep(4)

                # Buscar tarjetas de producto en el catálogo (bloques de productos)
                cards = await page.query_selector_all("a[href*='/listing/'], a[href*='/buy/']")
                print(f"Elementos encontrados en página: {len(cards)}")

                procesados = 0
                for index, item in enumerate(cards):
                    if procesados >= 10:  # Máximo 10 productos por sección
                        break

                    try:
                        href = await item.get_attribute("href") or ""
                        
                        # Filtrar solo enlaces de producto/listado
                        if not href or href == target_url or href.endswith("/buy") or href.endswith("/laptops"):
                            continue

                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        text_content = await item.inner_text()
                        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
                        
                        if not lines:
                            continue

                        # Extraer título
                        title_text = lines[0]
                        
                        # Extraer el precio en USD
                        cost_price = 0.0
                        for line in lines:
                            if "$" in line:
                                cleaned = "".join(c for c in line if c.isdigit() or c == '.')
                                if cleaned:
                                    cost_price = float(cleaned)
                                    break

                        if cost_price <= 0:
                            continue

                        # Calcular precio de venta con el 30% de ganancia
                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Buscar la imagen del producto
                        img_elem = await item.query_selector("img")
                        image_url = await img_elem.get_attribute("src") if img_elem else ""

                        # Identificar marca
                        title_lower = title_text.lower()
                        if "iphone" in title_lower or "macbook" in title_lower or "apple" in title_lower:
                            brand = "Apple"
                        elif "samsung" in title_lower or "galaxy" in title_lower:
                            brand = "Samsung"
                        elif "dell" in title_lower:
                            brand = "Dell"
                        elif "hp" in title_lower:
                            brand = "HP"
                        elif "lenovo" in title_lower:
                            brand = "Lenovo"
                        else:
                            brand = "Genérico"

                        producto = {
                            "title": title_text,
                            "brand": brand,
                            "model": title_text,
                            "condition": "Good",
                            "cost_price": cost_price,
                            "sale_price": sale_price,
                            "storage": "Unlocked" if categoria == "Celular" else "N/A",
                            "image_url": image_url,
                            "source_url": source_url
                        }

                        headers = {
                            "Content-Type": "application/json",
                            "x-api-key": SCRAPER_API_KEY
                        }
                        
                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                        print(f"  [{categoria} - {brand}] '{title_text}' | Costo: ${cost_price} -> Venta (30%): ${sale_price} | Base44 Status: {res.status_code}")
                        procesados += 1

                    except Exception as item_error:
                        print(f"  Error procesando elemento {index + 1}: {item_error}")

            except Exception as nav_error:
                print(f"Error cargando la sección {target_url}: {nav_error}")

        await browser.close()
        print("\nProceso de extracción finalizado con éxito.")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())