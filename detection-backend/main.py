from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.routes.upper_body.bicepRoutes import router as bicepRouter
from src.routes.body_detector_routes.fingerRoutes import router as fingerRouter
from src.routes.lower_body.squatRoutes import router as squatRouter
from src.routes.upper_body.pushupRoutes import router as pushupRouter
from src.routes.cardio.jumpingJackRoutes import router as jumpingJackRouter
from src.routes.lower_body.lungeRoutes import router as lungeRouter
from src.routes.cardio.highKneesRoutes import router as highKneesRouter
from src.routes.core.plankRoutes import router as plankRouter
from src.routes.body_detector_routes.bodyAnalysisRoutes import (
    router as bodyAnalysisRouter,
)
from src.routes.cardio.mountainClimberRoutes import router as mountainClimberRouter
from src.routes.upper_body.shoulderPressRoutes import router as shoulderPressRouter
from src.routes.upper_body.lateralRaiseRoutes import router as lateralRaiseRouter
from src.routes.upper_body.muayThaiJabRoutes import router as muayThaiJabRouter
from src.routes.core.deadbugRoutes import router as deadbugRouter
from src.routes.core.sidePlankRoutes import router as sidePlankRouter
from src.routes.lower_body.bridgePoseRoutes import router as bridgePoseRouter
from src.routes.core.birdDogRoutes import router as birdDogRouter
from src.routes.lower_body.calfRaiseRoutes import router as calfRaiseRouter
from src.routes.mobility.treePoseRoutes import router as treePoseRouter
from src.routes.mobility.warrioriiroutes import router as warrioriiRouter
from src.routes.mobility.cobraPoseRoutes import router as cobraPoseRouter
from src.routes.lower_body.chairPoseRoutes import router as chairPoseRouter
from src.routes.mobility.downwardDogRoutes import router as downwardDogRouter
from src.routes.upper_body.pikePushupRoutes import router as pikePushupRouter
from src.routes.cardio.tuckJumpRoutes import router as tuckJumpRouter
from src.routes.lower_body.sumoSquatRoutes import router as sumoSquatRouter
from src.routes.mobility.triangleRoutes import router as trianglePoseRouter
from src.routes.mobility.standingForwardFoldRoutes import (
    router as standingForwardFoldRouter,
)
from src.routes.mobility.reverseWarriorRoutes import router as reverseWarriorRouter
from src.routes.mobility.armCirclesRoutes import router as armCirclesRouter
from src.routes.cardio.standingCrossCrunchRoutes import (
    router as standingCrossCrunchRouter,
)
from src.routes.mobility.peacockPoseRoutes import router as peacockPoseRouter
from src.routes.core.hollowHoldRoutes import router as hollowHoldRouter
from src.routes.cardio.buttKicksRoutes import router as buttKicksRouter
from src.routes.lower_body.wallSitRoutes import router as wallSitRouter
from src.routes.core.legRaiseRoutes import router as legRaiseRouter
from src.routes.core.russianTwistRoutes import router as russianTwistRouter
from src.routes.core.flutterKicksRoutes import router as flutterKicksRouter
from src.routes.lower_body.singleLegSquatRoutes import router as singleLegSquatRouter
from src.routes.mobility.halfMoonRoutes import router as halfMoonRouter
from src.routes.core.bicycleCrunchRoutes import router as bicycleCrunchRouter
from src.routes.full_body.hinduPushupRoutes import router as hinduPushupRouter
from src.routes.upper_body.arnoldPressRoutes import router as arnoldPressRouter
from src.routes.mobility.dancerPoseRoutes import router as dancerPoseRouter
from src.routes.full_body.supermanRoutes import router as supermenPoseRouter
from src.routes.mobility.sideLegSwingRoutes import router as sideLegSwingRouter
from src.routes.mobility.frontLegSwingRoutes import router as frontLegSwingRouter
from src.routes.mobility.childsPoseRoutes import router as childsPoseRouter
from src.routes.full_body.skandhaChakraRoutes import router as skandhaChakraRouter
from src.routes.full_body.inchwormRoutes import router as inchwormRouter
from src.routes.upper_body.bentOverRowRoutes import router as bentOverRowRouter
from src.routes.full_body.shoulderStandRoutes import router as shoulderStandRouter
from src.routes.upper_body.tricepDipRoutes import router as tricepDipRouter
from src.routes.upper_body.singleArmCableLateralRaiseCrossbodyRoutes import (
    router as singleArmCableLateralRaiseCrossbodyRouter,
)
from src.routes.upper_body.standingTrunkRotationRoutes import (
    router as standingTrunkRotationRouter,
)
from src.routes.upper_body.frontRaiseRoutes import router as frontRaiseRouter
from src.routes.upper_body.seatedCableShrugRoutes import (
    router as seatedCableShrugRouter,
)
from src.routes.lower_body.advancedBridgePoseRoutes import (
    router as advancedBridgePoseRouter,
)
from src.routes.mobility.windmillRotationStretchRoutes import (
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
app.include_router(halfMoonRouter, prefix="/ws", tags="half-moon-router")
app.include_router(bicycleCrunchRouter, prefix="/ws", tags="bicycle-crunch-router")
app.include_router(hinduPushupRouter, prefix="/ws", tags="hindu-pushup-router")
app.include_router(arnoldPressRouter, prefix="/ws", tags="arnold-press-router")
app.include_router(dancerPoseRouter, prefix="/ws", tags="dancer-pose-router")
app.include_router(supermenPoseRouter, prefix="/ws", tags="supermen-pose-router")
app.include_router(sideLegSwingRouter, prefix="/ws", tags="side-leg-swing-router")
app.include_router(childsPoseRouter, prefix="/ws", tags="childs-pose-router")
app.include_router(frontLegSwingRouter, prefix="/ws", tags="front-leg-swing-router")
app.include_router(inchwormRouter, prefix="/ws", tags="inchworm-router")
app.include_router(skandhaChakraRouter, prefix="/ws", tags="skandha-chakra-router")
app.include_router(bentOverRowRouter, prefix="/ws", tags="bent-over-row-router")
app.include_router(shoulderStandRouter, prefix="/ws", tags="shoulder-stand-router")
app.include_router(frontRaiseRouter, prefix="/ws", tags="front-raise-router")
app.include_router(tricepDipRouter, prefix="/ws", tags="tricep-dip-router")
app.include_router(
    singleArmCableLateralRaiseCrossbodyRouter,
    prefix="/ws",
    tags="single-arm-cable-lateral-raise-cross-body-router",
)
app.include_router(
    standingTrunkRotationRouter, prefix="/ws", tags="standing-trunk-rotation-router"
)
app.include_router(
    seatedCableShrugRouter, prefix="/ws", tags="seated-cable-shrug-router"
)
app.include_router(
    advancedBridgePoseRouter, prefix="/ws", tags="advanced-bridge-pose-router"
)
app.include_router(
    windmillRotationStretchRouter, prefix="/ws", tags="windmill-rotation-stretch-router"
)
app.include_router(
    standingCrossCrunchRouter, prefix="/ws", tags="standing-cross-crunch-router"
)
app.include_router(
    standingForwardFoldRouter, prefix="/ws", tags="standing-forward-fold-router"
)
