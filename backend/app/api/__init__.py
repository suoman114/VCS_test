"""REST API / WebSocket 라우터 aggregation.

다른 에이전트가 새 라우터를 추가할 때는 여기에 include_router만 추가하면
된다 (예: testcase-manager-agent의 test_cases 라우터, backend-agent가
다음 웨이브에서 추가할 test_runs 라우터, log-collector-agent의 ws 라우터).
"""
from fastapi import APIRouter

from app.api.health import router as health_router
from app.api.settings import router as settings_router
from app.api.test_cases import router as test_cases_router
from app.api.test_runs import router as test_runs_router
from app.api.vcs import router as vcs_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(settings_router)
api_router.include_router(test_cases_router)
api_router.include_router(test_runs_router)
api_router.include_router(vcs_router)

__all__ = ["api_router"]
