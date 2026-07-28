import { useEffect, useState } from "react";
import type { TestCaseCategory, TestCaseCreate, TestCaseRead, TestCaseType, TestCaseUpdate } from "../../api/types";

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

      <label>
        config_ref * (VoLTE: vctp 설정 파일 경로 / McPTT: SIPp 시나리오 XML 경로)
        <input value={configRef} onChange={(e) => setConfigRef(e.target.value)} required />
      </label>

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
