"""Container diagnostics must not confuse application logs with the probe result."""

import json

import pytest

from scripts.module6_container_check import parse_container_readiness


def test_readiness_result_survives_logs_before_and_after_machine_output():
    expected = {
        "status": "not_ready",
        "checks": {"schema": "healthy", "models": "configuration_required"},
    }
    output = (
        'runtime role warning\n{"event":"another_json_log"}\n'
        + "DANGJIAN_CI_READINESS="
        + json.dumps(expected)
        + "\nshutdown log\n"
    )
    assert parse_container_readiness(output) == expected


@pytest.mark.parametrize(
    "output",
    [
        '{"checks":{"schema":"healthy"}}\n',
        'DANGJIAN_CI_READINESS={"checks":{}}\nDANGJIAN_CI_READINESS={"checks":{}}\n',
        'DANGJIAN_CI_READINESS={"status":"not_ready"}\n',
        "DANGJIAN_CI_READINESS=[]\n",
    ],
)
def test_missing_ambiguous_or_incomplete_machine_result_cannot_pass(output):
    with pytest.raises(ValueError):
        parse_container_readiness(output)
