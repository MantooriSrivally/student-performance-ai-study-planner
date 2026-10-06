"""
app/core/analyzer.py — Report orchestration. Owns engine choice, cost control
and the strict-JSON guarantee.

Pipeline
--------
    compact record -> cache lookup -> engine -> parse -> validate -> cache write

Strict JSON, unconditionally
----------------------------
The return type is StudentPerformanceReport, a Pydantic model with
extra="forbid". Nothing else can leave this module:
  * the LLM is pinned to response_mime_type="application/json" plus a schema,
  * fences or stray prose are stripped by extract_json_object,
  * the parsed object is validated field by field,
  * identity fields are overwritten from the source record so a hallucinated
    name or id cannot survive,
  * any failure at any step falls back to LocalReportEngine, which cannot fail
    on valid inputs.
So callers never have to handle "the model returned prose" as a case.

Cost control
------------
  * Default engine is "local": no network call, no key, no billing, ever.
  * The LLM path is opt-in through REPORT_ENGINE=gemini.
  * Identical records hit the on-disk cache and bill nothing on re-runs.
  * The prompt ships a compacted record, not the full document dump.
  * Thinking budget is zeroed and output tokens are capped.
  * Oversized payloads are refused before the request is sent.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from app.core.json_util import extract_json_object
from app.core.prompts import SYSTEM_PROMPT, build_user_prompt
from app.core.report_engine import LocalReportEngine, ReportInputs
from app.models.domain import Assessment, Assignment, Attendance, Interview, Student
from app.models.metrics import PerformanceMetrics
from app.models.report import ReportMeta, StudentPerformanceReport
from app.utils.logger import JarvLogger

VALID_ENGINES = ("local", "gemini")

# Gemini validates the schema keyword-by-keyword and rejects the whole request
# on an unknown one. Pydantic emits `default` and `minLength`, neither of which
# is in this dialect, so the schema has to be filtered before it is sent.
GEMINI_SCHEMA_KEYWORDS = frozenset({
    "$id", "$defs", "$ref", "$anchor",
    "type", "format", "title", "description", "enum",
    "items", "prefixItems", "minItems", "maxItems",
    "minimum", "maximum", "anyOf", "oneOf",
    "properties", "additionalProperties", "required",
    "propertyOrdering",
})

_MAP_VALUED_KEYWORDS = frozenset({"properties", "$defs"})


def to_gemini_schema(node: Any) -> Any:
    """
    Rewrite a Pydantic JSON Schema into the subset Gemini accepts.

    Constraints dropped here are not lost: the prompt still carries the full
    schema as text, and the reply is validated against the real Pydantic model
    afterwards. This only keeps the request from being rejected outright.
    """
    if isinstance(node, list):
        return [to_gemini_schema(v) for v in node]
    if not isinstance(node, dict):
        return node

    # A $ref sub-schema may not carry siblings other than $-prefixed keys.
    if "$ref" in node:
        return {k: v for k, v in node.items() if k.startswith("$")}

    out: dict[str, Any] = {}
    for key, value in node.items():
        if key not in GEMINI_SCHEMA_KEYWORDS:
            continue
        if key in _MAP_VALUED_KEYWORDS and isinstance(value, dict):
            out[key] = {k: to_gemini_schema(v) for k, v in value.items()}
        else:
            out[key] = to_gemini_schema(value)
    return out


class PerformanceAnalyzer:
    """Builds a validated StudentPerformanceReport from the pipeline's outputs."""

    DEFAULT_ENGINE = "local"
    # Floating alias on the cheapest tier: pinned versions get retired for new
    # users, which fails the request with a 404.
    DEFAULT_MODEL = "gemini-flash-lite-latest"
    CACHE_DIR = Path(__file__).parent.parent.parent / ".report_cache"

    MAX_OUTPUT_TOKENS = 16384   # a full report is large; billing is per token emitted
    MAX_PROMPT_CHARS = 60_000   # refuse before spending tokens on a runaway payload
    ANSWER_CLIP_CHARS = 240     # interview answers are the bulkiest field
    TEMPERATURE = 0.3

    def __init__(
        self,
        engine: Optional[str] = None,
        model: Optional[str] = None,
        use_cache: bool = True,
        cache_dir: Optional[Path] = None,
        logging: bool = True,
    ):
        self.engine = (engine or os.getenv("REPORT_ENGINE") or self.DEFAULT_ENGINE).strip().lower()
        self.model = (model or os.getenv("REPORT_MODEL") or self.DEFAULT_MODEL).strip()
        self.use_cache = use_cache
        self.cache_dir = cache_dir or self.CACHE_DIR
        self.logging = logging
        self.local = LocalReportEngine()

        if self.engine not in VALID_ENGINES:
            self._warn(f"Unknown REPORT_ENGINE '{self.engine}'; falling back to 'local'")
            self.engine = "local"

    # ── Public API ────────────────────────────────────────────────────────────

    def generate(
        self,
        *,
        student: Student,
        interview: Interview,
        assignment: Assignment,
        assessment: Assessment,
        attendance: Attendance,
        metrics: PerformanceMetrics,
    ) -> StudentPerformanceReport:
        """Return a validated report. Never raises for valid inputs."""
        data = ReportInputs(
            student=student,
            interview=interview,
            assignment=assignment,
            assessment=assessment,
            attendance=attendance,
            metrics=metrics,
        )
        record = self._compact_record(data)

        if self.engine == "local":
            self._info("Report engine: local rule engine (0 API calls, 0 tokens, no cost)")
            return self.local.build(data)

        cached = self._cache_read(record)
        if cached is not None:
            self._ok("Report served from cache (0 API calls, 0 tokens, no cost)")
            return cached

        report = self._generate_with_gemini(record, data)
        if report is not None:
            self._cache_write(record, report)
            return report

        self._warn("Falling back to the local rule engine; JSON contract preserved")
        return self.local.build(data)

    # ── Stage 1: compact the record ───────────────────────────────────────────

    def _compact_record(self, data: ReportInputs) -> dict[str, Any]:
        """
        Trim the record to what the prompt actually needs.

        A full document dump is mostly redundant with the KPI block, and every
        redundant character is a billed input token. Long free-text answers are
        clipped because the panel score already encodes the verdict.
        """
        student = data.student
        interview = data.interview
        metrics = data.metrics
        attendance = data.attendance

        return {
            "student": {
                "student_id": student.student_id,
                "name": student.name,
                "department": student.department,
                "year": student.year,
                "semester": student.semester,
                "cgpa": student.cgpa,
            },
            "interview": {
                "company": interview.company,
                "job_role": interview.job_role,
                "interview_date": interview.interview_date.isoformat(),
                "overall_score": interview.overall_score,
                "questions": [
                    {
                        "question": q.question,
                        "student_answer": self._clip(q.student_answer),
                        "score": q.score,
                        "feedback": q.feedback,
                    }
                    for q in interview.questions
                ],
                "interviewer_observation": interview.interviewer_observation,
                "strengths": interview.strengths,
                "weaknesses": interview.weaknesses,
                "overall_feedback": self._clip(interview.overall_feedback),
            },
            "assignments": [
                {
                    "id": a.assignment_id,
                    "title": a.title,
                    "subject": a.subject,
                    "marks": a.marks,
                    "max_marks": a.max_marks,
                    "percent": round(a.marks / a.max_marks * 100, 2),
                    "status": a.submission_status,
                    "feedback": a.feedback,
                }
                for a in data.assignment.assignments
            ],
            "assessments": [
                {
                    "id": s.assessment_id,
                    "subject": s.subject,
                    "score": s.score,
                    "grade": s.grade,
                }
                for s in data.assessment.assessments
            ],
            "attendance": {
                "month": attendance.month,
                "working_days": attendance.working_days,
                "present_days": attendance.present_days,
                "absent_days": attendance.absent_days,
                "leave_days": attendance.leave_days,
                "percentage": attendance.attendance_percentage,
                "status": attendance.status,
            },
            "computed_kpis": metrics.model_dump(),
            "scoring_weights": {
                "interview": 0.40,
                "assignment": 0.30,
                "assessment": 0.20,
                "attendance": 0.10,
            },
        }

    def _clip(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        if len(text) <= self.ANSWER_CLIP_CHARS:
            return text
        return text[: self.ANSWER_CLIP_CHARS].rstrip() + "..."

    # ── Stage 2: cache ────────────────────────────────────────────────────────

    def _fingerprint(self, record: dict[str, Any]) -> str:
        """Hash the exact inputs that determine the output, so a hit is safe."""
        payload = json.dumps(
            {"record": record, "engine": self.engine, "model": self.model},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    def _cache_path(self, record: dict[str, Any]) -> Path:
        return self.cache_dir / f"{self._fingerprint(record)}.json"

    def _cache_read(self, record: dict[str, Any]) -> Optional[StudentPerformanceReport]:
        if not self.use_cache:
            return None
        path = self._cache_path(record)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return StudentPerformanceReport.model_validate(json.load(f))
        except (OSError, json.JSONDecodeError, ValidationError) as e:
            # A stale or corrupt entry must never break the run.
            self._warn(f"Ignoring unusable cache entry {path.name}: {e}")
            return None

    def _cache_write(self, record: dict[str, Any], report: StudentPerformanceReport) -> None:
        if not self.use_cache:
            return
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            path = self._cache_path(record)
            with open(path, "w", encoding="utf-8") as f:
                f.write(report.model_dump_json(indent=2))
            self._info(f"Cached report as {path.name}; identical re-runs cost nothing")
        except OSError as e:
            self._warn(f"Could not write report cache: {e}")

    # ── Stage 3: LLM path ─────────────────────────────────────────────────────

    def _generate_with_gemini(
        self, record: dict[str, Any], data: ReportInputs
    ) -> Optional[StudentPerformanceReport]:
        """Call Gemini and validate. Returns None on any failure — caller falls back."""
        api_key = os.getenv("GOOGLE_API_KEY", "").strip()
        if not api_key or api_key == "your_api_key_here":
            self._warn("REPORT_ENGINE=gemini but GOOGLE_API_KEY is not set")
            return None

        try:
            from google import genai
            from google.genai import types
        except ImportError as e:
            self._warn(f"google-genai is not installed ({e}); run: pip install google-genai")
            return None

        prompt = build_user_prompt(record)
        client = genai.Client(api_key=api_key)

        # One repair attempt: a near-miss reply is worth correcting, but the
        # call count stays bounded so the bill cannot run away.
        for attempt in (1, 2):
            budget = len(SYSTEM_PROMPT) + len(prompt)
            if budget > self.MAX_PROMPT_CHARS:
                self._warn(
                    f"Prompt is {budget} chars, over the {self.MAX_PROMPT_CHARS} guard; "
                    f"refusing the call to avoid an oversized bill"
                )
                return None

            self._info(
                f"Gemini '{self.model}' attempt {attempt}/2 "
                f"(~{budget // 4} input tokens estimated)"
            )

            try:
                response = self._call(client, types, prompt)
            except Exception as e:
                self._warn(f"Gemini request failed: {type(e).__name__}: {e}")
                return None

            self._log_usage(response)

            try:
                payload = extract_json_object(response.text)
            except (ValueError, TypeError, json.JSONDecodeError) as e:
                self._warn(f"Model reply was not a JSON object: {e}")
                return None

            try:
                report = StudentPerformanceReport.model_validate(payload)
            except ValidationError as e:
                self._warn(f"Model JSON failed schema validation ({e.error_count()} error(s))")
                if attempt == 2:
                    return None
                prompt = self._repair_prompt(prompt, e)
                continue

            self._ok("Gemini report parsed and schema-validated")
            return self._pin_identity(report, data)

        return None

    @staticmethod
    def _repair_prompt(prompt: str, error: ValidationError) -> str:
        """Append the exact rejections so the retry is targeted, not a reroll."""
        faults = "\n".join(
            f"- {'.'.join(str(p) for p in err['loc'])}: {err['msg']}"
            for err in error.errors()[:20]
        )
        return (
            f"{prompt}\n\n"
            f"Your previous reply was rejected by schema validation:\n{faults}\n\n"
            f"Fix exactly these problems and return only the corrected JSON object."
        )

    def _call(self, client: Any, types: Any, prompt: str) -> Any:
        """
        Issue one request, with a single downgrade path.

        Thinking controls are model-specific: Gemini 3 wants thinking_level and
        rejects thinking_budget=0, while older models want the budget. Rather
        than mapping model names to dialects, ask for the thrifty setting and
        drop it if the API refuses.
        """
        try:
            return client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_config(types, thrifty=True),
            )
        except Exception as e:
            if "INVALID_ARGUMENT" not in str(e):
                raise
            self._warn("Model rejected the minimal-thinking setting; retrying without it")
            return client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._build_config(types, thrifty=False),
            )

    def _build_config(self, types: Any, thrifty: bool = True) -> Any:
        """
        Schema-constrained JSON output, kept as cheap as the model allows.

        response_json_schema is used rather than response_schema: the latter
        runs the model class through the SDK's proto conversion, which emits an
        `additional_properties` field that the API rejects outright.
        """
        kwargs: dict[str, Any] = {
            "system_instruction": SYSTEM_PROMPT,
            "response_mime_type": "application/json",
            "response_json_schema": to_gemini_schema(
                StudentPerformanceReport.model_json_schema()
            ),
            "temperature": self.TEMPERATURE,
            "max_output_tokens": self.MAX_OUTPUT_TOKENS,
        }
        thinking_config = getattr(types, "ThinkingConfig", None)
        if thrifty and thinking_config is not None:
            if "thinking_level" in getattr(thinking_config, "model_fields", {}):
                kwargs["thinking_config"] = thinking_config(thinking_level="minimal")
        return types.GenerateContentConfig(**kwargs)

    def _log_usage(self, response: Any) -> None:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        self._info(
            f"Tokens billed — input: {getattr(usage, 'prompt_token_count', '?')}, "
            f"output: {getattr(usage, 'candidates_token_count', '?')}, "
            f"total: {getattr(usage, 'total_token_count', '?')}"
        )

    # ── Stage 4: harden the validated result ──────────────────────────────────

    def _pin_identity(
        self, report: StudentPerformanceReport, data: ReportInputs
    ) -> StudentPerformanceReport:
        """
        Overwrite fields the model must not author.

        Identity comes from the source record, and meta records the engine that
        actually ran rather than whatever the model claimed.
        """
        return report.model_copy(
            update={
                "student_id": data.student.student_id,
                "student_name": data.student.name,
                "meta": ReportMeta(engine="gemini", model=self.model, strict_json=True),
            }
        )

    # ── Logging shims ─────────────────────────────────────────────────────────

    def _info(self, msg: str) -> None:
        if self.logging:
            JarvLogger.info(msg)

    def _ok(self, msg: str) -> None:
        if self.logging:
            JarvLogger.success(msg)

    def _warn(self, msg: str) -> None:
        if self.logging:
            JarvLogger.warn(msg)
