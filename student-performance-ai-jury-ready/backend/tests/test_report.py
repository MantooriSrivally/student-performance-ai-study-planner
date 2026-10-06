"""
tests/test_report.py — Prove the JSON contract holds unconditionally.

Two claims under test:
  1. PerformanceAnalyzer.generate always returns a schema-valid report, however
     badly the LLM path misbehaves.
  2. main.py always writes exactly one parseable JSON object to stdout.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.analyzer import GEMINI_SCHEMA_KEYWORDS, PerformanceAnalyzer, to_gemini_schema
from app.core.pipeline import StudentDataPipeline
from app.core.report_engine import LocalReportEngine, ReportInputs
from app.models.report import StudentPerformanceReport


@pytest.fixture(scope="module")
def unified():
    return StudentDataPipeline(logging=False).run()


@pytest.fixture(scope="module")
def inputs(unified) -> ReportInputs:
    return ReportInputs(
        student=unified.student,
        interview=unified.interview,
        assignment=unified.assignment,
        assessment=unified.assessment,
        attendance=unified.attendance,
        metrics=unified.metrics,
    )


def _assert_strict_json(report) -> dict:
    """Round-trip through text and re-validate, so nothing is taken on trust."""
    data = json.loads(report.model_dump_json())
    assert isinstance(data, dict)
    StudentPerformanceReport.model_validate(data)
    return data


def _generate(analyzer: PerformanceAnalyzer, inputs: ReportInputs):
    return analyzer.generate(
        student=inputs.student,
        interview=inputs.interview,
        assignment=inputs.assignment,
        assessment=inputs.assessment,
        attendance=inputs.attendance,
        metrics=inputs.metrics,
    )


# ── Local engine ──────────────────────────────────────────────────────────────

def test_local_engine_emits_valid_report(inputs):
    data = _assert_strict_json(LocalReportEngine().build(inputs))
    assert data["student_id"] == inputs.student.student_id
    assert data["meta"]["engine"] == "local"
    assert data["meta"]["strict_json"] is True


def test_local_engine_is_deterministic(inputs):
    engine = LocalReportEngine()
    skip = {"generated_at", "report_id"}
    assert engine.build(inputs).model_dump(exclude=skip) == (
        engine.build(inputs).model_dump(exclude=skip)
    )


def test_report_reflects_source_metrics(inputs):
    report = LocalReportEngine().build(inputs)
    assert report.overall_performance.score == pytest.approx(
        inputs.metrics.overall_performance_score, abs=0.01
    )
    assert report.attendance_snapshot.percentage == pytest.approx(
        inputs.attendance.attendance_percentage, abs=0.01
    )
    assert len(report.interview_deep_dive.questions) == len(inputs.interview.questions)


def test_schema_floors_are_met(inputs):
    report = LocalReportEngine().build(inputs)
    assert len(report.dimension_scores) >= 4
    assert len(report.strengths) >= 2
    assert len(report.growth_areas) >= 1
    assert 3 <= len(report.action_plan) <= 6
    assert len({item.timeframe for item in report.action_plan}) == len(report.action_plan)
    assert report.performance_tier.tier in (1, 2, 3)
    assert report.performance_tier.label.startswith("Tier")
    assert len(report.lagging_areas) >= 1
    assert len(report.weakness_analysis.items) >= 1
    assert len(report.study_plan.phases) >= 3
    assert report.study_plan.weekly_hours >= 1
    assert report.board_decision.decision in (
        "CLEAR_FOR_DRIVES", "HOLD_ONE_CYCLE", "INTENSIVE_SUPPORT"
    )
    assert len(report.scorecard) >= 5
    assert "40%" in report.methodology_note or "40" in report.methodology_note
    assert len(report.skill_graph.nodes) >= 4
    assert len(report.skill_graph.edges) >= 3
    assert report.skill_graph.bottleneck_skill
    assert report.skill_graph.downstream_count >= 0
    assert report.early_warning.severity in ("critical", "elevated", "watch", "clear")
    assert report.early_warning.predicted_issue
    assert report.early_warning.recommended_intervention
    assert report.what_if_scenario.current_readiness >= 0
    assert report.what_if_scenario.simulated_readiness >= 0
    assert len(report.what_if_scenario.levers) >= 4
    assert len(report.what_if_scenario.largest_drivers) >= 1


def test_tier_and_study_plan_are_coherent(inputs):
    report = LocalReportEngine().build(inputs)
    assert report.headline.startswith(inputs.student.name) or inputs.student.name in report.headline
    assert f"Tier {report.performance_tier.tier}" in report.performance_tier.label or (
        report.performance_tier.label == f"Tier {report.performance_tier.tier}"
    )
    assert report.weakness_analysis.primary_weakness
    assert all(area.gap >= 0 for area in report.lagging_areas)
    for phase in report.study_plan.phases:
        assert len(phase.practice_tasks) >= 2
        assert len(phase.real_world_resources) >= 2
    assert report.board_decision.priority_fix
    assert report.board_decision.next_review_date
    assert all(row.result in ("Pass", "Watch", "Fail") for row in report.scorecard)


# ── Default path costs nothing ────────────────────────────────────────────────

def test_default_engine_is_local_and_makes_no_call(inputs, monkeypatch):
    monkeypatch.delenv("REPORT_ENGINE", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "sk-should-never-be-used")

    def explode(*args, **kwargs):
        raise AssertionError("the local engine must never touch the network")

    monkeypatch.setattr(PerformanceAnalyzer, "_generate_with_gemini", explode)

    report = _generate(PerformanceAnalyzer(logging=False), inputs)
    assert _assert_strict_json(report)["meta"]["engine"] == "local"


def test_unknown_engine_degrades_to_local(inputs, monkeypatch):
    monkeypatch.setenv("REPORT_ENGINE", "definitely-not-an-engine")
    assert _generate(PerformanceAnalyzer(logging=False), inputs).meta.engine == "local"


def test_gemini_without_key_degrades_to_local(inputs, monkeypatch):
    monkeypatch.setenv("REPORT_ENGINE", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "your_api_key_here")
    analyzer = PerformanceAnalyzer(logging=False, use_cache=False)
    assert _generate(analyzer, inputs).meta.engine == "local"


# ── Every LLM failure mode still yields valid JSON ────────────────────────────

@pytest.mark.parametrize(
    "label,reply",
    [
        ("prose only",     "Sure! Here is the report you asked for."),
        ("empty",          ""),
        ("whitespace",     "   \n  "),
        ("markdown fence", '```json\n{"broken": true}\n```'),
        ("truncated json", '{"report_id": "SPR-1", "student_id":'),
        ("json array",     '[{"report_id": "SPR-1"}]'),
        ("wrong shape",    '{"totally": "different", "keys": 1}'),
        ("extra keys",     '{"report_id": "x", "unexpected_key": "boom"}'),
        ("null literal",   "null"),
    ],
)
def test_malformed_llm_reply_still_returns_valid_json(inputs, monkeypatch, label, reply):
    monkeypatch.setenv("REPORT_ENGINE", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        PerformanceAnalyzer,
        "_generate_with_gemini",
        lambda self, record, data: _parse_only(self, reply, data),
    )

    analyzer = PerformanceAnalyzer(logging=False, use_cache=False)
    data = _assert_strict_json(_generate(analyzer, inputs))
    assert data["meta"]["engine"] == "local", f"{label} should have degraded to local"


def _parse_only(analyzer, reply, data):
    """Run only the analyzer's parse/validate steps against a canned reply."""
    from pydantic import ValidationError

    from app.core.json_util import extract_json_object

    try:
        parsed = extract_json_object(reply)
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    try:
        return analyzer._pin_identity(StudentPerformanceReport.model_validate(parsed), data)
    except ValidationError:
        return None


def test_transport_failure_degrades_to_local(inputs, monkeypatch):
    monkeypatch.setenv("REPORT_ENGINE", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        PerformanceAnalyzer, "_generate_with_gemini", lambda self, record, data: None
    )
    analyzer = PerformanceAnalyzer(logging=False, use_cache=False)
    assert _assert_strict_json(_generate(analyzer, inputs))["meta"]["engine"] == "local"


# ── Cache ─────────────────────────────────────────────────────────────────────

def test_cache_round_trip_avoids_a_second_call(inputs, tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_ENGINE", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    calls = {"n": 0}
    canned = LocalReportEngine().build(inputs)

    def fake_call(self, record, data):
        calls["n"] += 1
        return canned

    monkeypatch.setattr(PerformanceAnalyzer, "_generate_with_gemini", fake_call)

    first = _generate(PerformanceAnalyzer(logging=False, cache_dir=tmp_path), inputs)
    second = _generate(PerformanceAnalyzer(logging=False, cache_dir=tmp_path), inputs)

    assert calls["n"] == 1, "the second run must be served from cache"
    assert first.report_id == second.report_id
    _assert_strict_json(second)


def test_corrupt_cache_entry_is_ignored(inputs, tmp_path, monkeypatch):
    monkeypatch.setenv("REPORT_ENGINE", "gemini")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setattr(
        PerformanceAnalyzer, "_generate_with_gemini", lambda self, record, data: None
    )

    analyzer = PerformanceAnalyzer(logging=False, cache_dir=tmp_path)
    record = analyzer._compact_record(inputs)
    analyzer._cache_path(record).write_text("{not json at all", encoding="utf-8")

    assert _assert_strict_json(_generate(analyzer, inputs))["meta"]["engine"] == "local"


# ── Prompt payload ────────────────────────────────────────────────────────────

def test_compact_record_is_smaller_than_full_dump(inputs, unified):
    compact = json.dumps(
        PerformanceAnalyzer(logging=False)._compact_record(inputs), default=str
    )
    assert len(compact) < len(unified.model_dump_json()), (
        "compaction must actually reduce billed input tokens"
    )


def test_compact_record_keeps_the_facts_the_prompt_needs(inputs):
    record = PerformanceAnalyzer(logging=False)._compact_record(inputs)
    assert record["student"]["student_id"] == inputs.student.student_id
    assert len(record["interview"]["questions"]) == len(inputs.interview.questions)
    assert record["computed_kpis"]["overall_performance_score"] == (
        inputs.metrics.overall_performance_score
    )


# ── Gemini schema dialect ─────────────────────────────────────────────────────
# The API rejects the whole request on an unknown schema keyword, so the
# sanitiser is what makes the LLM path reachable at all.

def test_gemini_schema_contains_only_supported_keywords():
    schema = to_gemini_schema(StudentPerformanceReport.model_json_schema())
    offenders: list[str] = []

    def walk(node, path="$"):
        if isinstance(node, dict):
            is_map = path.endswith("/properties") or path.endswith("/$defs")
            for key, value in node.items():
                if not is_map and key not in GEMINI_SCHEMA_KEYWORDS:
                    offenders.append(f"{path}/{key}")
                walk(value, f"{path}/{key}")
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, f"{path}[{i}]")

    walk(schema)
    assert offenders == [], f"unsupported keywords would 400 the request: {offenders}"


def test_gemini_schema_drops_the_keywords_that_broke_the_request():
    raw = json.dumps(StudentPerformanceReport.model_json_schema())
    clean = json.dumps(to_gemini_schema(StudentPerformanceReport.model_json_schema()))
    assert "minLength" in raw and "minLength" not in clean
    assert '"default"' in raw and '"default"' not in clean


def test_gemini_schema_keeps_the_structure():
    schema = to_gemini_schema(StudentPerformanceReport.model_json_schema())
    assert schema["type"] == "object"
    assert "report_id" in schema["properties"]
    assert "student_id" in schema["required"]
    assert schema["$defs"]["ActionItem"]["properties"]["timeframe"]["enum"]


def test_ref_subschemas_carry_no_forbidden_siblings():
    """Gemini forbids non-$ keys alongside a $ref."""
    schema = to_gemini_schema(StudentPerformanceReport.model_json_schema())

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                assert all(k.startswith("$") for k in node), node
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(schema)


# ── End to end: stdout is always one JSON object ──────────────────────────────

# main.py loads .env, which may select the LLM engine. Pin these to the local
# engine so the suite stays free, offline and deterministic.
LOCAL_ENV = {**os.environ, "REPORT_ENGINE": "local"}


@pytest.mark.parametrize("args", [[], ["--quiet"]])
def test_main_stdout_is_strictly_json(args):
    result = subprocess.run(
        [sys.executable, "main.py", *args],
        cwd=PROJECT_ROOT,
        capture_output=True,
        timeout=120,
        env=LOCAL_ENV,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    # Decoding as UTF-8 is part of the contract: JSON is UTF-8 by definition,
    # and a Windows console would otherwise emit cp1252 bytes for em dashes.
    payload = json.loads(result.stdout.decode("utf-8"))
    StudentPerformanceReport.model_validate(payload)
    assert "student" not in payload
    assert "interview" not in payload
    assert "report" not in payload


def test_main_stdout_survives_a_shell_redirect(tmp_path):
    """The exact thing a user does: `python main.py > report.json`."""
    out = tmp_path / "report.json"
    with open(out, "wb") as fh:
        result = subprocess.run(
            [sys.executable, "main.py", "--quiet"],
            cwd=PROJECT_ROOT,
            stdout=fh,
            stderr=subprocess.PIPE,
            timeout=120,
            env=LOCAL_ENV,
        )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    payload = json.loads(out.read_text(encoding="utf-8"))
    StudentPerformanceReport.model_validate(payload)


def test_main_stdout_is_json_even_when_the_pipeline_dies():
    """A crashing pipeline must still leave stdout parseable."""
    script = (
        "import main\n"
        "class Boom:\n"
        "    def __init__(self, **kw):\n"
        "        raise FileNotFoundError('Missing source file: student.json')\n"
        "main.StudentDataPipeline = Boom\n"
        "main.main()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        timeout=120,
        env=LOCAL_ENV,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout.decode("utf-8"))
    assert payload["error"] == "FileNotFoundError"
