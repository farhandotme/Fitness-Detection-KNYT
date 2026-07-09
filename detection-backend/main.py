from fastapi import FastAPI

from src.routes.bicepRoutes import router as bicepRouter
from src.routes.fingerRoutes import router as fingerRouter

app = FastAPI()


@app.get("/")
async def home():
    return {"status": "running"}


app.include_router(bicepRouter, prefix="/ws", tags="bicep")
app.include_router(fingerRouter, prefix="/ws", tags="finger")
