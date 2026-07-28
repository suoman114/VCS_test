"""테스트 fixture 경로 헬퍼: `docs/log_samples/` 실제 로그 샘플을 가리킨다.

대용량 로그 파일(vctp.log 8972줄 등)을 테스트에서도 파일 전체를 문자열로
읽지 않고, `app.services.log_parser.read_file_lines()`로 스트리밍해서
사용한다 (token-guardian-agent 원칙).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
LOG_SAMPLES_ROOT = REPO_ROOT / "docs" / "log_samples"

VOLTE_VCTP_LOG = LOG_SAMPLES_ROOT / "volte" / "vctp.log"
VOLTE_VCSM_LOG = LOG_SAMPLES_ROOT / "volte" / "vcsm.log"
VOLTE_VCMM_LOG = LOG_SAMPLES_ROOT / "volte" / "vcmm.log"
MCPTT_VCMC_LOG = LOG_SAMPLES_ROOT / "mcptt" / "vcmc.log"
MCPTT_VCMM_LOG = LOG_SAMPLES_ROOT / "mcptt" / "vcmm.log"
