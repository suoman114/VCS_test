"""app.services.volte.sample_files.list_volte_sample_files 단위 테스트."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.config import Settings
from app.services.volte.sample_files import list_volte_sample_files


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
async def test_list_volte_sample_files_parses_and_sorts_ls_output() -> None:
    settings = Settings(vctp_sample_dir="/home/vcs/vctp/sample")
    connector = _FakeConnector(_FakeResult(exit_status=0, stdout="zzz.pcap\nimsVideo30sec.pcap\n\n"))

    files = await list_volte_sample_files(settings=settings, connector=connector)

    assert files == ["imsVideo30sec.pcap", "zzz.pcap"]
    assert connector.commands == ["\\ls -1 /home/vcs/vctp/sample"]
    # 주입된 connector는 이 함수가 만든 게 아니므로 닫지 않는다(호출자 책임).
    assert connector.closed is False


@pytest.mark.asyncio
async def test_list_volte_sample_files_raises_on_ls_failure() -> None:
    settings = Settings(vctp_sample_dir="/home/vcs/vctp/sample")
    connector = _FakeConnector(_FakeResult(exit_status=2, stdout="", stderr="No such file or directory"))

    with pytest.raises(RuntimeError, match="No such file or directory"):
        await list_volte_sample_files(settings=settings, connector=connector)


@pytest.mark.asyncio
async def test_list_volte_sample_files_strips_ansi_color_codes() -> None:
    """RHEL 계열 기본 .cshrc의 `alias ls 'ls --color=auto'` 등으로 색상 코드가
    섞여 들어와도(PTY 할당 시 흔함) 파일명만 깨끗하게 추출되어야 한다."""
    settings = Settings(vctp_sample_dir="/home/vcs/vctp/sample")
    colored_stdout = "\x1b[0mimsVideo30sec.pcap\x1b[0m\n\x1b[0mzzz.pcap\x1b[0m\n"
    connector = _FakeConnector(_FakeResult(exit_status=0, stdout=colored_stdout))

    files = await list_volte_sample_files(settings=settings, connector=connector)

    assert files == ["imsVideo30sec.pcap", "zzz.pcap"]
