from fastapi import FastAPI
from src.api import main_router as APIRouter
from src.sse.router import router as SSERouter
from src.middlewares.logger import LoggingMiddleware
from fastapi.middleware.cors import CORSMiddleware
import os
from src.events import startup, shutdown
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup(app)
    try:
        yield
    finally:
        await shutdown(app)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", 
        "http://localhost:5174", 
        "http://localhost:5175", 
        "http://192.168.1.62:5175",
        "https://localhost:5173", 
        "https://localhost:5174", 
        "https://localhost:5175", 
        "http://192.168.1.62:5173", 
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://localhost",
        "http://127.0.0.1",
        "http://192.168.1.62",
        "http://192.168.1.82"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_middleware(LoggingMiddleware)

app.include_router(APIRouter)
app.include_router(SSERouter)

if __name__ == "__main__":
    import uvicorn

    DEFAULT_PORT = "3031"
    try:
        port = int(os.environ.get("PORT", DEFAULT_PORT))
    except Exception:
        port = int(DEFAULT_PORT)

    uvicorn.run(
        "main:app",
        port=port,
        host=os.environ.get("HOST", "0.0.0.0"),
        reload=os.environ.get("ENV", "DEV") == "DEV",
    )