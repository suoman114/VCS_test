"""app.services.mcptt.scenario_files.list_mcptt_scenario_files 단위 테스트.

`app.services.volte.sample_files`와 동일한 패턴/테스트 구조를 따른다 — 다만
`.xml` 확장자만 필터링해서 돌려주는 점이 다르다(디렉토리에 jar 실행 파일
등 시나리오가 아닌 파일도 같이 있을 수 있어서, 2026-07-29 확인).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

import app.services.mcptt.scenario_files as scenario_files_module
from app.core.config import Settings
from app.services.mcptt.scenario_files import list_mcptt_scenario_files


@pytest.fixture(autouse=True)
def _no_db_root_password_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """이 파일은 순수 단위 테스트라 DB(대시보드 오버라이드) 없이 돈다.

    `resolve_sipp_root_password()`는 원래 DB에서 오버라이드를 조회하지만,
    오버라이드가 없으면 `Settings.sipp_ssh_root_password`를 그대로 돌려주는
    것과 동일하다 — DB 접근 없이 그 동작만 흉내낸다.
    """

    def _fake(settings: Settings) -> str | None:
        return settings.sipp_ssh_root_password

    monkeypatch.setattr(scenario_files_module, "resolve_sipp_root_password", _fake)


@dataclass
class _FakeResult:
    exit_status: int
    stdout: str
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.exit_status == 0


class _FakeConnector:
    def __init__(self, result: _FakeResult) -> None:
        self._result = result
        self.commands: list[str] = []
        self.su_commands: list[tuple[str, str]] = []
        self.closed = False

    async def run_command(self, command: str) -> _FakeResult:
        self.commands.append(command)
        return self._result

    async def run_command_as_su(self, command: str, su_password: str) -> _FakeResult:
        self.su_commands.append((command, su_password))
        return self._result

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_list_mcptt_scenario_files_filters_xml_only_and_sorts() -> None:
    settings = Settings(mcptt_sim_dir="/root/mcptt_sim")
    connector = _FakeConnector(
        _FakeResult(
            exit_status=0,
            stdout="zzz_call.xml\nutgen-jar-with-dependencies.jar\nbasic_call.xml\nREADME.txt\n\n",
        )
    )

    files = await list_mcptt_scenario_files(settings=settings, connector=connector)

    assert files == ["basic_call.xml", "zzz_call.xml"]
    assert connector.commands == ["\\ls -1 /root/mcptt_sim"]
    assert connector.closed is False


@pytest.mark.asyncio
async def test_list_mcptt_scenario_files_raises_on_ls_failure() -> None:
    settings = Settings(mcptt_sim_dir="/root/mcptt_sim")
    connector = _FakeConnector(_FakeResult(exit_status=2, stdout="", stderr="No such file or directory"))

    with pytest.raises(RuntimeError, match="No such file or directory"):
        await list_mcptt_scenario_files(settings=settings, connector=connector)


@pytest.mark.asyncio
async def test_list_mcptt_scenario_files_strips_ansi_color_codes() -> None:
    settings = Settings(mcptt_sim_dir="/root/mcptt_sim")
    colored_stdout = "\x1b[0mbasic_call.xml\x1b[0m\n\x1b[0mzzz_call.xml\x1b[0m\n"
    connector = _FakeConnector(_FakeResult(exit_status=0, stdout=colored_stdout))

    files = await list_mcptt_scenario_files(settings=settings, connector=connector)

    assert files == ["basic_call.xml", "zzz_call.xml"]


@pytest.mark.asyncio
async def test_list_mcptt_scenario_files_uses_su_root_when_password_configured() -> None:
    """`mcptt_sim_dir` 기본값이 `/root` 아래라, root 직접 로그인이 막힌 환경에서는
    로그인 계정 권한만으로 `ls`하면 permission denied로 실패한다(2026-07-30) —
    `sipp_ssh_root_password`가 설정돼 있으면 실제 시뮬레이터 실행과 동일하게
    su root로 조회해야 한다."""
    settings = Settings(mcptt_sim_dir="/root/mcptt_sim", sipp_ssh_root_password="r00t-pw")
    connector = _FakeConnector(_FakeResult(exit_status=0, stdout="basic_call.xml\n"))

    files = await list_mcptt_scenario_files(settings=settings, connector=connector)

    assert files == ["basic_call.xml"]
    assert connector.su_commands == [("\\ls -1 /root/mcptt_sim", "r00t-pw")]
    assert connector.commands == []  # 일반 run_command()로는 아무것도 안 돌아야 한다
