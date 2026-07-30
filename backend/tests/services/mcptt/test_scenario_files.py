"""app.services.mcptt.scenario_files.list_mcptt_scenario_files 단위 테스트.

`app.services.volte.sample_files`와 동일한 패턴/테스트 구조를 따른다 — 다만
`.xml` 확장자만 필터링해서 돌려주는 점이 다르다(디렉토리에 jar 실행 파일
등 시나리오가 아닌 파일도 같이 있을 수 있어서, 2026-07-29 확인).
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.config import Settings
from app.services.mcptt.scenario_files import list_mcptt_scenario_files


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
        self.closed = False

    async def run_command(self, command: str) -> _FakeResult:
        self.commands.append(command)
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
