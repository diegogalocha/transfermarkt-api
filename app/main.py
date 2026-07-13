import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from starlette.responses import RedirectResponse

from app.api.api import api_router
from app.settings import settings

# Configure logging to show INFO level messages
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ✅ Configuración del Rate Limiter
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMITING_FREQUENCY],
    enabled=settings.RATE_LIMITING_ENABLE,
)

# ✅ Inicializa FastAPI
is_production = settings.NODE_ENV.lower() == "production"
app = FastAPI(
    title="Transfermarkt API",
    docs_url=None if is_production else "/docs",
    redoc_url=None if is_production else "/redoc"
)

# ✅ Habilitar CORS para el frontend local
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Middlewares de Rate Limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

# ✅ Prefijo `/api/tm` para todas las rutas
app.include_router(api_router, prefix="/api/tm")

# ✅ Redirección a la documentación (solo si está habilitada)
@app.get("/", include_in_schema=False)
def root_redirect():
    if is_production:
        return {"status": "ok"}
    return RedirectResponse(url="/docs")

# ✅ Punto de entrada para Uvicorn
if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
