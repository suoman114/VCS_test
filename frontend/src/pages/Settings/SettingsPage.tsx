import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";
import { settingsApi } from "../../api/settings";
import type { SippExecMode, VcsSettings, VcsSettingsUpdate } from "../../api/types";
import "./SettingsPage.css";

type TestState = { status: "idle" | "testing" | "ok" | "error"; message?: string };

const IDLE: TestState = { status: "idle" };

export function SettingsPage() {
  const [settings, setSettings] = useState<VcsSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // VCS 필드
  const [vcsHost, setVcsHost] = useState("");
  const [vcsPort, setVcsPort] = useState(22);
  const [vcsUsername, setVcsUsername] = useState("");
  const [vcsPassword, setVcsPassword] = useState("");
  const [vcsClearPassword, setVcsClearPassword] = useState(false);
  const [vcsPrivateKeyPath, setVcsPrivateKeyPath] = useState("");
  const [vcsKnownHosts, setVcsKnownHosts] = useState("");

  // SIPp 필드
  const [sippExecMode, setSippExecMode] = useState<SippExecMode>("local");
  const [sippHost, setSippHost] = useState("");
  const [sippPort, setSippPort] = useState(22);
  const [sippUsername, setSippUsername] = useState("");
  const [sippPassword, setSippPassword] = useState("");
  const [sippClearPassword, setSippClearPassword] = useState(false);
  const [sippPrivateKeyPath, setSippPrivateKeyPath] = useState("");
  const [sippRootPassword, setSippRootPassword] = useState("");
  const [sippClearRootPassword, setSippClearRootPassword] = useState(false);

  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);

  const [vcsTest, setVcsTest] = useState<TestState>(IDLE);
  const [sippTest, setSippTest] = useState<TestState>(IDLE);

  function applySettings(s: VcsSettings) {
    setSettings(s);
    setVcsHost(s.vcs_ssh_host ?? "");
    setVcsPort(s.vcs_ssh_port);
    setVcsUsername(s.vcs_ssh_username ?? "");
    setVcsPrivateKeyPath(s.vcs_ssh_private_key_path ?? "");
    setVcsKnownHosts(s.vcs_ssh_known_hosts ?? "");
    setSippExecMode(s.sipp_exec_mode);
    setSippHost(s.sipp_ssh_host ?? "");
    setSippPort(s.sipp_ssh_port);
    setSippUsername(s.sipp_ssh_username ?? "");
    setSippPrivateKeyPath(s.sipp_ssh_private_key_path ?? "");
    setVcsPassword("");
    setVcsClearPassword(false);
    setSippPassword("");
    setSippClearPassword(false);
    setSippRootPassword("");
    setSippClearRootPassword(false);
  }

  useEffect(() => {
    let cancelled = false;
    settingsApi
      .getVcs()
      .then((s) => {
        if (!cancelled) applySettings(s);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : "설정 조회 실패");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    setSavedAt(null);
    try {
      const body: VcsSettingsUpdate = {
        vcs_ssh_host: vcsHost,
        vcs_ssh_port: vcsPort,
        vcs_ssh_username: vcsUsername,
        vcs_ssh_private_key_path: vcsPrivateKeyPath,
        vcs_ssh_known_hosts: vcsKnownHosts,
        sipp_exec_mode: sippExecMode,
        sipp_ssh_host: sippHost,
        sipp_ssh_port: sippPort,
        sipp_ssh_username: sippUsername,
        sipp_ssh_private_key_path: sippPrivateKeyPath,
      };
      if (vcsClearPassword) {
        body.vcs_ssh_password = "";
      } else if (vcsPassword) {
        body.vcs_ssh_password = vcsPassword;
      }
      if (sippClearPassword) {
        body.sipp_ssh_password = "";
      } else if (sippPassword) {
        body.sipp_ssh_password = sippPassword;
      }
      if (sippClearRootPassword) {
        body.sipp_ssh_root_password = "";
      } else if (sippRootPassword) {
        body.sipp_ssh_root_password = sippRootPassword;
      }

      const updated = await settingsApi.updateVcs(body);
      applySettings(updated);
      setSavedAt(new Date());
      setVcsTest(IDLE);
      setSippTest(IDLE);
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "저장 실패");
    } finally {
      setSaving(false);
    }
  }

  async function handleTestVcs() {
    setVcsTest({ status: "testing" });
    try {
      const result = await settingsApi.testVcsConnection();
      setVcsTest({ status: result.ok ? "ok" : "error", message: result.message });
    } catch (err) {
      setVcsTest({ status: "error", message: err instanceof ApiError ? err.message : "연결 테스트 실패" });
    }
  }

  async function handleTestSipp() {
    setSippTest({ status: "testing" });
    try {
      const result = await settingsApi.testSippConnection();
      setSippTest({ status: result.ok ? "ok" : "error", message: result.message });
    } catch (err) {
      setSippTest({ status: "error", message: err instanceof ApiError ? err.message : "연결 테스트 실패" });
    }
  }

  if (loading) {
    return (
      <div className="settings-page">
        <h2>설정</h2>
        <p>불러오는 중...</p>
      </div>
    );
  }

  if (loadError || !settings) {
    return (
      <div className="settings-page">
        <h2>설정</h2>
        <div className="page-error">{loadError ?? "설정을 불러오지 못했습니다"}</div>
      </div>
    );
  }

  return (
    <div className="settings-page">
      <h2>설정</h2>
      <p className="settings-intro">
        VCS/SIPp 접속 정보. 비워두면 <code>.env</code> 기본값을 그대로 쓰고, 값을 입력해서 저장하면 여기서
        설정한 값이 우선 적용됩니다.
      </p>

      <form className="settings-form" onSubmit={handleSave}>
        <section className="settings-section">
          <div className="settings-section-header">
            <h3>VCS 접속 정보</h3>
            <button type="button" onClick={handleTestVcs} disabled={vcsTest.status === "testing"}>
              {vcsTest.status === "testing" ? "테스트 중..." : "연결 테스트"}
            </button>
          </div>
          {vcsTest.status !== "idle" && vcsTest.status !== "testing" && (
            <div className={vcsTest.status === "ok" ? "test-result test-result-ok" : "test-result test-result-error"}>
              {vcsTest.message}
            </div>
          )}

          <div className="form-row">
            <label>
              호스트
              <input value={vcsHost} onChange={(e) => setVcsHost(e.target.value)} placeholder="예: 192.168.7.64" />
            </label>
            <label className="form-field-narrow">
              포트
              <input
                type="number"
                value={vcsPort}
                onChange={(e) => setVcsPort(Number(e.target.value) || 22)}
                min={1}
                max={65535}
              />
            </label>
          </div>

          <div className="form-row">
            <label>
              사용자명
              <input value={vcsUsername} onChange={(e) => setVcsUsername(e.target.value)} placeholder="예: vcs" />
            </label>
            <label>
              비밀번호
              <input
                type="password"
                value={vcsPassword}
                onChange={(e) => setVcsPassword(e.target.value)}
                disabled={vcsClearPassword}
                placeholder={settings.vcs_ssh_password_set ? "변경하려면 입력 (설정됨)" : "설정 안 됨"}
              />
              <span className="form-checkbox-hint">
                <input
                  type="checkbox"
                  checked={vcsClearPassword}
                  onChange={(e) => setVcsClearPassword(e.target.checked)}
                />
                비밀번호 삭제(.env 값으로 되돌리기)
              </span>
            </label>
          </div>

          <div className="form-row">
            <label>
              SSH 개인키 경로(선택)
              <input
                value={vcsPrivateKeyPath}
                onChange={(e) => setVcsPrivateKeyPath(e.target.value)}
                placeholder="비밀번호 인증이면 비워둠"
              />
            </label>
            <label>
              known_hosts 경로(선택)
              <input
                value={vcsKnownHosts}
                onChange={(e) => setVcsKnownHosts(e.target.value)}
                placeholder="비워두면 검증 안 함"
              />
            </label>
          </div>
        </section>

        <section className="settings-section">
          <div className="settings-section-header">
            <h3>SIPp 실행 설정</h3>
            <button type="button" onClick={handleTestSipp} disabled={sippTest.status === "testing"}>
              {sippTest.status === "testing" ? "테스트 중..." : "연결 테스트"}
            </button>
          </div>
          {sippTest.status !== "idle" && sippTest.status !== "testing" && (
            <div
              className={sippTest.status === "ok" ? "test-result test-result-ok" : "test-result test-result-error"}
            >
              {sippTest.message}
            </div>
          )}

          <label className="form-field-narrow">
            실행 위치
            <select value={sippExecMode} onChange={(e) => setSippExecMode(e.target.value as SippExecMode)}>
              <option value="local">local (자동화 서버에서 직접 실행)</option>
              <option value="ssh">ssh (별도 SIPp 전용 호스트)</option>
            </select>
          </label>

          {sippExecMode === "ssh" && (
            <>
              <div className="form-row">
                <label>
                  호스트
                  <input value={sippHost} onChange={(e) => setSippHost(e.target.value)} placeholder="SIPp 서버 IP" />
                </label>
                <label className="form-field-narrow">
                  포트
                  <input
                    type="number"
                    value={sippPort}
                    onChange={(e) => setSippPort(Number(e.target.value) || 22)}
                    min={1}
                    max={65535}
                  />
                </label>
              </div>
              <div className="form-row">
                <label>
                  사용자명
                  <input value={sippUsername} onChange={(e) => setSippUsername(e.target.value)} />
                </label>
                <label>
                  비밀번호
                  <input
                    type="password"
                    value={sippPassword}
                    onChange={(e) => setSippPassword(e.target.value)}
                    disabled={sippClearPassword}
                    placeholder={settings.sipp_ssh_password_set ? "변경하려면 입력 (설정됨)" : "설정 안 됨"}
                  />
                  <span className="form-checkbox-hint">
                    <input
                      type="checkbox"
                      checked={sippClearPassword}
                      onChange={(e) => setSippClearPassword(e.target.checked)}
                    />
                    비밀번호 삭제(.env 값으로 되돌리기)
                  </span>
                </label>
              </div>
              <label>
                SSH 개인키 경로(선택)
                <input value={sippPrivateKeyPath} onChange={(e) => setSippPrivateKeyPath(e.target.value)} />
              </label>

              <div className="settings-subsection">
                <div className="settings-subsection-title">
                  root 직접 SSH 로그인이 막혀있는 서버(sysadm 등으로 접속 후 su로 전환)
                </div>
                <label>
                  su root 비밀번호(선택)
                  <input
                    type="password"
                    value={sippRootPassword}
                    onChange={(e) => setSippRootPassword(e.target.value)}
                    disabled={sippClearRootPassword}
                    placeholder={
                      settings.sipp_ssh_root_password_set ? "변경하려면 입력 (설정됨)" : "비워두면 su 없이 직접 실행"
                    }
                  />
                  <span className="form-checkbox-hint">
                    <input
                      type="checkbox"
                      checked={sippClearRootPassword}
                      onChange={(e) => setSippClearRootPassword(e.target.checked)}
                    />
                    삭제(.env 값으로 되돌리기)
                  </span>
                </label>
                <div className="form-hint">
                  설정하면 위 사용자명 계정으로 접속한 뒤 <code>su - root</code>로 전환해서 SIPp 실행 관련
                  명령을 root 권한으로 실행합니다(예: <code>/root/SIPP/sipp</code> 실행 파일 접근용).
                </div>
              </div>
            </>
          )}
        </section>

        {saveError && <div className="form-error">{saveError}</div>}

        <div className="form-actions">
          {savedAt && <span className="form-hint">{savedAt.toLocaleTimeString()}에 저장됨</span>}
          <button type="submit" disabled={saving}>
            {saving ? "저장 중..." : "저장"}
          </button>
        </div>
      </form>
    </div>
  );
}
