import asyncio
from playwright.async_api import async_playwright

async def diagnostico():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://swappa.com/buy/unlocked/apple", wait_until="networkidle")
        
        cards = await page.query_selector_all("a[href*='/buy/']")
        print(f"Total enlaces encontrados: {len(cards)}\n")
        
        for i, card in enumerate(cards[:5]): # Muestra solo los primeros 5
            href = await card.get_attribute("href")
            text = await card.inner_text()
            print(f"--- MUESTRA {i+1} ---")
            print(f"HREF: {href}")
            print(f"TEXTO INTERNO:\n{repr(text)}")
            print("-" * 30)

        await browser.close()

if __name__ == "__main__":
    asyncio.run(diagnostico())