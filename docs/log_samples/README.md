# 로그 샘플 보관 위치

실제 VCS 프로세스 로그 샘플을 여기에 보관한다. `log-parser-callflow-agent`가 이 샘플을 기준으로 파서와 Call Flow 생성 로직을 구현한다.

```
docs/log_samples/
├── volte/
│   ├── vctp.log   # 패킷 캡처/릴레이 (대부분 노이즈, DumpPacketTask 라인)
│   ├── vcsm.log   # SIP 시그널링 (Call Flow 1차 소스)
│   └── vcmm.log   # 녹취 제어(JSON) — Pass/Fail 판정 1차 근거
└── mcptt/
    ├── vcmc.log   # SIP + MCPTT 시그널링 (Call Flow 1차 소스)
    └── vcmm.log   # 녹취 제어(JSON) — Pass/Fail 판정 1차 근거
```

**현재 상태**: 위 5개 파일은 VoLTE/McPTT 각각 **성공 케이스 1건**의 실제 로그다. 로그 그래머, 프로세스 역할, 성공 판정 기준(`vcmm.log`의 `recording_stop_res.reasonCode == 2000`)은 `CLAUDE.md` §2, §3, §9에 반영되어 있다.

**추가로 필요한 것**: 실패/타임아웃/에러 케이스 로그. 지금까지는 성공 케이스만 있어 Pass/Fail 판정 규칙 중 "Fail" 쪽 패턴을 아직 만들 수 없다 (`CLAUDE.md` §13 TBD 참고). 실패 사례를 추가로 올려주시면 같은 방식(`volte/`, `mcptt/` 하위, 상황을 알 수 있는 파일명)으로 넣어주면 된다.

> 참고: 로그 파일이 큰 경우(`vctp.log`는 약 9,000줄) 에이전트는 전체를 한 번에 읽지 않고 발췌/스크립트 기반으로 분석한다 (`token-guardian-agent` 정책, `CLAUDE.md` §9 참고).
