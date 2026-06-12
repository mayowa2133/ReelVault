import os

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.routes.diagnostics import router as diagnostics_router
from app.routes.sheets import router as sheets_router
from app.routes.tasks import router as tasks_router
from app.routes.telegram import router as telegram_router
from app.services.downloader_service import downloader_runtime_info
from app.services.social_video_service import SUPPORTED_URL_FEATURES
from app.utils.errors import ReelVaultError, public_error_message
from app.utils.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(debug=settings.enable_debug_logging)
logger = get_logger(__name__)

app = FastAPI(
    title="ReelVault",
    description="Short-form social video inspiration automation webhook service.",
    version="0.1.0",
)

app.include_router(telegram_router)
app.include_router(tasks_router)
app.include_router(sheets_router)
app.include_router(diagnostics_router)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "runtime": {
            "service": os.getenv("K_SERVICE"),
            "revision": os.getenv("K_REVISION"),
            "configuration": os.getenv("K_CONFIGURATION"),
        },
        "diagnostics": {
            "routes": sorted(
                route.path
                for route in app.routes
                if getattr(route, "path", "").startswith("/diagnostics/")
            ),
        },
        "url_support": {
            "features": list(SUPPORTED_URL_FEATURES),
        },
        "downloader": downloader_runtime_info(settings),
    }


@app.exception_handler(ReelVaultError)
async def reelvault_error_handler(_: Request, exc: ReelVaultError) -> JSONResponse:
    logger.warning(
        "handled_reelvault_error",
        extra={"code": exc.code, "step": exc.step, "message_safe": public_error_message(exc)},
    )
    return JSONResponse(status_code=400, content={"ok": False, "error": public_error_message(exc)})


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("unhandled_request_error", extra={"message_safe": public_error_message(exc)})
    return JSONResponse(status_code=500, content={"ok": False, "error": "Internal server error"})
