# testcases

시험 케이스 YAML 정의 (git으로 버전 관리). 스키마는 `testcase-manager-agent`가 정의한다.

```
volte/   # VoLTE 시험 케이스 정의
mcptt/   # McPTT 시험 케이스 정의
```

## YAML 스키마

`backend/app/schemas/test_case.py`의 `TestCaseCreate`와 1:1 대응한다. 예시는
`volte/volte_basic_call_001.yaml`, `mcptt/mcptt_basic_call_001.yaml` 참고.

| 필드 | 타입 | 필수 | 설명 |
|---|---|---|---|
| `id` | string | 아니오 | 생략 시 최초 import 때 서버가 UUID 생성 |
| `name` | string | 예 | 표시 이름 (DB에서 unique) |
| `description` | string | 아니오 | 설명 |
| `category` | `volte` \| `mcptt` | 예 | 프로토콜 축 |
| `test_type` | `basic_call` \| `performance` \| `abnormal` | 아니오(기본 `basic_call`) | 시험 유형 축 |
| `config_ref` | string | 예 | VoLTE: 설정 파일 경로. McPTT: 메인 SIPp 시나리오 경로 |
| `protocol_params` | object | 아니오(기본 `{}`) | 프로토콜별 부가 파라미터 (자유 구조) |
| `pass_criteria` | object | 아니오(기본 `{}`) | 판정 규칙 (`required_events`, `forbidden_patterns`, `max_duration_sec` 등) |

## DB <-> YAML 동기화 설계 노트

Phase 1 완전 구현은 선택 사항이나, 아래 방식을 기준으로 삼는다.

- **가져오기(import, YAML -> DB)**: YAML 파일을 파싱해 `TestCaseCreate`로 검증 후
  `POST /api/test-cases`와 동일한 로직으로 upsert한다. 매칭 키는 `id`(있으면
  우선) 없으면 `name`. 파일 경로는 저장소 루트 기준 상대 경로로
  `TestCase.yaml_path`에 기록해 이후 재-export 시 어떤 파일에 쓸지 추적한다.
- **내보내기(export, DB -> YAML)**: `TestCase.yaml_path`가 있으면 해당 파일을
  덮어쓰고, 없으면 `testcases/{category}/{id 또는 slugify(name)}.yaml`로 새로
  생성한다(그 경로를 다시 `yaml_path`에 기록).
- **충돌 처리**: 두 방향 모두 최종 승자는 "이번 작업의 대상"이다(즉 import는
  YAML이, export는 DB가 이긴다). 자동 병합은 하지 않는다 — 운영자가 git diff로
  변경 사항을 검토하고 명시적으로 import/export를 실행하는 것을 전제로 한다.
- **실행 방식**: CLI 스크립트(예: `backend/scripts/sync_test_cases.py`, 아직
  미구현) 또는 관리용 API 엔드포인트(`POST /api/test-cases/import`,
  `POST /api/test-cases/{id}/export`, 아직 미구현)로 트리거하는 두 가지 방식을
  모두 고려할 수 있다. 실제 구현 시점에 backend-agent와 협의해 확정한다.
