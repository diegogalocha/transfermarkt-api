# 🚀 Transfermarkt API - Local Setup con Docker

Este proyecto permite correr una instancia **local** de la Transfermarkt API sin límites de uso, ideal para desarrollo y pruebas en ZCoutverse.

---

## 🛠️ Requisitos previos
- [Docker Desktop](https://www.docker.com/products/docker-desktop) instalado y funcionando
- WSL2 actualizado (en Windows)
- Puerto `8000` libre

---

## ▶️ Levantar la API en local

1. **Construir la imagen desde cero** (sin caché, recomendado la primera vez):
   ```bash
   docker-compose build --no-cache

2. Levantar el contenedor:
   ```bash
   docker-compose up

3. Documentación SWAGGER
    👉 http://localhost:8000/docs

🔄 Reiniciar / Detener
Detener: docker-compose down
Reiniciar (si ya está construida): docker-compose up -d

🌐 Configuración en el Frontend
En tu .env del frontend pon:

VITE_TRANSFERMARKT_API_URL=http://localhost:8000

Luego lanza tu frontend con: npm run dev

🐳 Logs en tiempo real
docker logs -f transfermarkt-api

📌 Subir a Producción
Usa el docker-compose.prod.yml incluido abajo para desplegar en cualquier VPS o servicio cloud compatible con Docker.

---

## 📄 `docker-compose.prod.yml` (Para despliegue en servidor)

```yaml
version: "3.9"

services:
  transfermarkt-api:
    image: zcoutverse/transfermarkt-api:latest # Cambia esto si subes tu imagen a DockerHub
    container_name: transfermarkt-api
    ports:
      - "8000:8000"
    environment:
      - RATE_LIMITING_ENABLE=true         # Actívalo si quieres control de rate limit
      - RATE_LIMITING_FREQUENCY=2/3second # Ejemplo de límite
    restart: unless-stopped
    
    
🚀 Cómo desplegar en un VPS
Construir la imagen localmente:
docker build -t zcoutverse/transfermarkt-api:latest ./backend/transfermarkt-api

Subirla a DockerHub (si quieres usar un registry):
docker push zcoutverse/transfermarkt-api:latest

En el servidor, descarga el proyecto y ejecuta:
docker-compose -f docker-compose.prod.yml up -d

Listo, accesible en http://<tu-servidor>:8000