# scenarios/sipp

McPTT 호처리 시험용 SIPp XML 시나리오. 담당 에이전트: `sipp-scenario-agent`.

시나리오 실행(프로세스 트리거)은 `backend-agent`가, 결과 로그 파싱은 `log-parser-callflow-agent`가 담당한다.
이 디렉토리에는 시나리오 XML과 실행 파라미터 문서만 둔다.

## 시나리오 파일

### `mcptt_basic_call.xml`

McPTT 기본 호처리(정상 흐름) 시나리오: `INVITE -> (100/180/183 optional) -> 200 OK -> ACK -> 통화 유지(3초) -> BYE -> 200 OK`

SIPp는 실제 McPTT 단말/네트워크가 VCS(vctp/vcmc)로 보내는 트래픽 역할(UAC)을 수행한다.
`docs/log_samples/mcptt/vcmc.log` 실측 로그를 기반으로 MCPTT 고유 헤더/바디(Contact의 `+g.3gpp.mcptt`,
`multipart/mixed` 바디의 `application/vnd.3gpp.mcptt-info+xml` + `application/sdp`, `P-Asserted-Identity` 등)를
반영했다. 상세 근거와 알려진 제약(TODO)은 파일 상단 XML 주석에 기술되어 있다 — 여기서는 요약만 다룬다.

## 실행 파라미터 (Test Case `protocol_params` <-> SIPp 커맨드라인 인자 매핑)

| Test Case `protocol_params` 키 (제안) | SIPp 인자 | 의미 | 기본값/예시 |
|---|---|---|---|
| `target_host` | `<remote_ip>` (positional, `sipp` 첫 인자) | VCS(vctp) 대상 IP | 환경별 상이 (TBD, §13) |
| `target_port` | `<remote_ip>:<remote_port>` (positional) | VCS SIP 리스닝 포트 | 예: `5060` |
| `local_ip` | `-i <local_ip>` | SIPp 실행 호스트의 로컬 IP (바인딩) | 환경별 상이 (TBD, §13 — 로컬/원격 실행 위치 미확정) |
| `local_port` | `-p <local_port>` | SIPp 로컬 SIP 포트 | 예: `5080` |
| `transport` | `-t u1` (UDP, 기본값) | SIP 전송 프로토콜 | UDP (실측 로그 기준) |
| `callee_id` | `-s <service>` | 착신 MCPTT 번호(피호출자) | 예: `+82585109100` |
| `caller_id` | `-key mcptt_caller_id <value>` | 발신 MCPTT 사용자 ID | 예: `+82585102956` |
| `group_id` | `-key mcptt_group_id <value>` | MCPTT 그룹 ID | 예: `+8298011990000` |
| `mcptt_domain` | `-key mcptt_domain <value>` | 발신자 PLMN 도메인(FQDN) | TBD (운영 값 미확인, 예시: `ptt.example.mnc001.mcc450.3gppnetwork.org`) |
| `calls_count` | `-m <N>` | 총 호 발생 수 | 기본 시험은 `1` 권장 (아래 "알려진 제약" 참고) |
| `call_rate` | `-r <rate>` | 초당 호 발생율(calls/sec) | 기본 호처리 검증 목적이면 `1` 권장 |
| (판정/로깅용, protocol_params 아님) | `-trace_msg -trace_screen -trace_stat` | SIPp 자체 로그/통계 생성 | log-parser-callflow-agent가 SIPp 로그와 VCS 로그를 Call-ID/타임스탬프로 상관관계 매칭할 때 사용 (CLAUDE.md §3.2) |

> `-key`는 SIPp 커맨드라인에서 시나리오 내 커스텀 키워드(`[mcptt_caller_id]` 등)를 치환하는 표준 옵션이다
> (`-key <keyword> <value>`). SIPp 버전에 따라 지원 여부가 다를 수 있으므로, backend-agent가 실제 실행
> 전에 사용할 SIPp 버전에서 `-key` 지원을 확인해야 한다 (TBD).

## SIPp 실행 커맨드라인 예시

```bash
sipp <target_host>:<target_port> \
  -sf scenarios/sipp/mcptt_basic_call.xml \
  -i <local_ip> \
  -p <local_port> \
  -t u1 \
  -s <callee_id> \
  -key mcptt_caller_id <caller_id> \
  -key mcptt_group_id <group_id> \
  -key mcptt_domain <mcptt_domain> \
  -m 1 -r 1 \
  -trace_msg -trace_screen -trace_stat \
  -message_file storage/logs/<test_case_id>/<run_id>/sipp_messages.log \
  -screen_file storage/logs/<test_case_id>/<run_id>/sipp_screen.log \
  -stf storage/logs/<test_case_id>/<run_id>/sipp_stats.csv
```

- `<target_host>`, `<local_ip>` 등 실제 호스트/경로 값은 이 문서에 하드코딩하지 않는다 — 실행 시점에
  backend-agent가 Test Case의 `protocol_params`에 맞게 채운다.
- `storage/logs/{test_case_id}/{run_id}/` 하위 경로는 CLAUDE.md §3.3(원본 로그 보존 원칙)을 따른다.
- SIPp 실행 위치(2026-07-29 확인: 실제 배포는 VCS와 별도인 전용 SIPp 호스트) —
  `protocol_params.sipp_exec_mode`("local"|"ssh")로 선택하며 기본값은 `Settings.sipp_exec_mode`.
  `ssh` 모드는 `McpttBasicCallExecutor._run_sipp_remote`(`backend/app/services/mcptt/executor.py`)가
  이 시나리오/커맨드라인 정의를 그대로 재사용해, 시나리오 XML을 SIPp 호스트로 업로드한 뒤 SSH로
  실행하고 SIPp 로그(message/screen/stat)를 로컬로 다운로드한다.

## 알려진 제약 (backend-agent/log-parser-callflow-agent 공유용 요약)

1. **다건(concurrent) 호 실행 시 주의**: `mcptt_basic_call.xml`의 multipart 바디 내부 두 파트(mcptt-info+xml, sdp)의
   `Content-Length`는 SIPp가 자동 재계산하지 못하는 고정값이다(단일 호, 특정 `local_ip` 길이 기준으로 계산됨).
   `-m 1`(단일 호) 기준으로는 정확하지만, `-m`을 늘리거나 `local_ip`가 계산 기준과 다른 자릿수면 내부 Content-Length가
   실제 바이트 수와 어긋날 수 있다. SIP 메시지 전체의 프레이밍(바깥쪽 Content-Length)은 `[len]`으로 항상 정확하므로
   메시지 자체는 유효하지만, VCS가 중첩 파트 Content-Length를 엄격 검증하는지는 TBD — 확인되는 대로 시나리오를
   갱신하거나 별도 전처리(길이 재계산) 스텝을 추가해야 할 수 있다.
2. McPTT 플로어 제어(발언권 취득/해제, `recording_change_req/res`)는 시그널링이 아닌 미디어 평면 트래픽으로 판단되어
   이번 기본 호처리(시그널링) 시나리오에는 포함하지 않았다.
3. MCPTT PLMN 도메인, `mcptt-Params`의 전체 3GPP 스키마 등 실제 규격 확정 전까지 TBD로 남긴 항목이 있다
   (시나리오 파일 상단 주석 TODO 2, 3 참고).
