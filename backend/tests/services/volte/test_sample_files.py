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
    assert connector.commands == ["ls -1 /home/vcs/vctp/sample"]
    # 주입된 connector는 이 함수가 만든 게 아니므로 닫지 않는다(호출자 책임).
    assert connector.closed is False


@pytest.mark.asyncio
async def test_list_volte_sample_files_raises_on_ls_failure() -> None:
    settings = Settings(vctp_sample_dir="/home/vcs/vctp/sample")
    connector = _FakeConnector(_FakeResult(exit_status=2, stdout="", stderr="No such file or directory"))

    with pytest.raises(RuntimeError, match="No such file or directory"):
        await list_volte_sample_files(settings=settings, connector=connector)
