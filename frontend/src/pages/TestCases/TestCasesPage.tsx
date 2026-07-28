import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { testCasesApi } from "../../api/testCases";
import { testRunsApi } from "../../api/testRuns";
import type { TestCaseCategory, TestCaseCreate, TestCaseRead, TestCaseType, TestCaseUpdate } from "../../api/types";
import { TestCaseForm } from "./TestCaseForm";
import "./TestCasesPage.css";

const PAGE_SIZE = 20;

export function TestCasesPage() {
  const navigate = useNavigate();
  const [items, setItems] = useState<TestCaseRead[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [categoryFilter, setCategoryFilter] = useState<TestCaseCategory | "">("");
  const [testTypeFilter, setTestTypeFilter] = useState<TestCaseType | "">("");
  const [nameFilter, setNameFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [editing, setEditing] = useState<TestCaseRead | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await testCasesApi.list({
        category: categoryFilter || undefined,
        test_type: testTypeFilter || undefined,
        name: nameFilter || undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setItems(res.items);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "목록 조회 실패");
    } finally {
      setLoading(false);
    }
  }, [categoryFilter, testTypeFilter, nameFilter, offset]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleCreateOrUpdate(data: TestCaseCreate | TestCaseUpdate) {
    if (editing) {
      await testCasesApi.update(editing.id, data as TestCaseUpdate);
    } else {
      await testCasesApi.create(data as TestCaseCreate);
    }
    setShowForm(false);
    setEditing(null);
    await load();
  }

  async function handleDelete(tc: TestCaseRead) {
    if (!window.confirm(`"${tc.name}" 케이스를 삭제할까요?`)) return;
    try {
      await testCasesApi.remove(tc.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "삭제 실패");
    }
  }

  async function handleRun(tc: TestCaseRead) {
    setRunningId(tc.id);
    setError(null);
    try {
      // ASSUMED: POST /api/test-cases/{id}/run — backend-agent 구현 중 (api/testRuns.ts 참고)
      const run = await testRunsApi.trigger(tc.id);
      navigate(`/execution/${run.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "실행 트리거 실패");
    } finally {
      setRunningId(null);
    }
  }

  return (
    <div className="test-cases-page">
      <div className="page-header">
        <h2>시험 케이스 관리</h2>
        <button
          onClick={() => {
            setEditing(null);
            setShowForm(true);
          }}
        >
          + 새 케이스 등록
        </button>
      </div>

      <div className="filters">
        <select
          value={categoryFilter}
          onChange={(e) => {
            setOffset(0);
            setCategoryFilter(e.target.value as TestCaseCategory | "");
          }}
        >
          <option value="">전체 프로토콜</option>
          <option value="volte">VoLTE</option>
          <option value="mcptt">McPTT</option>
        </select>

        <select
          value={testTypeFilter}
          onChange={(e) => {
            setOffset(0);
            setTestTypeFilter(e.target.value as TestCaseType | "");
          }}
        >
          <option value="">전체 시험유형</option>
          <option value="basic_call">basic_call</option>
          <option value="performance">performance</option>
          <option value="abnormal">abnormal</option>
        </select>

        <input
          placeholder="이름 검색"
          value={nameFilter}
          onChange={(e) => {
            setOffset(0);
            setNameFilter(e.target.value);
          }}
        />
      </div>

      {error && <div className="page-error">{error}</div>}

      {showForm && (
        <div className="modal-backdrop">
          <div className="modal">
            <TestCaseForm
              initial={editing}
              onCancel={() => {
                setShowForm(false);
                setEditing(null);
              }}
              onSubmit={handleCreateOrUpdate}
            />
          </div>
        </div>
      )}

      {loading ? (
        <div>불러오는 중...</div>
      ) : (
        <table className="test-cases-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>이름</th>
              <th>프로토콜</th>
              <th>유형</th>
              <th>config_ref</th>
              <th>수정일시</th>
              <th>작업</th>
            </tr>
          </thead>
          <tbody>
            {items.map((tc) => (
              <tr key={tc.id}>
                <td className="mono">{tc.id}</td>
                <td>{tc.name}</td>
                <td>{tc.category === "volte" ? "VoLTE" : "McPTT"}</td>
                <td>{tc.test_type}</td>
                <td className="mono ellipsis" title={tc.config_ref}>
                  {tc.config_ref}
                </td>
                <td>{new Date(tc.updated_at).toLocaleString()}</td>
                <td className="actions">
                  <button
                    onClick={() => handleRun(tc)}
                    disabled={runningId === tc.id}
                    title="POST /api/test-cases/{id}/run (가정된 스펙)"
                  >
                    {runningId === tc.id ? "실행 중..." : "실행"}
                  </button>
                  <button
                    onClick={() => {
                      setEditing(tc);
                      setShowForm(true);
                    }}
                  >
                    수정
                  </button>
                  <button className="danger" onClick={() => handleDelete(tc)}>
                    삭제
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={7} className="empty-row">
                  등록된 시험 케이스가 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}

      <div className="pagination">
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          이전
        </button>
        <span>
          {offset + 1}-{Math.min(offset + PAGE_SIZE, total)} / {total}
        </span>
        <button disabled={offset + PAGE_SIZE >= total} onClick={() => setOffset(offset + PAGE_SIZE)}>
          다음
        </button>
      </div>
    </div>
  );
}
