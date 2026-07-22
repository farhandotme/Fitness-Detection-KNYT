from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.routes.bicepRoutes import router as bicepRouter
from src.routes.fingerRoutes import router as fingerRouter
from src.routes.squatRoutes import router as squatRouter
from src.routes.pushupRoutes import router as pushupRouter
from src.routes.jumpingJackRoutes import router as jumpingJackRouter
from src.routes.lungeRoutes import router as lungeRouter
from src.routes.highKneesRoutes import router as highKneesRouter
from src.routes.plankRoutes import router as plankRouter
from src.routes.bodyAnalysisRoutes import router as bodyAnalysisRouter
from src.routes.mountainClimberRoutes import router as mountainClimberRouter
from src.routes.shoulderPressRoutes import router as shoulderPressRouter
from src.routes.lateralRaiseRoutes import router as lateralRaiseRouter
from src.routes.muayThaiJabRoutes import router as muayThaiJabRouter
from src.routes.deadbugRoutes import router as deadbugRouter
from src.routes.sidePlankRoutes import router as sidePlankRouter
from src.routes.bridgePoseRoutes import router as bridgePoseRouter
from src.routes.birdDogRoutes import router as birdDogRouter
from src.routes.calfRaiseRoutes import router as calfRaiseRouter
from src.routes.treePoseRoutes import router as treePoseRouter
from src.routes.warrioriiroutes import router as warrioriiRouter
from src.routes.cobraPoseRoutes import router as cobraPoseRouter
from src.routes.chairPoseRoutes import router as chairPoseRouter
from src.routes.downwardDogRoutes import router as downwardDogRouter

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
app.include_router(highKneesRouter, prefix="/ws", tags="high-knees")
app.include_router(plankRouter, prefix="/ws", tags="plank-hold")
app.include_router(mountainClimberRouter, prefix="/ws", tags="mountain-climber")
app.include_router(bodyAnalysisRouter, prefix="/api", tags="body-analysis")
app.include_router(shoulderPressRouter, prefix="/ws", tags="shoulder-press")
app.include_router(lateralRaiseRouter, prefix="/ws", tags="lateral-raise")
app.include_router(muayThaiJabRouter, prefix="/ws", tags="muaythai-jab")
app.include_router(deadbugRouter, prefix="/ws", tags="dead-bug-router")
app.include_router(sidePlankRouter, prefix="/ws", tags="side-plank-router")
app.include_router(bridgePoseRouter, prefix="/ws", tags="bridge-pose-router")
app.include_router(birdDogRouter, prefix="/ws", tags="bird-dog-router")
app.include_router(calfRaiseRouter, prefix="/ws", tags="calf-raise-router")
app.include_router(treePoseRouter, prefix="/ws", tags="tree-pose-router")
app.include_router(warrioriiRouter, prefix="/ws", tags="warriorii-pose-router")
app.include_router(cobraPoseRouter, prefix="/ws", tags="cobra-pose-router")
app.include_router(chairPoseRouter, prefix="/ws", tags="chair-pose-router")
app.include_router(downwardDogRouter, prefix="/ws", tags="downward-dog-router")
