from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.routers.search import router as search_router
from app.database import engine, Base

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(search_router, prefix="/api")

@app.on_event("startup")
async def startup():
    # Create tables (optional - only if you need to create new tables)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)