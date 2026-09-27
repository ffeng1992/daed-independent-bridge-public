"""Generic dnsdist console adapter extracted from the existing local sync tool."""
from __future__ import annotations
import subprocess
from dataclasses import dataclass
from collections.abc import Callable
UP="UP"
DOWN="DOWN"
class SyncError(RuntimeError):pass

@dataclass(frozen=True)
class Backend:
    index: int
    name: str
    address: str
    state: str



Runner = Callable[[list[str], str | None], subprocess.CompletedProcess[str]]


def default_runner(argv: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603
        argv,
        input=input_text,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )



def parse_servers(output: str) -> dict[str, Backend]:
    servers: dict[str, Backend] = {}
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4 or not fields[0].isdigit() or fields[3] not in {UP, DOWN}:
            continue
        backend = Backend(int(fields[0]), fields[1], fields[2], fields[3])
        if backend.name in servers:
            raise SyncError(f"duplicate dnsdist backend name: {backend.name}")
        servers[backend.name] = backend
    return servers


class DnsdistControl:
    def __init__(self, command: tuple[str, ...], runner: Runner = default_runner):
        self.command = command
        self.runner = runner

    def _run(self, script: str) -> str:
        result = self.runner([*self.command, "-e", script], None)
        if result.returncode != 0:
            raise SyncError("dnsdist control failed")
        return result.stdout

    def servers(self) -> dict[str, Backend]:
        return parse_servers(self._run("showServers()"))

    def set_state(self, backend: Backend, state: str) -> None:
        if state not in {UP, DOWN} or type(backend.index) is not int or backend.index < 0:
            raise SyncError("invalid backend action")
        method = "setUp" if state == UP else "setDown"
        self._run(f"getServer({backend.index}):{method}()")


