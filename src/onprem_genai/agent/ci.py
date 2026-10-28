"""CI verification of the agent's branch through the Jenkins MCP Server plugin (``mcp-server``).

Tools used (plugin source, ``DefaultMcpServer`` / ``TestResultExtension`` / ``BuildLogsExtension``):
``triggerBuild(jobFullName, parameters)`` → queue item; ``getQueueItem(id)`` → ``executable.number`` once the
build starts; ``getBuild(jobFullName, buildNumber)`` → ``building`` / ``result``;
``getTestResults(jobFullName, buildNumber)`` → JUnit summary; ``getBuildLog(jobFullName, buildNumber)`` →
last 100 log lines. The plugin authenticates with HTTP Basic (user + API token or password).
"""

from __future__ import annotations

import asyncio
import base64
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from onprem_genai.agent.knowledge import McpToolClient

DEFAULT_JOB = "fprime-unit-tests"
_DONE_RESULTS = {"SUCCESS", "UNSTABLE", "FAILURE", "ABORTED", "NOT_BUILT"}


@dataclass
class CiResult:
    job: str
    branch: str
    modules: list[str]
    build_number: int | None = None
    result: str | None = None  # SUCCESS / UNSTABLE / FAILURE / ABORTED / TIMEOUT / ERROR
    url: str | None = None
    seconds: float = 0.0
    tests: dict[str, Any] = field(default_factory=dict)
    log_tail: str = ""
    error: str = ""

    @property
    def passed(self) -> bool:
        return self.result == "SUCCESS"

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "passed": self.passed}


def basic_auth(user: str, secret: str) -> dict[str, str]:
    token = base64.b64encode(f"{user}:{secret}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def _leaf(exc: BaseException) -> BaseException:
    """The original error inside the exception groups that anyio task groups wrap it in."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return exc


def _find(obj: Any, key: str) -> Any:
    """First value of ``key`` in a nested JSON object (the plugin's tree pruning may vary the nesting)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            if (found := _find(v, key)) is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            if (found := _find(v, key)) is not None:
                return found
    return None


class JenkinsCi:
    """Runs the F´ unit-test pipeline for a branch and waits for its verdict."""

    def __init__(
        self,
        target: Any,  # MCP endpoint URL (…/mcp-server/mcp) or an MCP server / transport (tests)
        user: str | None = None,
        secret: str | None = None,
        job: str = DEFAULT_JOB,
        poll_s: float = 5.0,
        timeout_s: float = 3600.0,
    ) -> None:
        self.target = target
        self.headers = basic_auth(user, secret) if user and secret else None
        self.job, self.poll_s, self.timeout_s = job, poll_s, timeout_s

    async def run(self, branch: str, modules: list[str]) -> CiResult:
        res = CiResult(self.job, branch, modules)
        t0 = time.monotonic()
        try:
            async with McpToolClient(self.target, self.headers) as mcp:
                await self._run(mcp, res, t0)
        except Exception as exc:  # CI trouble is reported; it never loses the agent's results
            leaf = _leaf(exc)
            res.result = "TIMEOUT" if isinstance(leaf, TimeoutError) else (res.result or "ERROR")
            res.error = f"{type(leaf).__name__}: {leaf}"[:1000]
        res.seconds = round(time.monotonic() - t0, 1)
        return res

    async def _run(self, mcp: McpToolClient, res: CiResult, t0: float) -> None:
        job = await mcp.call("getJob", jobFullName=self.job)
        if not job:
            raise RuntimeError(f"Jenkins job {self.job!r} not found or not visible to this user")
        last_before = _find(job.get("lastBuild") or {}, "number") or 0
        params = {"BRANCH": res.branch, "MODULES": " ".join(res.modules)}
        queued = await mcp.call("triggerBuild", jobFullName=self.job, parameters=params)
        queue_id = _find(queued, "id")
        while res.build_number is None:
            self._check_timeout(t0)
            if queue_id is not None:
                item = await mcp.call("getQueueItem", id=int(queue_id))
                if item and _find(item, "cancelled"):
                    raise RuntimeError("build was cancelled while queued")
                number = _find(_find(item, "executable") or {}, "number") if item else None
                if number:
                    res.build_number = int(number)
                    break
            # queue items expire from the cache: fall back to the job's newest build
            last = await mcp.call("getBuild", jobFullName=self.job)
            number = _find(last or {}, "number")
            if number and int(number) > int(last_before):
                res.build_number = int(number)
                break
            await asyncio.sleep(self.poll_s)
        while True:
            self._check_timeout(t0)
            build = await mcp.call("getBuild", jobFullName=self.job, buildNumber=res.build_number) or {}
            res.url = _find(build, "url") or res.url
            result = _find(build, "result")
            if not _find(build, "building") and result in _DONE_RESULTS:
                res.result = str(result)
                break
            await asyncio.sleep(self.poll_s)
        tests = await mcp.call("getTestResults", jobFullName=self.job, buildNumber=res.build_number)
        if isinstance(tests, dict):
            res.tests = {
                k: tests[k]
                for k in ("totalCount", "failCount", "skipCount", "passCount", "failedTests")
                if k in tests
            }
        if not res.passed:
            log = await mcp.call("getBuildLog", jobFullName=self.job, buildNumber=res.build_number)
            lines = _find(log, "lines") if isinstance(log, dict) else log
            res.log_tail = "\n".join(lines[-60:]) if isinstance(lines, list) else str(lines or "")[-4000:]

    def _check_timeout(self, t0: float) -> None:
        if time.monotonic() - t0 > self.timeout_s:
            raise TimeoutError(f"no CI verdict after {self.timeout_s:.0f}s")
