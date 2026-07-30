import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import type { TestCaseCategory, TestCaseCreate, TestCaseRead, TestCaseType, TestCaseUpdate } from "../../api/types";
import { vcsApi } from "../../api/vcs";

interface TestCaseFormProps {
  initial?: TestCaseRead | null;
  onCancel: () => void;
  onSubmit: (data: TestCaseCreate | TestCaseUpdate) => Promise<void>;
}

const CATEGORY_OPTIONS: TestCaseCategory[] = ["volte", "mcptt"];
const TEST_TYPE_OPTIONS: TestCaseType[] = ["basic_call", "performance", "abnormal"];

/** JSON object textarea 를 위한 안전 파서. 빈 문자열은 {}로 취급한다. */
function parseJsonObject(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  const parsed = JSON.parse(trimmed);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("JSON 객체 형식이어야 합니다");
  }
  return parsed as Record<string, unknown>;
}

export function TestCaseForm({ initial, onCancel, onSubmit }: TestCaseFormProps) {
  const [id, setId] = useState(initial?.id ?? "");
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [category, setCategory] = useState<TestCaseCategory>(initial?.category ?? "volte");
  const [testType, setTestType] = useState<TestCaseType>(initial?.test_type ?? "basic_call");
  const [configRef, setConfigRef] = useState(initial?.config_ref ?? "");
  const [protocolParamsText, setProtocolParamsText] = useState(
    initial ? JSON.stringify(initial.protocol_params, null, 2) : "{}",
  );
  const [passCriteriaText, setPassCriteriaText] = useState(
    initial ? JSON.stringify(initial.pass_criteria, null, 2) : "{}",
  );
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // VoLTE 전용: VCS의 vctp 샘플 pcap 디렉토리 목록 (select box용).
  const [volteSampleFiles, setVolteSampleFiles] = useState<string[] | null>(null);
  const [volteSampleFilesError, setVolteSampleFilesError] = useState<string | null>(null);
  const [volteSampleFilesLoading, setVolteSampleFilesLoading] = useState(false);

  // McPTT 전용: SIPp 전용 호스트의 mcptt_sim_dir 시나리오 XML 목록 (select box용,
  // 2026-07-29 — VoLTE의 pcap 샘플 select box와 동일한 패턴).
  const [mcpttScenarioFiles, setMcpttScenarioFiles] = useState<string[] | null>(null);
  const [mcpttScenarioFilesError, setMcpttScenarioFilesError] = useState<string | null>(null);
  const [mcpttScenarioFilesLoading, setMcpttScenarioFilesLoading] = useState(false);

  // McPTT 성능(performance) 시험 전용: call_rate/rate_period_ms/max_duration_sec를
  // protocol_params JSON에 직접 타이핑하지 않고 입력 박스로 받는다(2026-07-30
  // 요청 — "인프라 오류: protocol_params에 call_rate가 필요하다" 에러가 반복돼서,
  // scenario_file select box와 동일한 패턴으로 전용 입력 필드를 추가).
  const [callRate, setCallRate] = useState("");
  const [ratePeriodMs, setRatePeriodMs] = useState("1000");
  const [maxDurationSec, setMaxDurationSec] = useState("");

  useEffect(() => {
    if (category !== "volte") return;
    let cancelled = false;
    setVolteSampleFilesLoading(true);
    setVolteSampleFilesError(null);
    vcsApi
      .volteSampleFiles()
      .then((res) => {
        if (!cancelled) setVolteSampleFiles(res.items);
      })
      .catch((err) => {
        if (!cancelled) {
          setVolteSampleFiles(null);
          setVolteSampleFilesError(
            err instanceof ApiError ? err.message : "VCS 서버에서 샘플 파일 목록을 가져오지 못했습니다",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setVolteSampleFilesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [category]);

  useEffect(() => {
    if (category !== "mcptt") return;
    let cancelled = false;
    setMcpttScenarioFilesLoading(true);
    setMcpttScenarioFilesError(null);
    vcsApi
      .mcpttScenarioFiles()
      .then((res) => {
        if (!cancelled) setMcpttScenarioFiles(res.items);
      })
      .catch((err) => {
        if (!cancelled) {
          setMcpttScenarioFiles(null);
          setMcpttScenarioFilesError(
            err instanceof ApiError ? err.message : "SIPp 서버에서 시나리오 파일 목록을 가져오지 못했습니다",
          );
        }
      })
      .finally(() => {
        if (!cancelled) setMcpttScenarioFilesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [category]);

  useEffect(() => {
    setId(initial?.id ?? "");
    setName(initial?.name ?? "");
    setDescription(initial?.description ?? "");
    setCategory(initial?.category ?? "volte");
    setTestType(initial?.test_type ?? "basic_call");
    setConfigRef(initial?.config_ref ?? "");
    setProtocolParamsText(initial ? JSON.stringify(initial.protocol_params, null, 2) : "{}");
    setPassCriteriaText(initial ? JSON.stringify(initial.pass_criteria, null, 2) : "{}");

    // 기존 성능 시험 케이스를 수정할 때는 protocol_params에 이미 저장된
    // 값을 입력 박스에도 반영한다(없으면 rate_period_ms만 기본값 1000).
    const params = (initial?.protocol_params ?? {}) as Record<string, unknown>;
    setCallRate(params.call_rate !== undefined && params.call_rate !== null ? String(params.call_rate) : "");
    setRatePeriodMs(
      params.rate_period_ms !== undefined && params.rate_period_ms !== null ? String(params.rate_period_ms) : "1000",
    );
    setMaxDurationSec(
      params.max_duration_sec !== undefined && params.max_duration_sec !== null
        ? String(params.max_duration_sec)
        : "",
    );
  }, [initial]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    let protocolParams: Record<string, unknown>;
    let passCriteria: Record<string, unknown>;
    try {
      protocolParams = parseJsonObject(protocolParamsText);
      passCriteria = parseJsonObject(passCriteriaText);
    } catch {
      setError("protocol_params / pass_criteria는 올바른 JSON 객체여야 합니다");
      return;
    }

    // VoLTE는 select box에서 고른 파일명을 protocol_params.sample_file에도 반영한다
    // (config_ref와 항상 동일한 값을 쓰게 해서 둘이 어긋나는 걸 방지).
    if (category === "volte" && configRef) {
      protocolParams = { ...protocolParams, sample_file: configRef };
    }
    // McPTT도 동일한 패턴 — select box에서 고른 시나리오 파일명을
    // protocol_params.scenario_file에 반영한다(2026-07-29).
    if (category === "mcptt" && configRef) {
      protocolParams = { ...protocolParams, scenario_file: configRef };
    }

    // McPTT 성능 시험: call_rate 입력 박스 값을 protocol_params에 반영한다
    // (2026-07-30) — McpttPerformanceExecutor가 필수로 요구하는 값이라
    // 안 채우면 실행 시 "protocol_params에 call_rate가 필요하다" 에러가 난다.
    if (category === "mcptt" && testType === "performance") {
      if (!callRate.trim()) {
        setError("call_rate(호 발생 수)를 입력해야 합니다");
        return;
      }
      protocolParams = {
        ...protocolParams,
        call_rate: Number(callRate),
        rate_period_ms: ratePeriodMs.trim() ? Number(ratePeriodMs) : 1000,
      };
      if (maxDurationSec.trim()) {
        protocolParams = { ...protocolParams, max_duration_sec: Number(maxDurationSec) };
      }
    }

    setSubmitting(true);
    try {
      if (initial) {
        const update: TestCaseUpdate = {
          name,
          description: description || null,
          category,
          test_type: testType,
          config_ref: configRef,
          protocol_params: protocolParams,
          pass_criteria: passCriteria,
        };
        await onSubmit(update);
      } else {
        const create: TestCaseCreate = {
          id: id || undefined,
          name,
          description: description || undefined,
          category,
          test_type: testType,
          config_ref: configRef,
          protocol_params: protocolParams,
          pass_criteria: passCriteria,
        };
        await onSubmit(create);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "저장 실패");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="test-case-form" onSubmit={handleSubmit}>
      <h3>{initial ? "시험 케이스 수정" : "시험 케이스 등록"}</h3>

      {!initial && (
        <label>
          ID (선택, 비우면 서버 자동 생성)
          <input value={id} onChange={(e) => setId(e.target.value)} placeholder="예: volte-basic-001" />
        </label>
      )}

      <label>
        이름 *
        <input value={name} onChange={(e) => setName(e.target.value)} required />
      </label>

      <label>
        설명
        <textarea value={description ?? ""} onChange={(e) => setDescription(e.target.value)} rows={2} />
      </label>

      <div className="form-row">
        <label>
          프로토콜 *
          <select value={category} onChange={(e) => setCategory(e.target.value as TestCaseCategory)}>
            {CATEGORY_OPTIONS.map((c) => (
              <option key={c} value={c}>
                {c === "volte" ? "VoLTE" : "McPTT"}
              </option>
            ))}
          </select>
        </label>

        <label>
          시험 유형
          <select value={testType} onChange={(e) => setTestType(e.target.value as TestCaseType)}>
            {TEST_TYPE_OPTIONS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </label>
      </div>

      {category === "volte" ? (
        <label>
          pcap 샘플 파일 * (VCS의 /home/vcs/vctp/sample 목록)
          {volteSampleFilesLoading && <div className="form-hint">목록 불러오는 중...</div>}
          {volteSampleFilesError && (
            <div className="form-hint form-hint-error">
              {volteSampleFilesError} — VCS 연결을 확인하거나 파일명을 직접 입력하세요.
            </div>
          )}
          {volteSampleFiles ? (
            <select value={configRef} onChange={(e) => setConfigRef(e.target.value)} required>
              <option value="" disabled>
                파일 선택...
              </option>
              {volteSampleFiles.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
              {configRef && !volteSampleFiles.includes(configRef) && (
                <option value={configRef}>{configRef} (현재 값, 목록에 없음)</option>
              )}
            </select>
          ) : (
            <input
              value={configRef}
              onChange={(e) => setConfigRef(e.target.value)}
              placeholder="예: imsVideo30sec.pcap"
              required
            />
          )}
        </label>
      ) : (
        <label>
          시나리오 XML 파일 * (SIPp 서버의 /root/mcptt_sim 목록)
          {mcpttScenarioFilesLoading && <div className="form-hint">목록 불러오는 중...</div>}
          {mcpttScenarioFilesError && (
            <div className="form-hint form-hint-error">
              {mcpttScenarioFilesError} — SIPp 서버 연결을 확인하거나 파일명을 직접 입력하세요.
            </div>
          )}
          {mcpttScenarioFiles ? (
            <select value={configRef} onChange={(e) => setConfigRef(e.target.value)} required>
              <option value="" disabled>
                파일 선택...
              </option>
              {mcpttScenarioFiles.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
              {configRef && !mcpttScenarioFiles.includes(configRef) && (
                <option value={configRef}>{configRef} (현재 값, 목록에 없음)</option>
              )}
            </select>
          ) : (
            <input
              value={configRef}
              onChange={(e) => setConfigRef(e.target.value)}
              placeholder="예: mcptt_basic_call.xml"
              required
            />
          )}
        </label>
      )}

      {category === "mcptt" && testType === "performance" && (
        <>
          <div className="form-row">
            <label>
              호 발생 수(call_rate) *
              <input
                type="number"
                min="1"
                value={callRate}
                onChange={(e) => setCallRate(e.target.value)}
                placeholder="예: 1"
                required
              />
            </label>
            <label>
              주기(ms, rate_period_ms)
              <input
                type="number"
                min="1"
                value={ratePeriodMs}
                onChange={(e) => setRatePeriodMs(e.target.value)}
                placeholder="1000"
              />
            </label>
            <label>
              최대 실행 시간(초, 선택)
              <input
                type="number"
                min="1"
                value={maxDurationSec}
                onChange={(e) => setMaxDurationSec(e.target.value)}
                placeholder="비우면 '시험 종료' 버튼으로만 종료"
              />
            </label>
          </div>
          <div className="form-hint">
            {callRate.trim()
              ? `${ratePeriodMs.trim() || "1000"}ms마다 ${callRate}콜 발생`
              : "예: call_rate=1, rate_period_ms=1000 → 초당 1콜"}
            {maxDurationSec.trim()
              ? ` · 최대 ${maxDurationSec}초 뒤 자동 종료`
              : " · 최대 실행 시간을 안 정하면 '시험 종료' 버튼을 눌러야만 끝납니다"}
          </div>
        </>
      )}

      <label>
        protocol_params (JSON)
        {category === "mcptt" && testType === "performance" && (
          <div className="form-hint">
            call_rate/rate_period_ms/max_duration_sec은 위 입력 박스 값이 항상 우선 적용됩니다 — 여기 직접
            넣어도 무시됩니다.
          </div>
        )}
        <textarea
          value={protocolParamsText}
          onChange={(e) => setProtocolParamsText(e.target.value)}
          rows={4}
          spellCheck={false}
        />
      </label>

      <label>
        pass_criteria (JSON)
        <textarea
          value={passCriteriaText}
          onChange={(e) => setPassCriteriaText(e.target.value)}
          rows={4}
          spellCheck={false}
        />
      </label>

      {error && <div className="form-error">{error}</div>}

      <div className="form-actions">
        <button type="button" onClick={onCancel} disabled={submitting}>
          취소
        </button>
        <button type="submit" disabled={submitting}>
          {submitting ? "저장 중..." : "저장"}
        </button>
      </div>
    </form>
  );
}
