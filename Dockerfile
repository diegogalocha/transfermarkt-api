# ---- Stage 1: Build Environment ----
FROM python:3.11-slim AS builder

WORKDIR /app

# Variables de entorno
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    RATE_LIMITING_ENABLE=false \
    RATE_LIMITING_FREQUENCY=0/1second

# Instala dependencias del sistema necesarias para compilar paquetes
RUN apt-get update && apt-get install -y build-essential curl git && rm -rf /var/lib/apt/lists/*

# Copia el archivo de dependencias
COPY pyproject.toml poetry.lock* /app/

# Instala poetry y exporta requirements.txt
RUN pip install poetry==1.5.1 \
    && poetry export -f requirements.txt --output requirements.txt --without-hashes

# Copia el resto del proyecto
COPY . /app

# ---- Stage 2: Runtime ----
FROM python:3.11-slim

WORKDIR /app

# Copia la aplicación y las dependencias exportadas
COPY --from=builder /app /app

# Instala dependencias sin Poetry
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000

# ✅ Arranca FastAPI correctamente (usa app.main:app)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
