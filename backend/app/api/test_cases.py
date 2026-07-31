"""Test Case CRUD API (CLAUDE.md §6, §7).

라우터는 얇게 유지한다: 검증은 Pydantic 스키마(`app.schemas.test_case`)가,
enum 변환 등 아주 단순한 매핑만 이 파일에서 처리하고 그 외 로직은 없다.
복잡한 비즈니스 로직(예: YAML 동기화 실행, 실행기 트리거)은 이후
backend-agent가 별도 서비스 모듈로 분리해 추가한다.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.test_case import TestCase, TestCaseCategory, TestCaseType
from app.schemas.test_case import (
    TestCaseCreate,
    TestCaseListResponse,
    TestCaseRead,
    TestCaseUpdate,
)

router = APIRouter(prefix="/test-cases", tags=["test-cases"])


def _get_or_404(db: Session, test_case_id: str) -> TestCase:
    test_case = db.get(TestCase, test_case_id)
    if test_case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="TestCase not found")
    return test_case


def _create_kwargs(payload: TestCaseCreate) -> dict[str, Any]:
    """Pydantic 스키마 -> TestCase 생성자 kwargs.

    category/test_type은 SQLAlchemy Enum 컬럼(enum_class 기반)이 기대하는
    실제 Enum 멤버로 변환한다. id는 명시적으로 None을 넣지 않는다 — 컬럼
    default(uuid4)가 적용되려면 속성 자체를 설정하지 않아야 한다.
    """
    data = payload.model_dump(exclude={"id"})
    data["category"] = TestCaseCategory(data["category"])
    data["test_type"] = TestCaseType(data["test_type"])
    return data


@router.get("", response_model=TestCaseListResponse)
def list_test_cases(
    category: str | None = Query(default=None, description="volte | mcptt"),
    test_type: str | None = Query(default=None, description="basic_call | performance | abnormal"),
    name: str | None = Query(default=None, description="이름 부분 일치 검색"),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> TestCaseListResponse:
    stmt = select(TestCase)

    if category is not None:
        try:
            stmt = stmt.where(TestCase.category == TestCaseCategory(category))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid category: {category!r}") from exc

    if test_type is not None:
        try:
            stmt = stmt.where(TestCase.test_type == TestCaseType(test_type))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid test_type: {test_type!r}") from exc

    if name:
        stmt = stmt.where(TestCase.name.ilike(f"%{name}%"))

    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    items = (
        db.execute(stmt.order_by(TestCase.created_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    return TestCaseListResponse(items=list(items), total=total)


@router.get("/{test_case_id}", response_model=TestCaseRead)
def get_test_case(test_case_id: str, db: Session = Depends(get_db)) -> TestCase:
    return _get_or_404(db, test_case_id)


@router.post("", response_model=TestCaseRead, status_code=status.HTTP_201_CREATED)
def create_test_case(payload: TestCaseCreate, db: Session = Depends(get_db)) -> TestCase:
    if payload.id and db.get(TestCase, payload.id) is not None:
        raise HTTPException(status_code=409, detail=f"TestCase id already exists: {payload.id}")
    if db.execute(select(TestCase).where(TestCase.name == payload.name)).scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"TestCase name already exists: {payload.name}")

    test_case = TestCase(**_create_kwargs(payload))
    if payload.id:
        test_case.id = payload.id

    db.add(test_case)
    db.commit()
    db.refresh(test_case)
    return test_case


@router.patch("/{test_case_id}", response_model=TestCaseRead)
def update_test_case(
    test_case_id: str, payload: TestCaseUpdate, db: Session = Depends(get_db)
) -> TestCase:
    test_case = _get_or_404(db, test_case_id)

    updates = payload.model_dump(exclude_unset=True)
    if "category" in updates:
        updates["category"] = TestCaseCategory(updates["category"])
    if "test_type" in updates:
        updates["test_type"] = TestCaseType(updates["test_type"])
    if "name" in updates and updates["name"] != test_case.name:
        existing = db.execute(
            select(TestCase).where(TestCase.name == updates["name"])
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(status_code=409, detail=f"TestCase name already exists: {updates['name']}")

    for field_name, value in updates.items():
        setattr(test_case, field_name, value)

    db.add(test_case)
    db.commit()
    db.refresh(test_case)
    return test_case


@router.delete("/{test_case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_test_case(test_case_id: str, db: Session = Depends(get_db)) -> None:
    test_case = _get_or_404(db, test_case_id)
    db.delete(test_case)
    db.commit()
