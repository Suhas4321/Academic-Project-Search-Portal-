# app/main.py

import os
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.database import engine, Base
from app.routers.search import router as search_router
from app.routers.admin import router as admin_router

# Load environment variables (DATABASE_URL, ADMIN_USERNAME, ADMIN_PASSWORD, SECRET_KEY)
load_dotenv()

app = FastAPI()

# Sessions for admin auth
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "change-me"),
)

# Serve static files under /static
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Serve index.html at root URL
@app.get("/", include_in_schema=False)
async def root():
    return FileResponse("app/static/index.html")

# Serve admin_login.html at /admin-login
@app.get("/admin-login", include_in_schema=False)
async def admin_login():
    return FileResponse("app/static/admin_login.html")

# Optionally, you can keep /admin as well if you want
@app.get("/admin", include_in_schema=False)
async def admin_root():
    return FileResponse("app/static/admin_login.html")

# Include API routers
app.include_router(search_router, prefix="/api")
app.include_router(admin_router, prefix="/api")

@app.on_event("startup")
async def startup():
    # Create any missing tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)