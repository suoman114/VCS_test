# 로그 샘플 보관 위치

실제 VCS / vctp / SIPp 로그 샘플을 여기에 넣어주세요. `log-parser-callflow-agent`가 이 샘플을 기준으로 파서와 Call Flow 생성 로직을 구현합니다.

권장 구조:

```
docs/log_samples/
├── volte/     # VCS/vctp 로그 샘플
└── mcptt/     # VCS 로그 + SIPp 로그 샘플 (McPTT)
```

파일명에 상황(정상 호처리 성공/실패/타임아웃 등)을 알 수 있게 표기해주시면 파싱 규칙과 Pass/Fail 판정 기준을 정확히 잡는 데 도움이 됩니다.

> 참고: 로그 파일이 큰 경우에도 에이전트는 전체를 한 번에 읽지 않고 발췌/스크립트 기반으로 분석합니다 (`token-guardian-agent` 정책, `CLAUDE.md` §9 참고).
