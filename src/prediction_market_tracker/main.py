import uvicorn


def main() -> None:
    uvicorn.run("prediction_market_tracker.api:app", host="0.0.0.0", port=8000)
