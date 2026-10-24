from fastapi import APIRouter

from app.api.routes import backtest, coach, market_data, model, risk, system

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(market_data.router)
api_router.include_router(risk.router)
api_router.include_router(model.router)
api_router.include_router(backtest.router)
api_router.include_router(coach.router)
