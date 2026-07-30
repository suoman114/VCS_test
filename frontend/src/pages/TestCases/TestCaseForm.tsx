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

      <label>
        protocol_params (JSON)
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
