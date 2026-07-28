"""CallFlowDiagram 모델 (CLAUDE.md §6).

`app.services.callflow.generator`가 `CallEvent` 시퀀스로부터 생성한 Mermaid
`sequenceDiagram` 텍스트를 Test Run 단위로 보관한다. 프론트엔드는 이 텍스트를
그대로 렌더링하면 된다 (별도 다이어그램 엔진 불필요, CLAUDE.md §4).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid4_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CallFlowDiagram(Base):
    __tablename__ = "call_flow_diagrams"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4_str)

    # 1 Test Run : 1 최신 Call Flow. 재생성(재파싱) 시 upsert로 갱신한다.
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("test_runs.id"), unique=True, index=True, nullable=False
    )

    mermaid_source: Mapped[str] = mapped_column(Text, nullable=False)

    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CallFlowDiagram run_id={self.run_id} generated_at={self.generated_at}>"
