import asyncio
import os
import requests
from playwright.async_api import async_playwright

# CONFIGURACIÓN DE BASE44 / REBIT
BASE44_WEBHOOK_URL = os.getenv(
    "BASE44_WEBHOOK_URL", 
    "https://rebit-smart-grid.base44.app/functions/swappaWebhook"
)
SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "mi_clave1_secreta_swappa_2026")

# MARGEN DE GANANCIA: 30% (Precio Base * 1.30)
MARGEN_GANANCIA = 1.30

# URLs exactas de Celulares Desbloqueados y Laptops
TARGET_URLS = [
    # --- CELULARES DESBLOQUEADOS ---
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
    print(f"Iniciando extracción masiva en Swappa hacia Webhook: {BASE44_WEBHOOK_URL}...")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/New_York"
        )
        
        page = await context.new_page()

        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

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
                    print(f"Omitiendo por respuesta HTTP {response.status if response else 'Nula'}")
                    continue

                await asyncio.sleep(3)

                # Scroll progresivo para cargar imágenesLazy
                await page.evaluate("""async () => {
                    await new Promise((resolve) => {
                        let totalHeight = 0;
                        let distance = 400;
                        let timer = setInterval(() => {
                            let scrollHeight = document.body.scrollHeight;
                            window.scrollBy(0, distance);
                            totalHeight += distance;
                            if(totalHeight >= scrollHeight){
                                clearInterval(timer);
                                resolve();
                            }
                        }, 100);
                    });
                }""")

                await asyncio.sleep(2)

                # Seleccionar todas las tarjetas dentro del área principal
                cards = await page.query_selector_all("main a, div.product-card, a[href*='/buy/']")
                print(f"Total de bloques detectados: {len(cards)}")

                for index, item in enumerate(cards):
                    try:
                        text_content = await item.inner_text()
                        lines = [line.strip() for line in text_content.split("\n") if line.strip()]
                        
                        # Debe tener al menos título y precio (2 o más líneas de texto)
                        if len(lines) < 2:
                            continue

                        # Buscar precio en USD ($)
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

                        # Si no hay precio, la tarjeta no es un producto individual
                        if cost_price <= 0:
                            continue

                        title_text = lines[0]
                        if title_text.lower() in ["ver más", "view more", "filtrar", "filter", "todos", "all", "vender", "swappa"]:
                            continue

                        # Obtener enlace
                        href = await item.get_attribute("href") or ""
                        if not href:
                            link_elem = await item.query_selector("a")
                            if link_elem:
                                href = await link_elem.get_attribute("href") or ""

                        source_url = "https://swappa.com" + href if href.startswith("/") else href

                        # Calcular precio de venta al público en Nicaragua (30% de ganancia)
                        sale_price = round(cost_price * MARGEN_GANANCIA, 2)

                        # Extraer imagen
                        img_elem = await item.query_selector("img")
                        image_url = ""
                        if img_elem:
                            image_url = (
                                await img_elem.get_attribute("src") or 
                                await img_elem.get_attribute("data-src") or ""
                            )
                            if image_url and image_url.startswith("//"):
                                image_url = "https:" + image_url

                        storage = "Unlocked / Nicaragua" if categoria == "Celular" else "Estándar"
                        for line in lines:
                            if any(unit in line.upper() for unit in ["GB", "TB"]):
                                storage = line
                                break

                        nombre_completo = f"{brand} {title_text}" if brand.lower() not in title_text.lower() else title_text

                        producto = {
                            "title": nombre_completo,
                            "brand": brand,
                            "model": title_text,
                            "condition": "Excelente / Usado Garantizado",
                            "cost_price": cost_price,
                            "sale_price": sale_price,
                            "storage": storage,
                            "image_url": image_url,
                            "source_url": source_url,
                            "category": categoria
                        }

                        headers = {
                            "Content-Type": "application/json",
                            "x-api-key": SCRAPER_API_KEY
                        }
                        
                        res = requests.post(BASE44_WEBHOOK_URL, json=producto, headers=headers, timeout=10)
                        
                        total_enviados += 1
                        print(f"[{total_enviados}] [{categoria} - {brand}] {nombre_completo} | Costo: ${cost_price} -> Venta: ${sale_price} | Base44 Status: {res.status_code}")

                    except Exception as item_error:
                        continue

            except Exception as nav_error:
                print(f"Error cargando la sección {target_url}: {nav_error}")

        await browser.close()
        print(f"\n=======================================================")
        print(f" Proceso finalizado. Total de equipos registrados en Base44: {total_enviados}")
        print(f"=======================================================")

if __name__ == "__main__":
    asyncio.run(extraer_y_enviar())