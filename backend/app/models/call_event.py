"""CallEvent 모델 (CLAUDE.md §6).

로그 어댑터(`app.services.log_parser`)가 원본 로그 라인/블록을 파싱해 만드는
표준화된 이벤트 레코드. Call Flow 생성(`app.services.callflow`)과 Pass/Fail
판정 규칙 엔진의 공통 입력 스키마다.

NOTE(FK 미확정과 동일한 패턴): run_id는 `TestRun.id`(String(36))를 참조한다.
"""
from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid4_str() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CallEventSource(str, enum.Enum):
    """CLAUDE.md §9.1에서 확인된 프로세스별 로그 소스.

    - vctp_log: 패킷 relay 로그. 대부분 노이즈(DumpPacketTask.java:156)이며
      Call Flow에는 기본적으로 필터링 대상. SIP relay 참고용
      (DumpPacketTask.java:131)만 저비중으로 채택.
    - vcsm_log (VoLTE) / vcmc_log (McPTT): SIP(+MCPTT) 시그널링 1차 소스.
    - vcmm_log (VoLTE·McPTT 공통): 녹취 제어(JSON, RMQ) 메시지. Pass/Fail
      판정 1차 근거.
    - sipp_log: McPTT SIPp 자체 로그/통계. TODO(SIPp Scenario Agent와 조율):
      SIPp 로그 포맷/경로가 아직 확정되지 않아 어댑터 인터페이스만 예약해
      둔다 (log_parser/sipp_adapter.py 참고).
    """

    VCTP_LOG = "vctp_log"
    VCSM_LOG = "vcsm_log"
    VCMM_LOG = "vcmm_log"
    VCMC_LOG = "vcmc_log"
    SIPP_LOG = "sipp_log"


class CallEvent(Base):
    __tablename__ = "call_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid4_str)

    # 느슨한 참조가 아니라 실제 FK: TestRun 모델은 이미 merge되어 있다.
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("test_runs.id"), index=True, nullable=False
    )

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    source: Mapped[CallEventSource] = mapped_column(
        SAEnum(CallEventSource, native_enum=False, length=16), nullable=False
    )

    # 원본 라인 혹은 원본 블록(멀티라인 SIP 메시지/JSON) 전체. 재현/디버깅용.
    # 대용량 로그 원문 전체를 여기 담지 않는다 — 어댑터가 이벤트로 인정한
    # 블록만 저장한다 (token-guardian-agent 원칙).
    raw_line: Mapped[str] = mapped_column(Text, nullable=False)

    # 예: SIP_INVITE, SIP_200, RECORDING_START_REQ, RECORDING_STOP_RES,
    # RECORDING_CHANGE_REQ, RECORDING_CHANGE_RES, VCTP_SIP_RELAY 등.
    # CLAUDE.md §6 참고. 결정론적 어댑터가 채우는 문자열 태그이므로
    # DB 레벨 Enum으로 강하게 제약하지 않는다(신규 타입 추가 시 마이그레이션
    # 불필요하게 하기 위함).
    parsed_type: Mapped[str] = mapped_column(String(64), nullable=False)

    call_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # SIP 상태 코드(200, 180, 403 ...) 또는 vcmm JSON의 header.reasonCode.
    reason_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Call Flow 렌더링 순서. 같은 run_id 내에서 어댑터/병합 단계가 부여한다.
    seq_no: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CallEvent id={self.id} run_id={self.run_id} source={self.source} "
            f"parsed_type={self.parsed_type} seq_no={self.seq_no}>"
        )
