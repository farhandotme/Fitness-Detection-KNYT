from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routes.bicepRoutes import router as bicepRouter
from src.routes.fingerRoutes import router as fingerRouter
from src.routes.squatRoutes import router as squatRouter
from src.routes.pushupRoutes import router as pushupRouter
from src.routes.jumpingJackRoutes import router as jumpingJackRouter
from src.routes.lungeRoutes import router as lungeRouter
from src.routes.bodyAnalysisRoutes import router as bodyAnalysisRouter

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def home():
    return {"status": "running"}


app.include_router(bicepRouter, prefix="/ws", tags="bicep")
app.include_router(fingerRouter, prefix="/ws", tags="finger")
app.include_router(squatRouter, prefix="/ws", tags="squat")
app.include_router(pushupRouter, prefix="/ws", tags="pushup")
app.include_router(jumpingJackRouter, prefix="/ws", tags="jumping-jack")
app.include_router(lungeRouter, prefix="/ws", tags="lunge")
app.include_router(bodyAnalysisRouter, prefix="/api", tags="body-analysis")
