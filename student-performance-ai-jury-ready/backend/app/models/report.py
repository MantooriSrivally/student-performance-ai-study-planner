"""
app/models/report.py — Strict JSON schema for the student performance report.

Every field is required. Extra keys are forbidden so LLM output can be
validated 1:1 against this contract.
"""

from typing import List, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class OverallPerformance(StrictModel):
    score: float = Field(ge=0, le=100, description="Weighted composite score 0-100")
    grade: Literal["Outstanding", "Very Good", "Good", "Average", "Below Average", "Needs Improvement"]
    letter: Literal["O", "A+", "A", "B", "C", "D"]
    status: Literal["Placement Ready", "Almost Ready", "Needs Preparation", "Not Ready"]
    headline: str = Field(min_length=12, description="One-line board-level verdict")


class DimensionScore(StrictModel):
    name: str
    score: float = Field(ge=0, le=100)
    band: Literal["Outstanding", "Strong", "Developing", "Needs Focus"]
    narrative: str = Field(min_length=20, description="Evidence-backed comment for this dimension")


class EvidencePoint(StrictModel):
    title: str
    evidence: str = Field(description="Concrete fact or quote from the student record")
    impact: Literal["high", "medium", "low"]
    why_it_matters: str


class QuestionInsight(StrictModel):
    question: str
    score: int = Field(ge=0, le=10)
    topic: str
    verdict: Literal["Excellent", "Strong", "Adequate", "Needs Work"]
    coaching_note: str


class TraitRating(StrictModel):
    trait: str
    rating: str


class InterviewDeepDive(StrictModel):
    company: str
    role: str
    interview_date: str
    overall_score: float = Field(ge=0, le=10)
    question_average: float = Field(ge=0, le=10)
    strongest_topic: str
    weakest_topic: str
    questions: List[QuestionInsight] = Field(min_length=1)
    observations: List[TraitRating]
    narrative: str = Field(min_length=40)


class AcademicItem(StrictModel):
    id: str
    title: str
    subject: str
    percent: float = Field(ge=0, le=100)
    detail: str


class AcademicSnapshot(StrictModel):
    cgpa: float = Field(ge=0, le=10)
    assignment_average: float = Field(ge=0, le=100)
    assessment_average: float = Field(ge=0, le=100)
    on_time_rate: float = Field(ge=0, le=100)
    items: List[AcademicItem]
    narrative: str = Field(min_length=40)


class AttendanceSnapshot(StrictModel):
    month: str
    percentage: float = Field(ge=0, le=100)
    present_days: int
    working_days: int
    status: Literal["Eligible", "Not Eligible"]
    narrative: str = Field(min_length=20)


class ActionItem(StrictModel):
    priority: int = Field(ge=1, le=10)
    timeframe: Literal["7 days", "30 days", "60 days", "90 days"]
    skill: str
    action: str
    success_metric: str


class PlacementReadiness(StrictModel):
    status: Literal["Placement Ready", "Almost Ready", "Needs Preparation", "Not Ready"]
    confidence: float = Field(ge=0, le=100)
    target_roles: List[str] = Field(min_length=1)
    company_fit: List[str] = Field(min_length=1)
    blockers: List[str]
    narrative: str = Field(min_length=40)


class ReportMeta(StrictModel):
    engine: Literal["local", "spacexai", "gemini"]
    model: str
    strict_json: bool = True


class ScorecardRow(StrictModel):
    """One line of the printable one-page scorecard."""

    metric: str
    value: str
    benchmark: str
    result: Literal["Pass", "Watch", "Fail"]


class BoardDecision(StrictModel):
    """Final placement-cell decision block for the output report."""

    decision: Literal["CLEAR_FOR_DRIVES", "HOLD_ONE_CYCLE", "INTENSIVE_SUPPORT"]
    decision_label: str
    rationale: str = Field(min_length=40)
    next_review_date: str = Field(description="ISO date for next checkpoint")
    priority_fix: str = Field(min_length=12, description="Single highest-leverage action")
    signed_by: str = Field(description="Issuing system or counselor name")


class PerformanceTier(StrictModel):
    """Placement cohort: Tier 1 (ready), Tier 2 (near-ready), Tier 3 (foundation)."""

    tier: Literal[1, 2, 3]
    label: Literal["Tier 1", "Tier 2", "Tier 3"]
    title: str = Field(description="Human label, e.g. Placement Ready Elite")
    score_band: str = Field(description="Score range that defines this tier")
    narrative: str = Field(min_length=40)


class LaggingArea(StrictModel):
    area: str
    current_score: float = Field(ge=0, le=100)
    target_score: float = Field(ge=0, le=100)
    gap: float = Field(ge=0)
    severity: Literal["critical", "moderate", "mild"]
    evidence: str
    fix_hint: str


class WeaknessItem(StrictModel):
    weakness: str
    root_cause: str
    evidence: str
    severity: Literal["critical", "moderate", "mild"]
    related_area: str


class WeaknessAnalysis(StrictModel):
    summary: str = Field(min_length=40)
    primary_weakness: str
    pattern: str = Field(description="Cross-cutting pattern across gaps")
    items: List[WeaknessItem] = Field(min_length=1)


class StudyPlanPhase(StrictModel):
    phase: str = Field(description="e.g. Days 1–7")
    focus_skill: str
    daily_routine: str
    practice_tasks: List[str] = Field(min_length=2)
    real_world_resources: List[str] = Field(min_length=2)
    success_checkpoint: str


class RealWorldStudyPlan(StrictModel):
    overview: str = Field(min_length=40)
    duration: str
    weekly_hours: float = Field(ge=1, le=80)
    phases: List[StudyPlanPhase] = Field(min_length=3, max_length=6)
    daily_habits: List[str] = Field(min_length=2)
    tools_and_platforms: List[str] = Field(min_length=2)


class SkillNode(StrictModel):
    """One node in the placement skill dependency graph."""

    id: str
    label: str
    score: float = Field(ge=0, le=100)
    band: Literal["Outstanding", "Strong", "Developing", "Needs Focus"]
    layer: Literal["foundation", "core", "applied", "outcome"]
    evidence: str = Field(min_length=12, description="Where this score came from")
    health: Literal["healthy", "watch", "blocking"] = Field(
        description="blocking = limits downstream skills"
    )


class SkillEdge(StrictModel):
    """Directed prerequisite → dependent relationship."""

    source: str
    target: str
    relation: str = Field(description="e.g. unlocks, feeds, gates")
    strength: Literal["strong", "adequate", "fragile"] = Field(
        description="fragile when the source skill is weaker than the target needs"
    )

class SkillGraph(StrictModel):
    """Skill relationship map — not a flat percentage list."""

    root_skill: str
    nodes: List[SkillNode] = Field(min_length=4)
    edges: List[SkillEdge] = Field(min_length=3)
    bottleneck_skill: str
    downstream_count: int = Field(ge=0)
    insight: str = Field(
        min_length=40,
        description="e.g. Improving OOP is likely to improve three downstream areas",
    )


class WarningSignal(StrictModel):
    """One early-warning trajectory signal."""

    metric: str
    direction: Literal["down", "flat", "up"]
    delta_label: str = Field(description="Human delta, e.g. ↓ 12% vs healthy band")
    detail: str


class EarlyWarning(StrictModel):
    """Proactive trajectory alert — detect the path before the outcome."""

    active: bool
    severity: Literal["critical", "elevated", "watch", "clear"]
    title: str
    signals: List[WarningSignal]
    predicted_issue: str
    recommended_intervention: str = Field(min_length=20)
    trajectory_summary: str = Field(min_length=40)


class WhatIfLever(StrictModel):
    """One controllable input for the what-if simulator / report scenario."""

    key: str
    label: str
    current: float
    unit: Literal["percent", "score10"]
    recommended: float
    min_value: float
    max_value: float


class WhatIfScenario(StrictModel):
    """Engine-computed current vs recommended simulation for the final report."""

    current_readiness: float = Field(ge=0, le=100)
    simulated_readiness: float = Field(ge=0, le=100)
    delta: float
    largest_drivers: List[str] = Field(min_length=1)
    levers: List[WhatIfLever] = Field(min_length=4)
    narrative: str = Field(min_length=40)
    formula_note: str = Field(min_length=20)


class StudentPerformanceReport(StrictModel):
    """Board-ready placement report. This is the LLM JSON contract."""

    report_id: str
    generated_at: str = Field(description="ISO-8601 UTC timestamp")
    student_id: str
    student_name: str
    headline: str = Field(min_length=12)
    executive_summary: str = Field(min_length=80, description="3 short paragraphs, evidence-heavy")
    overall_performance: OverallPerformance
    performance_tier: PerformanceTier
    dimension_scores: List[DimensionScore] = Field(min_length=4)
    interview_deep_dive: InterviewDeepDive
    academic_snapshot: AcademicSnapshot
    attendance_snapshot: AttendanceSnapshot
    strengths: List[EvidencePoint] = Field(min_length=2)
    growth_areas: List[EvidencePoint] = Field(min_length=1)
    weakness_analysis: WeaknessAnalysis
    lagging_areas: List[LaggingArea] = Field(min_length=1)
    risk_flags: List[str]
    skill_graph: SkillGraph
    early_warning: EarlyWarning
    what_if_scenario: WhatIfScenario
    placement_readiness: PlacementReadiness
    action_plan: List[ActionItem] = Field(min_length=3, max_length=6)
    study_plan: RealWorldStudyPlan
    board_decision: BoardDecision
    scorecard: List[ScorecardRow] = Field(min_length=5, max_length=10)
    methodology_note: str = Field(min_length=40)
    counselor_recommendation: str = Field(min_length=40)
    closing_note: str = Field(min_length=20)
    meta: ReportMeta
