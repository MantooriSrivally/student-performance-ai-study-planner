"""
app/core/pipeline.py — Load > Validate > KPIs > strict-JSON report.

No separate loader, aggregator, or config — everything lives here.
The SOURCES registry drives the entire process declaratively.
"""

import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Type

from pydantic import BaseModel, ValidationError

from app.core.analyzer import PerformanceAnalyzer
from app.models.domain import Student, Interview, Assignment, Assessment, Attendance
from app.models.metrics import PerformanceMetrics
from app.models.unified import UnifiedStudent
from app.utils.logger import JarvLogger


# ── Scoring weights (inlined — no separate config file) ───────────────────────

@dataclass
class ScoringWeights:
    interview:  float = 0.40
    assignment: float = 0.30
    assessment: float = 0.20
    attendance: float = 0.10

    def __post_init__(self):
        total = self.interview + self.assignment + self.assessment + self.attendance
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Weights must sum to 1.0, got {total:.4f}")


# ── Declarative source registry ───────────────────────────────────────────────
# Add or remove data sources here — the pipeline picks them up automatically.

SOURCES: dict[str, tuple[str, Type[BaseModel]]] = {
    "student":     ("student.json",     Student),
    "interview":   ("interview.json",   Interview),
    "assignment":  ("assignment.json",  Assignment),
    "assessment":  ("assessment.json",  Assessment),
    "attendance":  ("attendance.json",  Attendance),
}


# ── Pipeline ──────────────────────────────────────────────────────────────────

class StudentDataPipeline:
    """
    Reads JSON sources → cleans & validates via Pydantic → computes KPIs → UnifiedStudent.
    Everything in one place. No external loaders or aggregators needed.
    """

    DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "mock_data"

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        weights: Optional[ScoringWeights] = None,
        logging: bool = True,
    ):
        self.data_dir = data_dir or self.DEFAULT_DATA_DIR
        self.weights  = weights or ScoringWeights()
        self.logging  = logging

    # ── Stage 1: Load ─────────────────────────────────────────────────────────

    def _load_source(self, path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Missing source file: {path.name}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise TypeError(f"{path.name}: expected a JSON object, got {type(data).__name__}")
        return data

    def _load_all(self) -> dict[str, dict]:
        return {
            key: self._load_source(self.data_dir / filename)
            for key, (filename, _) in SOURCES.items()
        }

    # ── Stage 2: Validate & Clean ─────────────────────────────────────────────

    def _validate_all(self, raw: dict[str, dict]) -> dict[str, BaseModel]:
        """Runs each raw dict through its registered Pydantic model — validation IS cleaning."""
        try:
            return {
                key: model.model_validate(raw[key])
                for key, (_, model) in SOURCES.items()
            }
        except ValidationError as e:
            raise ValueError(f"Validation failure:\n{e}") from e

    def _assert_id_consistency(self, parsed: dict[str, BaseModel]) -> None:
        """All sources must share the same student_id."""
        expected = parsed["student"].student_id
        mismatches = {
            key: obj.student_id
            for key, obj in parsed.items()
            if hasattr(obj, "student_id") and obj.student_id != expected
        }
        if mismatches:
            raise ValueError(f"student_id mismatch — expected '{expected}', got: {mismatches}")

    # ── Stage 3: Compute KPIs ─────────────────────────────────────────────────

    def _compute_metrics(self, parsed: dict[str, BaseModel]) -> PerformanceMetrics:
        assignment: Assignment = parsed["assignment"]
        assessment: Assessment = parsed["assessment"]
        interview:  Interview  = parsed["interview"]
        attendance: Attendance = parsed["attendance"]
        w = self.weights

        a_items = assignment.assignments
        s_items = assessment.assessments

        assign_avg = round(
            sum(a.marks / a.max_marks * 100.0 for a in a_items) / len(a_items), 2
        ) if a_items else 0.0

        assess_avg = round(
            sum(s.score for s in s_items) / len(s_items), 2
        ) if s_items else 0.0

        int_score = interview.overall_score
        att_score = attendance.attendance_percentage

        overall = round(
            (int_score * 10 * w.interview)
            + (assign_avg  * w.assignment)
            + (assess_avg  * w.assessment)
            + (att_score   * w.attendance),
            2,
        )

        return PerformanceMetrics(
            assignment_average=assign_avg,
            assessment_average=assess_avg,
            interview_score=int_score,
            attendance_score=att_score,
            overall_performance_score=overall,
            total_assignments=len(a_items),
            total_assessments=len(s_items),
            on_time_submissions=sum(1 for a in a_items if a.submission_status == "On Time"),
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> UnifiedStudent:
        """Execute the full pipeline. Returns a clean, validated UnifiedStudent."""
        log = self.logging
        if log:
            JarvLogger.header("STUDENT DATA PIPELINE")
            JarvLogger.system(f"Source directory: {self.data_dir}")

        total_start = time.perf_counter()
        timings: dict[str, float] = {}

        # Stage 1 — Load
        t = time.perf_counter()
        if log: JarvLogger.info("Stage 1/4: Loading source JSON files...")
        raw = self._load_all()
        timings["1. LOAD"] = (time.perf_counter() - t) * 1000

        # Stage 2 — Validate & Clean
        t = time.perf_counter()
        if log: JarvLogger.info("Stage 2/4: Validating and cleaning all sources...")
        parsed = self._validate_all(raw)
        self._assert_id_consistency(parsed)
        timings["2. VALIDATE"] = (time.perf_counter() - t) * 1000

        # Stage 3 — Aggregate
        t = time.perf_counter()
        if log: JarvLogger.info("Stage 3/4: Computing KPIs...")
        metrics = self._compute_metrics(parsed)
        timings["3. KPIs"] = (time.perf_counter() - t) * 1000

        # Stage 4 — Strict-JSON performance report (LLM if keyed, else local)
        t = time.perf_counter()
        if log: JarvLogger.info("Stage 4/4: Generating strict-JSON performance report...")
        report = PerformanceAnalyzer(logging=log).generate(
            student=parsed["student"],
            interview=parsed["interview"],
            assignment=parsed["assignment"],
            assessment=parsed["assessment"],
            attendance=parsed["attendance"],
            metrics=metrics,
        )
        unified = UnifiedStudent(
            student    = parsed["student"],
            interview  = parsed["interview"],
            assignment = parsed["assignment"],
            assessment = parsed["assessment"],
            attendance = parsed["attendance"],
            metrics    = metrics,
            report     = report,
        )
        timings["4. REPORT"] = (time.perf_counter() - t) * 1000

        total_ms = (time.perf_counter() - total_start) * 1000

        if log:
            JarvLogger.success(f"Pipeline completed in {total_ms:.2f} ms")
            for label, ms in timings.items():
                JarvLogger.metrics_summary(label, ms)
            print("-" * 65, file=sys.stderr)

        return unified
