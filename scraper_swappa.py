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

# URLs exactas basadas en la navegación real de Swappa
TARGET_URLS = [
    # --- CELULARES DESBLOQUEADOS (Nicaragua) ---
    {"categoria": "Celular", "brand": "Apple", "url": "https://swappa.com/buy/unlocked/apple"},
    {"categoria": "Celular", "brand": "Samsung", "url": "https://swappa.com/buy/unlocked/samsung"},
    {"categoria": "Celular", "brand": "Google", "url": "https://swappa.com/buy/unlocked/google"},
    # --- LAPTOPS POR MARCA ---
    {"categoria": "Laptop", "brand": "Apple", "url": "https://swappa.com/buy/b/apple"},
    {"categoria": "Laptop", "brand": "Dell", "url": "https://swappa.com/buy/b/dell"},
    {"categoria": "Laptop", "brand": "HP", "url": "https://swappa.com/buy/b/hp"},
    {"categoria": "Laptop", "brand": "Lenovo", "url": "https://swappa.com/buy/b/lenovo"},
    {"categoria": "Laptop", "brand": "Asus", "url": "https://swappa.com/buy/b/asus"}
]

async def extraer_y_enviar():
    print("Iniciando extracción en Swappa...")
    
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
            brand = target["brand"]
            target_url = target["url"]
            
            try:
                print(f"\n--- Escaneando {categoria}s ({brand}) en: {target_url} ---")
                response = await page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
                
                if not response or response.status != 200:
                    print(f"Omitiendo por respuesta HTTP {response.status if response else 'Nula'}")
                    continue

                await asyncio.sleep(3)

                # Seleccionar todas las tarjetas/bloques de catálogo que contienen un enlace /buy/
                cards = await page.query_selector_all("a[href*='/buy/']")
                print(f"Tarjetas de catálogo encontradas: {len(cards)}")

                procesados = 0
                for index, item in enumerate(cards):
                    if procesados >= 10:  # Límite de 10 productos por sección
                        break

                    try:
                        href = await item.get_attribute("href") or ""
                        
                        # Filtrar la URL base o enlaces repetidos del menú superior
                        if not href or href == target_url or href.count('/') < 3:
                            continue

                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        text_content = await item.inner_text()
                        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
                        
                        if not lines:
                            continue

                        title_text = lines[0]
                        if title_text.lower() in ["ver más", "view more", "filtrar", "filter", "todos"]:
                            continue

                        # Extraer el precio en USD
                        cost_price = 0.0
                        for line in lines:
                            if "$" in line:
                                cleaned = "".join(c for c in line if c.isdigit() or c == '.')
                                if cleaned:
                                    try:
                                        cost_price = float(cleaned)
                                        break
                                    except ValueError:
                                        continue

                        if cost_price <= 0:
                            continue

                        # Precio de venta con margen del 30%
                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Capturar la imagen
                        img_elem = await item.query_selector("img")
                        image_url = await img_elem.get_attribute("src") if img_elem else ""

                        producto = {
                            "title": f"{brand} {title_text}" if brand not in title_text else title_text,
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
                        print(f"  [{categoria} - {brand}] '{producto['title']}' | Costo: ${cost_price} -> Venta (30%): ${sale_price} | Base44 Status: {res.status_code}")
                        procesados += 1

                    except Exception as item_error:
                        print(f"  Error procesando elemento {index + 1}: {item_error}")

            except Exception as nav_error:
                print(f"Error en sección {target_url}: {nav_error}")

        await browser.close()
        print("\nExtracción completada exitosamente.")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())