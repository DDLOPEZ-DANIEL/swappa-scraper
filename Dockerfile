# Actualizado a v1.63.0-jammy para coincidir con la versión requerida de Playwright
FROM mcr.microsoft.com/playwright/python:v1.63.0-jammy

# Directorio de trabajo
WORKDIR /app

# Copiar archivos de dependencias e instalarlas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

# Comando de ejecución por defecto
CMD ["python", "scraper_swappa.py"]