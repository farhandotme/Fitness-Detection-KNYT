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
from src.routes.pikePushupRoutes import router as pikePushupRouter
from src.routes.tuckJumpRoutes import router as tuckJumpRouter
from src.routes.sumoSquatRoutes import router as sumoSquatRouter
from src.routes.triangleRoutes import router as trianglePoseRouter
from src.routes.standingForwardFoldRoutes import router as standingForwardFoldRouter
from src.routes.reverseWarriorRoutes import router as reverseWarriorRouter
from src.routes.armCirclesRoutes import router as armCirclesRouter
from src.routes.standingCrossCrunchRoutes import router as standingCrossCrunchRouter
from src.routes.peacockPoseRoutes import router as peacockPoseRouter
from src.routes.hollowHoldRoutes import router as hollowHoldRouter
from src.routes.buttKicksRoutes import router as buttKicksRouter
from src.routes.wallSitRoutes import router as wallSitRouter
from src.routes.legRaiseRoutes import router as legRaiseRouter
from src.routes.russianTwistRoutes import router as russianTwistRouter
from src.routes.flutterKicksRoutes import router as flutterKicksRouter
from src.routes.singleLegSquatRoutes import router as singleLegSquatRouter
from src.routes.windmillRotationStretchRoutes import (
    router as windmillRotationStretchRouter,
)

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
app.include_router(pikePushupRouter, prefix="/ws", tags="pike-pushup-router")
app.include_router(tuckJumpRouter, prefix="/ws", tags="tuck-jump-router")
app.include_router(sumoSquatRouter, prefix="/ws", tags="sumo-squat-router")
app.include_router(trianglePoseRouter, prefix="/ws", tags="triangle-pose-router")
app.include_router(reverseWarriorRouter, prefix="/ws", tags="reverse-warrior-router")
app.include_router(armCirclesRouter, prefix="/ws", tags="arm-circles-router")
app.include_router(peacockPoseRouter, prefix="/ws", tags="peacock-pose-router")
app.include_router(hollowHoldRouter, prefix="/ws", tags="hollow-hold-router")
app.include_router(flutterKicksRouter, prefix="/ws", tags="flutter-kicks-router")
app.include_router(buttKicksRouter, prefix="/ws", tags="butt-kicks-router")
app.include_router(wallSitRouter, prefix="/ws", tags="wall-sit-router")
app.include_router(legRaiseRouter, prefix="/ws", tags="leg-raise-router")
app.include_router(russianTwistRouter, prefix="/ws", tags="russian-twist-router")
app.include_router(singleLegSquatRouter, prefix="/ws", tags="single-leg-squat-router")
app.include_router(
    windmillRotationStretchRouter, prefix="/ws", tags="windmill-rotation-stretch-router"
)
app.include_router(
    standingCrossCrunchRouter, prefix="/ws", tags="standing-cross-crunch-router"
)
app.include_router(
    standingForwardFoldRouter, prefix="/ws", tags="standing-forward-fold-router"
)
