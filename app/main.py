# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from .config import settings

from .database import engine, Base
from .routers import inventory, operators, operation_types, die_config, dies, production_orders, component_bom, work_orders

app = FastAPI(
    title="Die Shop API",
    version="0.1.0",
    # root_path="/api",
)

Base.metadata.create_all(bind=engine)
# CORS (React'in bağlanabilmesi için)
origins = [
    "http://localhost:5173",  # Vite ise
    "http://localhost:3000",  # Create React App ise
    "http://arslan",
    "http://arslan:8084",
    "http://arslan:8082",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(inventory.router)
app.include_router(die_config.router)
app.include_router(dies.router)
app.include_router(production_orders.router)
app.include_router(work_orders.router)      # /work-orders
app.include_router(work_orders.ops_router) 
app.include_router(component_bom.router) 
app.include_router(operators.router)
app.include_router(operation_types.router)

@app.get("/health")
def health_check():
    return {"status": "ok"}

# media klasörünü Django’daki gibi publish et
settings.MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
app.mount(settings.MEDIA_URL, StaticFiles(directory=settings.MEDIA_ROOT), name="media")