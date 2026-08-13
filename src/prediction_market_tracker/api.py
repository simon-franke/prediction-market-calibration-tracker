from fastapi import FastAPI

from prediction_market_tracker import __version__

app = FastAPI(title="Prediction Market Calibration Tracker", version=__version__)


@app.get("/health", tags=["operations"])
async def health() -> dict[str, str]:
    """Liveness endpoint for the hosted web service."""
    return {"status": "ok", "version": __version__}
