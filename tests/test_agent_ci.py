"""CI client against a fake of the Jenkins MCP Server plugin (same tool names, parameters and JSON envelope).

The real plugin is exercised by the ``jenkins`` integration test in CI (docker compose profile ``ci``).
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
from typing import Any

import pytest
from mcp.server.mcpserver import MCPServer

from onprem_genai.agent.ci import JenkinsCi, basic_auth
from onprem_genai.agent.knowledge import decode_result, mcp_target
from onprem_genai.agent.runner import review_sheet, verify_with_ci

JOB = "fprime-unit-tests"


def envelope(result: Any) -> str:
    """What the plugin returns as text content (``ToolResponse``)."""
    if result is None:
        return json.dumps({"status": "COMPLETED", "message": "Search completed, but no results were found."})
    return json.dumps({"status": "COMPLETED", "message": "Data retrieved successfully.", "result": result})


def fake_jenkins(
    outcome: str = "SUCCESS", queue_polls: int = 2, build_polls: int = 2
) -> tuple[MCPServer, dict]:
    state: dict[str, Any] = {"triggered": [], "queue_calls": 0, "build_calls": 0}
    server = MCPServer(name="jenkins")

    @server.tool()
    def getJob(jobFullName: str) -> str:  # noqa: N802, N803  (plugin names)
        return envelope(
            {"name": JOB, "fullName": jobFullName, "lastBuild": {"number": 11}}
            if jobFullName == JOB
            else None
        )

    @server.tool()
    def triggerBuild(jobFullName: str, parameters: dict[str, Any] | None = None) -> str:  # noqa: N802, N803
        state["triggered"].append((jobFullName, parameters))
        return envelope({"_class": "hudson.model.Queue$WaitingItem", "id": 7, "why": "In the quiet period"})

    @server.tool()
    def getQueueItem(id: int) -> str:  # noqa: N802
        state["queue_calls"] += 1
        if state["queue_calls"] < queue_polls:
            return envelope({"id": id, "why": "Waiting for next available executor"})
        return envelope(
            {
                "_class": "hudson.model.Queue$LeftItem",
                "id": id,
                "cancelled": False,
                "executable": {"number": 12, "url": "http://jenkins/job/fprime-unit-tests/12/"},
            }
        )

    @server.tool()
    def getBuild(jobFullName: str, buildNumber: int | None = None) -> str:  # noqa: N802, N803
        state["build_calls"] += 1
        if buildNumber is None:
            return envelope({"number": 11, "result": "SUCCESS", "building": False})
        building = state["build_calls"] < build_polls
        return envelope(
            {
                "number": buildNumber,
                "building": building,
                "result": None if building else outcome,
                "url": f"http://jenkins/job/{jobFullName}/{buildNumber}/",
            }
        )

    @server.tool()
    def getTestResults(jobFullName: str, buildNumber: int | None = None) -> str:  # noqa: N802, N803
        failed = outcome != "SUCCESS"
        # nested like the real plugin's answer, which wraps the counts in the build's test-result action
        return envelope(
            {
                "buildNumber": buildNumber,
                "TestResultAction": {
                    "totalCount": 12,
                    "failCount": int(failed),
                    "skipCount": 0,
                    "passCount": 12 - int(failed),
                },
                "failedTests": [{"name": "Requirement.X"}] if failed else [],
            }
        )

    @server.tool()
    def getBuildLog(jobFullName: str, buildNumber: int | None = None) -> str:  # noqa: N802, N803
        return envelope(
            {"lines": ["[ RUN      ] Requirement.X", "[  FAILED  ] Requirement.X"], "hasMoreContent": False}
        )

    return server, state


def test_decode_result_variants() -> None:
    assert decode_result(None, [envelope({"id": 7})]) == {"id": 7}
    assert decode_result(None, [envelope(None)]) is None
    assert decode_result({"result": envelope([1, 2])}, []) == [1, 2]
    assert decode_result({"result": [{"a": 1}]}, []) == [{"a": 1}]  # MCP SDK list convention
    assert decode_result({"req_id": "X", "status": "ok"}, []) == {"req_id": "X", "status": "ok"}
    assert decode_result(None, ["plain text"]) == "plain text"


def test_basic_auth_header_and_transport() -> None:
    expected = base64.b64encode(b"oge-agent:not-a-real-token").decode()
    assert basic_auth("oge-agent", "not-a-real-token") == {"Authorization": f"Basic {expected}"}
    assert mcp_target("http://x/mcp") == "http://x/mcp"
    assert not isinstance(mcp_target("http://x/mcp", {"Authorization": "Basic a"}), str)


def test_ci_success_path() -> None:
    server, state = fake_jenkins()
    ci = JenkinsCi(server, job=JOB, poll_s=0.01)
    res = asyncio.run(ci.run("oge-agent/run-1", ["Svc/ComStub", "Svc/PrmDb"]))
    assert res.passed, res.error
    assert res.build_number == 12
    assert res.url == "http://jenkins/job/fprime-unit-tests/12/"
    assert res.tests["passCount"] == 12
    assert state["triggered"] == [(JOB, {"BRANCH": "oge-agent/run-1", "MODULES": "Svc/ComStub Svc/PrmDb"})]
    assert res.log_tail == ""


def test_ci_failure_keeps_log_and_failed_tests() -> None:
    server, _ = fake_jenkins(outcome="UNSTABLE")
    res = asyncio.run(JenkinsCi(server, job=JOB, poll_s=0.01).run("b", ["Svc/ComStub"]))
    assert not res.passed
    assert res.result == "UNSTABLE"
    assert res.tests["failedTests"] == [{"name": "Requirement.X"}]
    assert "[  FAILED  ] Requirement.X" in res.log_tail


def test_ci_unknown_job_and_timeout_are_reported() -> None:
    server, _ = fake_jenkins()
    res = asyncio.run(JenkinsCi(server, job="nope", poll_s=0.01).run("b", ["Svc/ComStub"]))
    assert res.result == "ERROR"
    assert "not found" in res.error
    slow, _ = fake_jenkins(build_polls=10**6)
    res = asyncio.run(JenkinsCi(slow, job=JOB, poll_s=0.01, timeout_s=0.3).run("b", ["Svc/ComStub"]))
    assert res.result == "TIMEOUT"


def test_verify_with_ci_runs_once_for_touched_modules(tmp_path: Path) -> None:
    server, state = fake_jenkins()
    records = [
        {
            "req_id": "A-1",
            "module": "Svc/ComStub",
            "status": "passed",
            "commit": "abc",
            "attempts": 1,
            "metrics": {},
            "history": [],
        },
        {
            "req_id": "A-2",
            "module": "Svc/ComStub",
            "status": "passed",
            "commit": "def",
            "attempts": 1,
            "metrics": {},
            "history": [],
        },
        {
            "req_id": "B-1",
            "module": "Svc/PrmDb",
            "status": "failed",
            "commit": None,
            "attempts": 3,
            "metrics": {},
            "history": [],
        },
    ]
    out = tmp_path / "run.jsonl"
    ci = asyncio.run(verify_with_ci(JenkinsCi(server, job=JOB, poll_s=0.01), records, "br", out))
    assert ci is not None
    assert ci["passed"]
    assert state["triggered"][0][1]["MODULES"] == "Svc/ComStub"
    assert json.loads(out.with_suffix(".ci.json").read_text())["build_number"] == 12
    assert "→ **SUCCESS** (12/12 tests passed)" in review_sheet(records, "m", ci)
    assert asyncio.run(verify_with_ci(JenkinsCi(server, job=JOB), records[2:], "br", out)) is None


@pytest.mark.jenkins
def test_real_jenkins_pipeline_runs_fprime_unit_tests() -> None:
    """Against the compose ``ci`` profile: Jenkins LTS + mcp-server plugin + the F´ pipeline (see deploy/)."""
    url = os.environ.get("OGE_JENKINS_MCP_URL")
    if not url:
        pytest.skip("set OGE_JENKINS_MCP_URL, OGE_JENKINS_USER and OGE_JENKINS_TOKEN")
    branch = os.environ.get("OGE_JENKINS_BRANCH", "HEAD")
    ci = JenkinsCi(url, os.environ.get("OGE_JENKINS_USER"), os.environ.get("OGE_JENKINS_TOKEN"), poll_s=10)
    res = asyncio.run(ci.run(branch, ["Svc/ComStub"]))
    assert res.passed, res.as_dict()
    assert res.tests.get("totalCount", 0) >= 10
