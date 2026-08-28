import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.admin import router as admin_router
from app.api.bookings import router as bookings_router
from app.api.facilities import router as facilities_router
from app.api.waitlist import router as waitlist_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="Lockin API",
    version="0.6.0",
    description="Concurrency-safe sports facility booking platform API for IIT Guwahati",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(facilities_router)
app.include_router(bookings_router)
app.include_router(waitlist_router)
app.include_router(admin_router)


@app.get("/health", tags=["health"])
async def health():
    return {
        "status": "ok",
        "service": "lockin-api",
    }