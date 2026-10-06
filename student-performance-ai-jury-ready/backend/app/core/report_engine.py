"""
app/core/report_engine.py — Local report generator. Zero network, zero billing.

Builds a complete StudentPerformanceReport from the validated sources using
deterministic rules over the already-computed KPIs.

Two jobs:
  1. Default engine, so a report is available with no API key and no cost.
  2. Guaranteed fallback for the analyzer. Because this path can never fail on
     valid inputs, the JSON contract holds even when an LLM reply is malformed,
     truncated, refused, or the network is down.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.report import (
    AcademicItem,
    AcademicSnapshot,
    ActionItem,
    AttendanceSnapshot,
    BoardDecision,
    DimensionScore,
    EarlyWarning,
    EvidencePoint,
    InterviewDeepDive,
    LaggingArea,
    OverallPerformance,
    PerformanceTier,
    PlacementReadiness,
    QuestionInsight,
    RealWorldStudyPlan,
    ReportMeta,
    ScorecardRow,
    SkillEdge,
    SkillGraph,
    SkillNode,
    StudentPerformanceReport,
    StudyPlanPhase,
    TraitRating,
    WarningSignal,
    WeaknessAnalysis,
    WeaknessItem,
    WhatIfLever,
    WhatIfScenario,
)
from app.models.domain import Assessment, Assignment, Attendance, Interview, Student
from app.models.metrics import PerformanceMetrics

MODEL_NAME = "rule-engine-v1"


@dataclass(frozen=True)
class ReportInputs:
    """
    Validated sources plus computed KPIs — everything a report is derived from.

    The report is itself a field of UnifiedStudent, so the engine cannot accept
    a UnifiedStudent as input. This carries the same facts without the cycle.
    """

    student: Student
    interview: Interview
    assignment: Assignment
    assessment: Assessment
    attendance: Attendance
    metrics: PerformanceMetrics

# ── Topic inference ───────────────────────────────────────────────────────────
# Ordered: the first keyword hit wins, so put narrow topics before broad ones.

TOPIC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SQL & Databases",        ("sql", "join", "database", "query", "normalis", "normaliz", "index")),
    ("OOP & Design",           ("object-oriented", "object oriented", "oop", "inherit", "polymorph",
                                "encapsul", "abstraction", "class and object")),
    ("Web & APIs",             ("fastapi", "flask", "django", "rest", "api", "http", "get and post",
                                "endpoint", "swagger")),
    ("Machine Learning",       ("machine learning", "deep learning", "neural", "regression",
                                "overfit", "training data")),
    ("DSA & Problem Solving",  ("reverse", "sort", "array", "linked list", "stack", "queue",
                                "complexity", "algorithm", "recursion", "palindrome")),
    ("Python Fundamentals",    ("python", "list and tuple", "list vs tuple", "tuple", "dictionary",
                                "decorator", "generator", "string")),
    ("Behavioural & Comms",    ("yourself", "strength", "weakness", "why should we", "career",
                                "team", "conflict", "five years")),
)

DEFAULT_TOPIC = "General Technical"


def _infer_topic(question: str) -> str:
    text = question.lower()
    for topic, keywords in TOPIC_KEYWORDS:
        if any(k in text for k in keywords):
            return topic
    return DEFAULT_TOPIC


# ── Banding helpers ───────────────────────────────────────────────────────────

def _band(score: float) -> str:
    if score >= 85.0:
        return "Outstanding"
    if score >= 70.0:
        return "Strong"
    if score >= 55.0:
        return "Developing"
    return "Needs Focus"


def _grade_and_letter(score: float) -> tuple[str, str]:
    if score >= 90.0:
        return "Outstanding", "O"
    if score >= 80.0:
        return "Very Good", "A+"
    if score >= 70.0:
        return "Good", "A"
    if score >= 60.0:
        return "Average", "B"
    if score >= 50.0:
        return "Below Average", "C"
    return "Needs Improvement", "D"


def _verdict(score: int) -> str:
    if score >= 9:
        return "Excellent"
    if score >= 8:
        return "Strong"
    if score >= 6:
        return "Adequate"
    return "Needs Work"


def _readiness(score: float, attendance_eligible: bool) -> str:
    if not attendance_eligible:
        # Attendance is a hard placement gate, so it caps the verdict.
        return "Needs Preparation" if score >= 55.0 else "Not Ready"
    if score >= 85.0:
        return "Placement Ready"
    if score >= 70.0:
        return "Almost Ready"
    if score >= 55.0:
        return "Needs Preparation"
    return "Not Ready"


def _pct(part: float, whole: float) -> float:
    return round(part / whole * 100.0, 2) if whole else 0.0


# ── Action templates ──────────────────────────────────────────────────────────
# Keyed by dimension/topic so the plan names a real skill instead of "study more".

ACTION_TEMPLATES: dict[str, tuple[str, str, str]] = {
    "SQL & Databases": (
        "SQL",
        "Solve 30 JOIN queries across INNER, LEFT, RIGHT and FULL OUTER on a sample schema, "
        "then rewrite 5 of them using subqueries and window functions",
        "Score 9/10 or higher on a timed 20-question SQL JOIN quiz",
    ),
    "DSA & Problem Solving": (
        "Data Structures & Algorithms",
        "Complete 40 problems across arrays, strings, hashing and two-pointer patterns, "
        "writing the time and space complexity for each before coding",
        "Solve 3 of 3 medium problems inside 45 minutes without hints",
    ),
    "Interview Performance": (
        "Interview Delivery",
        "Run 4 recorded mock interviews and rebuild every answer that scored below 8 "
        "into a 60-second structured response",
        "Average 8.5/10 or higher across the final two mock interviews",
    ),
    "Assignment Discipline": (
        "Assignment Consistency",
        "Submit every assignment at least 24 hours before the deadline and log the "
        "reviewer feedback into a running improvement sheet",
        "100% on-time submission rate with zero pending items",
    ),
    "Assessment Command": (
        "Core Subject Depth",
        "Rework every assessment question that lost marks, then re-attempt the full "
        "paper under exam timing",
        "Raise the assessment average by 5 percentage points on the next attempt",
    ),
    "Attendance & Discipline": (
        "Attendance",
        "Attend every scheduled session this month and clear any backlog work from "
        "days already missed",
        "Hold attendance at 90% or above with Eligible status maintained",
    ),
    "Academic Standing": (
        "CGPA Trajectory",
        "Target the two lowest-scoring subjects with weekly problem sets and faculty "
        "office-hour reviews",
        "Improve the next semester GPA by at least 0.3 over the current CGPA",
    ),
    "Web & APIs": (
        "Backend Engineering",
        "Ship one production-shaped REST service with authentication, pagination, "
        "tests and deployed documentation",
        "A deployed API with a public docs URL and green test suite",
    ),
    "Machine Learning": (
        "Machine Learning",
        "Take one dataset end to end: cleaning, feature engineering, model comparison "
        "and a written error analysis",
        "A published notebook with a documented baseline and a beaten benchmark",
    ),
    "Python Fundamentals": (
        "Python Depth",
        "Study mutability, comprehensions, decorators and generators, then explain each "
        "aloud in under 60 seconds with a code example",
        "Explain all four topics unprompted in a peer review session",
    ),
    "OOP & Design": (
        "OOP & Design",
        "Model a small system with classes, then refactor it to demonstrate each of the "
        "four OOP pillars explicitly",
        "Whiteboard the design in 10 minutes naming all four pillars with examples",
    ),
    "Behavioural & Comms": (
        "Behavioural Answers",
        "Write and rehearse STAR-format answers for the eight most common behavioural "
        "questions using real project examples",
        "Deliver any behavioural answer in under 90 seconds without filler",
    ),
}

FALLBACK_ACTION: tuple[str, str, str] = (
    "Placement Readiness",
    "Hold a weekly review of interview recordings, assignment feedback and assessment "
    "papers, converting each gap into a dated practice task",
    "A written weekly log showing every logged gap closed or scheduled",
)

STRETCH_ACTION: tuple[str, str, str] = (
    "Advanced Differentiation",
    "Build one portfolio project that goes beyond coursework and publish a written "
    "breakdown of the architecture decisions",
    "A live project link plus a technical write-up reviewed by a mentor",
)

TIMEFRAMES: tuple[str, str, str, str] = ("7 days", "30 days", "60 days", "90 days")

# Real-world resources keyed by skill/topic for the study plan.
STUDY_RESOURCES: dict[str, tuple[str, ...]] = {
    "SQL & Databases": (
        "Mode SQL Tutorial (joins + window functions)",
        "LeetCode Database problem set (30 JOIN-heavy queries)",
        "PostgreSQL docs — SELECT / JOIN / Window Functions",
    ),
    "DSA & Problem Solving": (
        "NeetCode 150 — Arrays, Hashing, Two Pointers",
        "LeetCode Explore cards (Arrays & Strings)",
        "Abdul Bari YouTube — Time & Space Complexity",
    ),
    "Interview Performance": (
        "Pramp or Interviewing.io mock interviews (2/week)",
        "Record answers on Loom and self-score against STAR",
        "Ex-interviewer feedback sessions via college placement cell",
    ),
    "Assignment Discipline": (
        "Notion or Google Sheet deadline tracker shared with mentor",
        "GitHub project board with due dates and PR reviews",
        "Pomodoro 50/10 blocks for assignment deep work",
    ),
    "Assessment Command": (
        "Previous year university papers under timed conditions",
        "Anki flashcards for formulas and definitions",
        "Faculty office hours — rework every lost-mark question",
    ),
    "Attendance & Discipline": (
        "Calendar blocking for every lecture + weekly attendance audit",
        "Buddy system: one peer check-in after each missed class",
        "College LMS / ERP attendance dashboard daily glance",
    ),
    "Academic Standing": (
        "Subject-wise weekly problem sets from lowest CGPA courses",
        "Faculty remediation / tutorial sessions",
        "Semester GPA tracker spreadsheet with target delta +0.3",
    ),
    "Web & APIs": (
        "FastAPI official tutorial + deploy on Render/Railway",
        "freeCodeCamp REST API course",
        "Build and document one CRUD service with JWT auth",
    ),
    "Machine Learning": (
        "Kaggle Learn — Intro to ML + Intermediate ML",
        "One end-to-end notebook on a public dataset (UCI / Kaggle)",
        "Google ML Crash Course (feature engineering modules)",
    ),
    "Python Fundamentals": (
        "Real Python tutorials — mutability, decorators, generators",
        "Python docs tutorial + Fluent Python selected chapters",
        "Exercism Python track (30 exercises)",
    ),
    "OOP & Design": (
        "Refactor Guru — OOP principles & design patterns",
        "Whiteboard one mini system (library / parking lot) weekly",
        "Head First Design Patterns — selected chapters",
    ),
    "Behavioural & Comms": (
        "Amazon Leadership Principles STAR bank (write 8 stories)",
        "Toastmasters / college GD club for 5-minute talks",
        "Record and trim filler words with Otter.ai transcripts",
    ),
}

DEFAULT_RESOURCES: tuple[str, ...] = (
    "College placement cell mock interviews",
    "GitHub portfolio with weekly commits",
    "LinkedIn Learning or Coursera skill path matching weakest topic",
)

TARGET_SCORE = 80.0


def _tier_from_score(overall: float, eligible: bool, interview_score: float) -> PerformanceTier:
    """
    Tier 1 — Placement Ready Elite (high composite + eligible + strong interview)
    Tier 2 — Competitive Contender (solid composite, near placement)
    Tier 3 — Foundation Builder (needs structured prep before drives)
    """
    if eligible and overall >= 85.0 and interview_score >= 8.0:
        return PerformanceTier(
            tier=1,
            label="Tier 1",
            title="Placement Ready Elite",
            score_band="85-100 (eligible, interview >= 8/10)",
            narrative=(
                f"Composite {overall:.2f}% with interview {interview_score:.2f}/10 and Eligible "
                f"attendance places this student in Tier 1 — cleared for active placement drives "
                f"with depth work rather than remediation."
            ),
        )
    if eligible and overall >= 70.0:
        return PerformanceTier(
            tier=2,
            label="Tier 2",
            title="Competitive Contender",
            score_band="70-84 (eligible)",
            narrative=(
                f"Composite {overall:.2f}% with Eligible status places this student in Tier 2 — "
                f"realistic for service-based drives this cycle, and product-company ready once "
                f"the weakest topic is closed in one focused sprint."
            ),
        )
    return PerformanceTier(
        tier=3,
        label="Tier 3",
        title="Foundation Builder",
        score_band="Below 70 or attendance Not Eligible",
        narrative=(
            f"Composite {overall:.2f}% "
            f"{'(attendance Not Eligible) ' if not eligible else ''}"
            f"places this student in Tier 3 — hold premium drives, enrol in a structured "
            f"90-day study plan, and re-score before the next placement cycle."
        ),
    )


def _severity(gap: float) -> str:
    if gap >= 25.0:
        return "critical"
    if gap >= 12.0:
        return "moderate"
    return "mild"


# ── Engine ────────────────────────────────────────────────────────────────────

class LocalReportEngine:
    """Deterministic report builder. Same output schema as the LLM path."""

    ENGINE = "local"
    MODEL = MODEL_NAME

    def build(self, data: ReportInputs) -> StudentPerformanceReport:
        student = data.student
        interview = data.interview
        metrics = data.metrics
        attendance = data.attendance

        questions = interview.questions
        q_scores = [q.score for q in questions]
        q_avg = round(sum(q_scores) / len(q_scores), 2) if q_scores else 0.0

        topic_avgs = self._topic_averages(questions)
        strongest = max(topic_avgs.items(), key=lambda kv: (kv[1], kv[0]))[0]
        weakest = min(topic_avgs.items(), key=lambda kv: (kv[1], kv[0]))[0]

        on_time_rate = _pct(metrics.on_time_submissions, metrics.total_assignments)
        overall = round(metrics.overall_performance_score, 2)
        eligible = attendance.status == "Eligible"
        grade, letter = _grade_and_letter(overall)
        status = _readiness(overall, eligible)

        dimensions = self._dimensions(metrics, student.cgpa, on_time_rate)
        tier = _tier_from_score(overall, eligible, interview.overall_score)
        lagging = self._lagging_areas(dimensions, topic_avgs, weakest, on_time_rate, data)
        weakness = self._weakness_analysis(data, dimensions, questions, weakest, lagging, on_time_rate)
        skill_graph = self._skill_graph(data, topic_avgs, overall, status)
        early_warning = self._early_warning(data, topic_avgs, weakness, on_time_rate, overall)
        what_if = self._what_if_scenario(data, topic_avgs, overall)
        headline = (
            f"{student.name} is {tier.label} ({tier.title}) at {overall:.2f}% — "
            f"{grade} ({letter}), {status.lower()}, with {strongest} leading and {weakest} lagging"
        )

        return StudentPerformanceReport(
            report_id=self._report_id(student.student_id, overall),
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            student_id=student.student_id,
            student_name=student.name,
            headline=headline,
            executive_summary=self._executive_summary(
                data, overall, grade, status, q_avg, strongest, weakest, on_time_rate, tier
            ),
            overall_performance=OverallPerformance(
                score=overall,
                grade=grade,
                letter=letter,
                status=status,
                headline=f"{grade} ({letter}) at {overall:.2f}% — {status} · {tier.label}",
            ),
            performance_tier=tier,
            dimension_scores=dimensions,
            interview_deep_dive=self._interview_deep_dive(
                data, q_avg, strongest, weakest, topic_avgs
            ),
            academic_snapshot=self._academic_snapshot(data, on_time_rate),
            attendance_snapshot=self._attendance_snapshot(data),
            strengths=self._strengths(data, dimensions, questions, on_time_rate),
            growth_areas=self._growth_areas(data, dimensions, questions, weakest, on_time_rate),
            weakness_analysis=weakness,
            lagging_areas=lagging,
            risk_flags=self._risk_flags(data, on_time_rate, q_scores),
            skill_graph=skill_graph,
            early_warning=early_warning,
            what_if_scenario=what_if,
            placement_readiness=self._placement_readiness(
                data, overall, status, eligible, strongest, weakest, on_time_rate
            ),
            action_plan=self._action_plan(dimensions, weakest, topic_avgs),
            study_plan=self._study_plan(tier, weakest, dimensions, topic_avgs, lagging),
            board_decision=self._board_decision(
                data, overall, status, eligible, tier, weakest, lagging
            ),
            scorecard=self._scorecard(data, overall, status, eligible, on_time_rate, tier),
            methodology_note=self._methodology_note(),
            counselor_recommendation=self._counselor_recommendation(
                data, status, strongest, weakest, overall, tier
            ),
            closing_note=self._closing_note(student.name, status, weakest, tier),
            meta=ReportMeta(engine=self.ENGINE, model=self.MODEL, strict_json=True),
        )

    # ── Sections ─────────────────────────────────────────────────────────────

    @staticmethod
    def _report_id(student_id: str, overall: float) -> str:
        seed = f"{student_id}:{overall}".encode("utf-8")
        digest = hashlib.sha256(seed).hexdigest()[:6].upper()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        return f"SPR-{student_id.upper()}-{stamp}-{digest}"

    @staticmethod
    def _topic_averages(questions) -> dict[str, float]:
        buckets: dict[str, list[int]] = {}
        for q in questions:
            buckets.setdefault(_infer_topic(q.question), []).append(q.score)
        if not buckets:
            return {DEFAULT_TOPIC: 0.0}
        return {t: round(sum(v) / len(v), 2) for t, v in buckets.items()}

    @staticmethod
    def _dimensions(metrics, cgpa: float, on_time_rate: float) -> list[DimensionScore]:
        interview_pct = round(metrics.interview_score * 10, 2)
        cgpa_pct = round(cgpa * 10, 2)

        return [
            DimensionScore(
                name="Interview Performance",
                score=interview_pct,
                band=_band(interview_pct),
                narrative=(
                    f"Interview panel scored {metrics.interview_score:.2f}/10, which carries the "
                    f"heaviest weight (40%) in the composite score."
                ),
            ),
            DimensionScore(
                name="Assignment Discipline",
                score=round(metrics.assignment_average, 2),
                band=_band(metrics.assignment_average),
                narrative=(
                    f"Assignment average is {metrics.assignment_average:.2f}% across "
                    f"{metrics.total_assignments} submission(s), with "
                    f"{metrics.on_time_submissions} delivered on time ({on_time_rate:.2f}%)."
                ),
            ),
            DimensionScore(
                name="Assessment Command",
                score=round(metrics.assessment_average, 2),
                band=_band(metrics.assessment_average),
                narrative=(
                    f"Assessment average is {metrics.assessment_average:.2f}% across "
                    f"{metrics.total_assessments} assessment(s), measuring retention under exam timing."
                ),
            ),
            DimensionScore(
                name="Attendance & Discipline",
                score=round(metrics.attendance_score, 2),
                band=_band(metrics.attendance_score),
                narrative=(
                    f"Attendance stands at {metrics.attendance_score:.2f}%, which most placement "
                    f"cells treat as a hard eligibility gate rather than a soft signal."
                ),
            ),
            DimensionScore(
                name="Academic Standing",
                score=cgpa_pct,
                band=_band(cgpa_pct),
                narrative=(
                    f"CGPA of {cgpa:.2f}/10 maps to {cgpa_pct:.2f}% and clears the 7.0 CGPA "
                    f"screening filter used by most recruiters."
                    if cgpa >= 7.0 else
                    f"CGPA of {cgpa:.2f}/10 maps to {cgpa_pct:.2f}% and sits below the 7.0 CGPA "
                    f"screening filter that many recruiters apply before interviews."
                ),
            ),
        ]

    @staticmethod
    def _executive_summary(
        data: ReportInputs,
        overall: float,
        grade: str,
        status: str,
        q_avg: float,
        strongest: str,
        weakest: str,
        on_time_rate: float,
        tier: PerformanceTier,
    ) -> str:
        student = data.student
        interview = data.interview
        metrics = data.metrics
        attendance = data.attendance

        para_1 = (
            f"{student.name} ({student.student_id}, {student.department}, semester "
            f"{student.semester}) posts a composite score of {overall:.2f}%, graded {grade}, "
            f"classified as {tier.label} — {tier.title}, with standing {status}. The composite "
            f"is weighted 40% interview, 30% assignments, 20% assessments and 10% attendance."
        )
        para_2 = (
            f"The {interview.company} interview for {interview.job_role} returned "
            f"{interview.overall_score:.2f}/10 with a per-question average of {q_avg:.2f}/10. "
            f"{strongest} is the strongest area on the transcript; {weakest} is the weakest and "
            f"is the single highest-leverage fix available."
        )
        para_3 = (
            f"Academically the assignment average is {metrics.assignment_average:.2f}% at "
            f"{on_time_rate:.2f}% on-time delivery and the assessment average is "
            f"{metrics.assessment_average:.2f}%. Attendance for {attendance.month} is "
            f"{attendance.attendance_percentage:.2f}% "
            f"({attendance.present_days}/{attendance.working_days} days), status "
            f"{attendance.status}."
        )
        return f"{para_1}\n\n{para_2}\n\n{para_3}"

    @staticmethod
    def _interview_deep_dive(
        data: ReportInputs,
        q_avg: float,
        strongest: str,
        weakest: str,
        topic_avgs: dict[str, float],
    ) -> InterviewDeepDive:
        interview = data.interview

        insights: list[QuestionInsight] = []
        for q in interview.questions:
            topic = _infer_topic(q.question)
            verdict = _verdict(q.score)
            if q.score >= 9:
                note = (
                    f"Bank this answer as a reference response for {topic}; it is already at "
                    f"panel standard at {q.score}/10."
                )
            elif q.score >= 8:
                note = (
                    f"Solid at {q.score}/10. Add one concrete example or metric to push this "
                    f"{topic} answer to a 9 or 10."
                )
            elif q.score >= 6:
                note = (
                    f"Passable at {q.score}/10 but thin. Rebuild the {topic} answer around a "
                    f"definition, an example and a trade-off."
                )
            else:
                note = (
                    f"Priority repair at {q.score}/10. Relearn {topic} from fundamentals, then "
                    f"re-answer this exact question on camera until it is fluent."
                )
            insights.append(
                QuestionInsight(
                    question=q.question,
                    score=q.score,
                    topic=topic,
                    verdict=verdict,
                    coaching_note=note,
                )
            )

        observations = [
            TraitRating(trait=trait.replace("_", " ").title(), rating=rating)
            for trait, rating in interview.interviewer_observation.items()
        ]

        spread = ""
        if len(topic_avgs) > 1:
            spread = (
                f" Topic averages range from {min(topic_avgs.values()):.2f}/10 ({weakest}) to "
                f"{max(topic_avgs.values()):.2f}/10 ({strongest})."
            )

        narrative = (
            f"The {interview.company} panel scored {interview.job_role} candidacy at "
            f"{interview.overall_score:.2f}/10 on {interview.interview_date.isoformat()}, "
            f"across {len(interview.questions)} questions averaging {q_avg:.2f}/10.{spread} "
            f"Closing the {weakest} gap is worth more than polishing {strongest} further."
        )

        return InterviewDeepDive(
            company=interview.company,
            role=interview.job_role,
            interview_date=interview.interview_date.isoformat(),
            overall_score=interview.overall_score,
            question_average=q_avg,
            strongest_topic=strongest,
            weakest_topic=weakest,
            questions=insights,
            observations=observations,
            narrative=narrative,
        )

    @staticmethod
    def _academic_snapshot(data: ReportInputs, on_time_rate: float) -> AcademicSnapshot:
        metrics = data.metrics
        items: list[AcademicItem] = []

        for a in data.assignment.assignments:
            percent = _pct(a.marks, a.max_marks)
            detail = f"{a.marks}/{a.max_marks} marks, submitted {a.submission_status.lower()}"
            if a.feedback:
                detail += f". Reviewer noted: {a.feedback}"
            items.append(
                AcademicItem(
                    id=a.assignment_id,
                    title=a.title,
                    subject=a.subject,
                    percent=percent,
                    detail=detail,
                )
            )

        for s in data.assessment.assessments:
            items.append(
                AcademicItem(
                    id=s.assessment_id,
                    title=f"{s.subject} Assessment",
                    subject=s.subject,
                    percent=round(s.score, 2),
                    detail=f"Scored {s.score:.2f}%, graded {s.grade}",
                )
            )

        late = metrics.total_assignments - metrics.on_time_submissions
        punctuality = (
            f"all {metrics.total_assignments} submission(s) landed on time"
            if late == 0 else
            f"{late} of {metrics.total_assignments} submission(s) were late or pending"
        )
        narrative = (
            f"CGPA is {data.student.cgpa:.2f}/10. Assignments average "
            f"{metrics.assignment_average:.2f}% and assessments average "
            f"{metrics.assessment_average:.2f}%, and {punctuality} "
            f"({on_time_rate:.2f}% on-time rate). "
            f"Coursework volume is {metrics.total_assignments} assignment(s) and "
            f"{metrics.total_assessments} assessment(s), so each new score moves the average "
            f"significantly."
        )

        return AcademicSnapshot(
            cgpa=data.student.cgpa,
            assignment_average=round(metrics.assignment_average, 2),
            assessment_average=round(metrics.assessment_average, 2),
            on_time_rate=on_time_rate,
            items=items,
            narrative=narrative,
        )

    @staticmethod
    def _attendance_snapshot(data: ReportInputs) -> AttendanceSnapshot:
        att = data.attendance
        if att.attendance_percentage >= 90.0:
            verdict = "comfortably clears the 75% eligibility bar and needs no intervention"
        elif att.attendance_percentage >= 75.0:
            verdict = "clears the 75% eligibility bar but has little margin left"
        else:
            verdict = "sits below the 75% eligibility bar and blocks placement drives"

        narrative = (
            f"{att.month}: {att.present_days} present, {att.absent_days} absent and "
            f"{att.leave_days} on leave out of {att.working_days} working days, giving "
            f"{att.attendance_percentage:.2f}%. Status is {att.status}, which {verdict}."
        )
        return AttendanceSnapshot(
            month=att.month,
            percentage=att.attendance_percentage,
            present_days=att.present_days,
            working_days=att.working_days,
            status=att.status,
            narrative=narrative,
        )

    @staticmethod
    def _strengths(
        data: ReportInputs,
        dimensions: list[DimensionScore],
        questions,
        on_time_rate: float,
    ) -> list[EvidencePoint]:
        points: list[EvidencePoint] = []

        top_questions = sorted(questions, key=lambda q: (-q.score, q.question))[:2]
        for q in top_questions:
            if q.score < 8:
                continue
            points.append(
                EvidencePoint(
                    title=f"{_infer_topic(q.question)} is interview-ready",
                    evidence=f'"{q.question}" scored {q.score}/10 with panel feedback: '
                             f'{q.feedback or "no written feedback"}',
                    impact="high",
                    why_it_matters=(
                        f"A {q.score}/10 answer means this topic can be led with confidently in "
                        f"the opening minutes of a technical round."
                    ),
                )
            )

        for dim in sorted(dimensions, key=lambda d: -d.score):
            if dim.score < 85.0 or len(points) >= 4:
                continue
            points.append(
                EvidencePoint(
                    title=f"{dim.name} is a differentiator",
                    evidence=f"{dim.name} measured at {dim.score:.2f}% (band: {dim.band})",
                    impact="high" if dim.score >= 90 else "medium",
                    why_it_matters=(
                        f"Recruiters screen on this dimension early, and {dim.score:.2f}% "
                        f"clears the filter without discussion."
                    ),
                )
            )

        if on_time_rate == 100.0 and data.metrics.total_assignments > 0:
            points.append(
                EvidencePoint(
                    title="Perfect submission punctuality",
                    evidence=f"{data.metrics.on_time_submissions}/"
                             f"{data.metrics.total_assignments} assignments submitted on time",
                    impact="medium",
                    why_it_matters=(
                        "Deadline reliability is the closest academic proxy to on-the-job "
                        "delivery discipline, and it is directly citable in interviews."
                    ),
                )
            )

        for label in data.interview.strengths:
            if len(points) >= 5:
                break
            points.append(
                EvidencePoint(
                    title=label,
                    evidence=f'Panel at {data.interview.company} recorded this as a strength '
                             f'alongside an overall {data.interview.overall_score:.2f}/10',
                    impact="medium",
                    why_it_matters=(
                        f"Named panel strengths are the safest talking points to repeat in the "
                        f"next {data.interview.job_role} interview."
                    ),
                )
            )

        # Schema floor is 2; guarantee it even for a weak record.
        while len(points) < 2:
            dim = sorted(dimensions, key=lambda d: -d.score)[len(points)]
            points.append(
                EvidencePoint(
                    title=f"{dim.name} is the strongest available base",
                    evidence=f"{dim.name} measured at {dim.score:.2f}% (band: {dim.band})",
                    impact="low",
                    why_it_matters=(
                        "Even a modest high point is the correct place to anchor a recovery "
                        "plan, because progress compounds fastest from existing competence."
                    ),
                )
            )
        return points

    @staticmethod
    def _growth_areas(
        data: ReportInputs,
        dimensions: list[DimensionScore],
        questions,
        weakest: str,
        on_time_rate: float,
    ) -> list[EvidencePoint]:
        points: list[EvidencePoint] = []

        for q in sorted(questions, key=lambda q: (q.score, q.question))[:2]:
            if q.score >= 9:
                continue
            points.append(
                EvidencePoint(
                    title=f"{_infer_topic(q.question)} needs rebuilding",
                    evidence=f'"{q.question}" scored {q.score}/10. Answer given: '
                             f'"{q.student_answer}"',
                    impact="high" if q.score < 7 else "medium",
                    why_it_matters=(
                        f"This is the lowest-scoring answer on the transcript, so it is the "
                        f"cheapest place to add points before the next round."
                    ),
                )
            )

        for dim in sorted(dimensions, key=lambda d: d.score):
            if dim.score >= 75.0 or len(points) >= 4:
                continue
            points.append(
                EvidencePoint(
                    title=f"{dim.name} is dragging the composite",
                    evidence=f"{dim.name} measured at {dim.score:.2f}% (band: {dim.band})",
                    impact="high" if dim.score < 60 else "medium",
                    why_it_matters=(
                        f"At {dim.score:.2f}% this dimension pulls the weighted composite down "
                        f"more than any single interview answer does."
                    ),
                )
            )

        if on_time_rate < 100.0 and data.metrics.total_assignments > 0:
            late = data.metrics.total_assignments - data.metrics.on_time_submissions
            points.append(
                EvidencePoint(
                    title="Submission punctuality is leaking marks",
                    evidence=f"{late} of {data.metrics.total_assignments} assignment(s) were "
                             f"late or pending ({on_time_rate:.2f}% on-time rate)",
                    impact="medium",
                    why_it_matters=(
                        "Late submissions cost marks that were already earned and signal weak "
                        "delivery discipline to reviewers."
                    ),
                )
            )

        for label in data.interview.weaknesses:
            if len(points) >= 5:
                break
            points.append(
                EvidencePoint(
                    title=label,
                    evidence=f"Recorded as a weakness by the {data.interview.company} panel; "
                             f"transcript confirms {weakest} as the lowest-scoring topic",
                    impact="medium",
                    why_it_matters=(
                        "A weakness the panel wrote down will be probed again in the next "
                        "interview, so it must be closed rather than avoided."
                    ),
                )
            )

        # Schema floor is 1; a flawless record still gets a stretch target.
        if not points:
            weakest_dim = min(dimensions, key=lambda d: d.score)
            points.append(
                EvidencePoint(
                    title="No deficit found — set a stretch target",
                    evidence=f"Lowest dimension is still {weakest_dim.name} at "
                             f"{weakest_dim.score:.2f}% (band: {weakest_dim.band})",
                    impact="low",
                    why_it_matters=(
                        "With no remedial work outstanding, the next gain has to come from "
                        "depth beyond the syllabus rather than from fixing gaps."
                    ),
                )
            )
        return points

    @staticmethod
    def _topic_score_10(topic_avgs: dict[str, float], *names: str, default: float | None = 5.0) -> float | None:
        for name in names:
            if name in topic_avgs:
                return float(topic_avgs[name])
        return default

    @staticmethod
    def _clamp_score(value: float) -> float:
        return round(max(0.0, min(100.0, value)), 2)

    @staticmethod
    def _node_health(score: float, limits_downstream: bool) -> str:
        if score < 55.0 and limits_downstream:
            return "blocking"
        if score < 70.0:
            return "watch"
        return "healthy"

    @staticmethod
    def _edge_strength(source_score: float, target_score: float) -> str:
        if source_score < 55.0 or source_score + 12.0 < target_score:
            return "fragile"
        if source_score < 70.0:
            return "adequate"
        return "strong"

    @classmethod
    def _infer_core_language(cls, data: ReportInputs, topic_avgs: dict[str, float]) -> tuple[str, float, str]:
        """Pick the student's real language track from interview evidence."""
        blob = " ".join(
            q.question.lower() + " " + (q.student_answer or "").lower()
            for q in data.interview.questions
        )
        dept = (data.student.department or "").lower()
        py_hits = sum(1 for k in ("python", "fastapi", "django", "flask", "pandas") if k in blob)
        java_hits = sum(1 for k in ("java", "spring", "jvm", "hibernate") if k in blob)
        js_hits = sum(1 for k in ("javascript", "typescript", "node.js", "react", "express") if k in blob)
        soft = float(data.metrics.interview_score)
        py_score = cls._topic_score_10(topic_avgs, "Python Fundamentals", default=None)

        if java_hits > py_hits and java_hits >= js_hits:
            oop = cls._topic_score_10(topic_avgs, "OOP & Design", default=soft) or soft
            score = cls._clamp_score(((oop + soft) / 2) * 10)
            return "Java", score, f"Interview language cues ({java_hits}) + OOP proxy {oop:.1f}/10"
        if js_hits > py_hits and js_hits > java_hits:
            web = cls._topic_score_10(topic_avgs, "Web & APIs", default=soft) or soft
            score = cls._clamp_score(((web + soft) / 2) * 10)
            return "JavaScript", score, f"Interview language cues ({js_hits}) + Web/API proxy {web:.1f}/10"
        if py_score is not None:
            return "Python", cls._clamp_score(py_score * 10), f"Python Fundamentals topic average {py_score:.1f}/10"
        if "cse" in dept or "computer" in dept or py_hits >= 1:
            score = cls._clamp_score(soft * 10 * 0.92)
            return "Python", score, f"Department/interview proxy from panel overall {soft:.1f}/10"
        score = cls._clamp_score(soft * 10 * 0.9)
        return "Core language", score, f"Inferred from interview overall {soft:.1f}/10"

    @classmethod
    def _skill_graph(
        cls,
        data: ReportInputs,
        topic_avgs: dict[str, float],
        overall: float,
        status: str,
    ) -> SkillGraph:
        """Build a realistic dependency graph with prerequisite capping."""
        soft = float(data.metrics.interview_score)
        lang_label, lang_raw, lang_evidence = cls._infer_core_language(data, topic_avgs)

        oop_t = cls._topic_score_10(topic_avgs, "OOP & Design", default=None)
        dsa_t = cls._topic_score_10(topic_avgs, "DSA & Problem Solving", default=None)
        sql_t = cls._topic_score_10(topic_avgs, "SQL & Databases", default=None)
        web_t = cls._topic_score_10(topic_avgs, "Web & APIs", default=None)
        comms_t = cls._topic_score_10(topic_avgs, "Behavioural & Comms", default=None)

        oop_raw = cls._clamp_score((oop_t if oop_t is not None else soft * 0.85) * 10)
        dsa_raw = cls._clamp_score((dsa_t if dsa_t is not None else soft * 0.8) * 10)
        sql_raw = cls._clamp_score((sql_t if sql_t is not None else soft * 0.82) * 10)
        web_raw = cls._clamp_score((web_t if web_t is not None else soft * 0.83) * 10)
        comms_raw = cls._clamp_score((comms_t if comms_t is not None else soft * 0.9) * 10)

        # Prerequisite physics: cannot outrun a weak foundation
        oop = cls._clamp_score(min(oop_raw, lang_raw * 0.92 + 10))
        dsa = cls._clamp_score(min(dsa_raw, lang_raw * 0.95 + 8))
        sql = cls._clamp_score(min(sql_raw, lang_raw * 0.9 + 12))
        backend = cls._clamp_score(min(web_raw, oop * 0.88 + 14, sql * 0.75 + 20))
        problem = cls._clamp_score(min(dsa * 0.75 + soft * 10 * 0.25, dsa * 0.95 + 8))
        delivery = cls._clamp_score(
            data.metrics.assignment_average * 0.7
            + data.attendance.attendance_percentage * 0.3
        )
        placement = cls._clamp_score(
            overall * 0.55
            + (backend + problem + comms_raw) / 3 * 0.35
            + (10.0 if data.attendance.status == "Eligible" else 0.0) * 0.1
        )
        if status == "Not Ready":
            gate = min(backend, problem, comms_raw, delivery if delivery < 75 else 100)
            placement = cls._clamp_score(min(placement, gate + 5, overall * 0.9))

        def _ev_topic(name: str, raw_t: float | None, capped: float, raw_pct: float) -> str:
            if raw_t is None:
                base = f"No dedicated {name} answers — estimated from interview {soft:.1f}/10"
            else:
                base = f"{name} topic average {raw_t:.1f}/10"
            if abs(capped - raw_pct) > 1.5:
                return f"{base}; capped to {capped:.0f}% by weaker prerequisites"
            return f"{base} → {capped:.0f}%"

        nodes = [
            SkillNode(
                id="core_lang", label=lang_label, score=lang_raw, band=_band(lang_raw),
                layer="foundation", evidence=lang_evidence,
                health=cls._node_health(lang_raw, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="oop", label="OOP concepts", score=oop, band=_band(oop), layer="core",
                evidence=_ev_topic("OOP & Design", oop_t, oop, oop_raw),
                health=cls._node_health(oop, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="dsa", label="DSA", score=dsa, band=_band(dsa), layer="core",
                evidence=_ev_topic("DSA & Problem Solving", dsa_t, dsa, dsa_raw),
                health=cls._node_health(dsa, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="sql", label="SQL & data", score=sql, band=_band(sql), layer="core",
                evidence=_ev_topic("SQL & Databases", sql_t, sql, sql_raw),
                health=cls._node_health(sql, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="backend", label="Backend / APIs", score=backend, band=_band(backend),
                layer="applied", evidence=_ev_topic("Web & APIs", web_t, backend, web_raw),
                health=cls._node_health(backend, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="problem_solving", label="Problem solving", score=problem, band=_band(problem),
                layer="applied",
                evidence=f"Blend of DSA {dsa:.0f}% and interview {soft:.1f}/10",
                health=cls._node_health(problem, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="comms", label="Communication", score=comms_raw, band=_band(comms_raw),
                layer="applied", evidence=_ev_topic("Behavioural & Comms", comms_t, comms_raw, comms_raw),
                health=cls._node_health(comms_raw, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="delivery", label="Delivery & attendance", score=delivery, band=_band(delivery),
                layer="applied",
                evidence=(
                    f"Assignments {data.metrics.assignment_average:.0f}% · "
                    f"attendance {data.attendance.attendance_percentage:.0f}% ({data.attendance.status})"
                ),
                health=cls._node_health(delivery, True),  # type: ignore[arg-type]
            ),
            SkillNode(
                id="placement", label="Placement", score=placement, band=_band(placement),
                layer="outcome",
                evidence=f"Composite {overall:.1f}% gated by Backend / Problem solving / Comms / Delivery",
                health=cls._node_health(placement, False),  # type: ignore[arg-type]
            ),
        ]
        by_id = {n.id: n for n in nodes}

        edge_defs = [
            ("core_lang", "oop", "unlocks"),
            ("core_lang", "dsa", "unlocks"),
            ("core_lang", "sql", "unlocks"),
            ("oop", "backend", "feeds"),
            ("sql", "backend", "feeds"),
            ("dsa", "problem_solving", "feeds"),
            ("backend", "placement", "gates"),
            ("problem_solving", "placement", "gates"),
            ("comms", "placement", "gates"),
            ("delivery", "placement", "gates"),
        ]
        edges = [
            SkillEdge(
                source=src, target=tgt, relation=rel,
                strength=cls._edge_strength(by_id[src].score, by_id[tgt].score),  # type: ignore[arg-type]
            )
            for src, tgt, rel in edge_defs
        ]

        children: dict[str, list[str]] = {}
        for e in edges:
            children.setdefault(e.source, []).append(e.target)

        def _descendants(nid: str, seen: set[str] | None = None) -> set[str]:
            seen = seen or set()
            for c in children.get(nid, []):
                if c not in seen:
                    seen.add(c)
                    _descendants(c, seen)
            return seen

        candidates = [n for n in nodes if n.id != "placement" and _descendants(n.id)]
        blocking = [n for n in candidates if n.health == "blocking"]
        watching = [n for n in candidates if n.score < 75.0]
        pool = blocking or watching or candidates
        pool.sort(key=lambda n: (n.score, -len(_descendants(n.id))))
        bottleneck = pool[0]
        down_ids = sorted(_descendants(bottleneck.id))
        down_count = len(down_ids)
        label_by_id = {n.id: n.label for n in nodes}
        down_labels = ", ".join(label_by_id.get(i, i) for i in down_ids if i != "placement")
        fragile = [e for e in edges if e.strength == "fragile" and e.source == bottleneck.id]
        fragile_note = ""
        if fragile:
            fragile_note = (
                f" Fragile links from {bottleneck.label}: "
                + ", ".join(f"→ {label_by_id[e.target]}" for e in fragile)
                + "."
            )
        down_bit = f" ({down_labels}, Placement)" if down_labels else " (toward Placement)"
        plural = "s" if down_count != 1 else ""
        insight = (
            f"Improving {bottleneck.label} is likely to improve performance in "
            f"{down_count} downstream area{plural}{down_bit}. "
            f"Current {bottleneck.label} sits at {bottleneck.score:.0f}% ({bottleneck.band})"
            f" — {bottleneck.evidence}.{fragile_note}"
        )

        return SkillGraph(
            root_skill=lang_label,
            nodes=nodes,
            edges=edges,
            bottleneck_skill=bottleneck.label,
            downstream_count=down_count,
            insight=insight,
        )

    @classmethod
    def _early_warning(
        cls,
        data: ReportInputs,
        topic_avgs: dict[str, float],
        weakness: WeaknessAnalysis,
        on_time_rate: float,
        overall: float,
    ) -> EarlyWarning:
        """Infer trajectory pressure from gaps vs healthy placement bands."""
        signals: list[WarningSignal] = []
        att = data.attendance.attendance_percentage
        asg = data.metrics.assignment_average
        iv = data.metrics.interview_score
        dsa = cls._topic_score_10(topic_avgs, "DSA & Problem Solving")
        healthy_att, healthy_asg, healthy_iv, healthy_dsa = 85.0, 80.0, 7.5, 7.0

        if att < healthy_att:
            delta = round(healthy_att - att, 1)
            signals.append(
                WarningSignal(
                    metric="Attendance",
                    direction="down",
                    delta_label=f"↓ {delta}% vs healthy band ({healthy_att:.0f}%)",
                    detail=f"Recorded {att:.1f}% — eligibility floor is 75%; healthy drive band is {healthy_att:.0f}%.",
                )
            )
        if asg < healthy_asg:
            delta = round(healthy_asg - asg, 1)
            signals.append(
                WarningSignal(
                    metric="Assignments",
                    direction="down",
                    delta_label=f"↓ {delta}% vs healthy band ({healthy_asg:.0f}%)",
                    detail=f"Assignment average {asg:.1f}% with on-time rate {on_time_rate:.0f}%.",
                )
            )
        if on_time_rate < 90.0:
            signals.append(
                WarningSignal(
                    metric="Delivery rhythm",
                    direction="down",
                    delta_label=f"↓ {round(100.0 - on_time_rate, 1)}% on-time gap",
                    detail="Late or pending submissions signal disengagement before marks fully collapse.",
                )
            )
        if iv < healthy_iv:
            signals.append(
                WarningSignal(
                    metric="Interview confidence",
                    direction="down",
                    delta_label=f"↓ {round(healthy_iv - iv, 1)} pts vs {healthy_iv}/10 target",
                    detail=f"Panel overall {iv:.1f}/10 — below the competitive mock threshold.",
                )
            )
        if dsa < healthy_dsa:
            signals.append(
                WarningSignal(
                    metric="DSA performance",
                    direction="down",
                    delta_label=f"↓ {round(healthy_dsa - dsa, 1)} pts vs {healthy_dsa:.0f}/10",
                    detail=f"DSA topic average {dsa:.1f}/10 — product company filters will reject early.",
                )
            )

        if not signals:
            return EarlyWarning(
                active=False,
                severity="clear",
                title="No early warning",
                signals=[],
                predicted_issue="Trajectory within healthy placement bands",
                recommended_intervention="Maintain current cadence; schedule a light 2-week mock refresh before peak drive season.",
                trajectory_summary=(
                    f"Composite {overall:.1f}% and interview {iv:.1f}/10 sit inside healthy bands. "
                    f"Continue monitoring attendance and DSA so the path does not reverse unnoticed."
                ),
            )

        # Cluster → predicted issue
        metrics_hit = {s.metric for s in signals}
        if {"DSA performance", "Interview confidence"} & metrics_hit and (
            "Assignments" in metrics_hit or "Delivery rhythm" in metrics_hit
        ):
            predicted = "Technical preparation disengagement"
            intervention = (
                "2-week DSA recovery program: daily 90-minute problem sets (arrays → hashing → "
                "two pointers), 3 timed mocks, and counselor check-in on day 7 and day 14."
            )
        elif "Attendance" in metrics_hit and ("Assignments" in metrics_hit or "Delivery rhythm" in metrics_hit):
            predicted = "Academic engagement slip before placement season"
            intervention = (
                "1-week attendance recovery + assignment catch-up: restore ≥85% attendance, "
                "clear pending submissions, then resume technical drills."
            )
        elif "Interview confidence" in metrics_hit:
            predicted = "Interview readiness lag"
            intervention = (
                "10-day interview bootcamp: 2 mocks/week, topic drills on weakest answers, "
                "and a recorded STAR story practice for behavioural rounds."
            )
        elif "DSA performance" in metrics_hit:
            predicted = "DSA filter risk for product companies"
            intervention = (
                "2-week DSA recovery program focused on patterns that appear in first-round screens."
            )
        else:
            predicted = weakness.pattern or "Multi-signal placement risk"
            intervention = (
                f"Targeted 2-week sprint on {weakness.primary_weakness}: daily practice, "
                f"one mock, and a counselor review at the end of week two."
            )

        critical_hits = sum(
            1
            for s in signals
            if s.metric in ("Attendance", "DSA performance", "Interview confidence")
        )
        if len(signals) >= 4 or (data.attendance.status == "Not Eligible"):
            severity = "critical"
            title = "EARLY WARNING — critical trajectory"
        elif critical_hits >= 2 or len(signals) >= 3:
            severity = "elevated"
            title = "EARLY WARNING"
        else:
            severity = "watch"
            title = "EARLY WATCH"

        summary = (
            f"{len(signals)} trajectory signal(s) fired before drive season. "
            f"Pattern: {weakness.pattern}. Predicted issue: {predicted}. "
            f"Intervene now — waiting for the outcome score will be too late."
        )

        return EarlyWarning(
            active=True,
            severity=severity,  # type: ignore[arg-type]
            title=title,
            signals=signals,
            predicted_issue=predicted,
            recommended_intervention=intervention,
            trajectory_summary=summary,
        )

    @classmethod
    def _readiness_from_levers(
        cls,
        interview: float,
        assignments: float,
        attendance: float,
        dsa: float,
        communication: float,
    ) -> float:
        """Placement readiness % used by what-if (report + live simulator)."""
        score = (
            interview * 10 * 0.30
            + assignments * 0.25
            + attendance * 0.10
            + dsa * 10 * 0.20
            + communication * 10 * 0.15
        )
        if attendance < 75.0:
            score = min(score, 45.0)
        return round(max(0.0, min(100.0, score)), 2)

    @classmethod
    def _what_if_scenario(
        cls,
        data: ReportInputs,
        topic_avgs: dict[str, float],
        overall: float,
    ) -> WhatIfScenario:
        iv = float(data.metrics.interview_score)
        asg = float(data.metrics.assignment_average)
        att = float(data.attendance.attendance_percentage)
        dsa = float(cls._topic_score_10(topic_avgs, "DSA & Problem Solving") or 5.0)
        comms = float(cls._topic_score_10(topic_avgs, "Behavioural & Comms") or 5.0)

        levers_current = {
            "interview": iv,
            "assignments": asg,
            "attendance": att,
            "dsa": dsa,
            "communication": comms,
        }
        levers_rec = {
            "interview": max(iv, 7.5),
            "assignments": max(asg, 85.0),
            "attendance": max(att, 85.0),
            "dsa": max(dsa, 7.0),
            "communication": max(comms, 8.0),
        }

        current = cls._readiness_from_levers(iv, asg, att, dsa, comms)
        simulated = cls._readiness_from_levers(
            levers_rec["interview"],
            levers_rec["assignments"],
            levers_rec["attendance"],
            levers_rec["dsa"],
            levers_rec["communication"],
        )
        delta = round(simulated - current, 2)

        # Largest drivers = levers with biggest readiness contribution from the lift
        contrib: list[tuple[float, str]] = []
        labels = {
            "interview": "Interview",
            "assignments": "Assignments",
            "attendance": "Attendance",
            "dsa": "DSA",
            "communication": "Communication",
        }
        weights = {
            "interview": 10 * 0.30,
            "assignments": 0.25,
            "attendance": 0.10,
            "dsa": 10 * 0.20,
            "communication": 10 * 0.15,
        }
        for key, label in labels.items():
            lift = (levers_rec[key] - levers_current[key]) * weights[key]
            if lift > 0.05:
                contrib.append((lift, label))
        contrib.sort(reverse=True)
        drivers = [name for _, name in contrib[:2]] or ["Maintain current levels"]

        lever_models = [
            WhatIfLever(
                key="attendance",
                label="Attendance",
                current=round(att, 2),
                unit="percent",
                recommended=round(levers_rec["attendance"], 2),
                min_value=0,
                max_value=100,
            ),
            WhatIfLever(
                key="interview",
                label="Interview",
                current=round(iv, 2),
                unit="score10",
                recommended=round(levers_rec["interview"], 2),
                min_value=0,
                max_value=10,
            ),
            WhatIfLever(
                key="assignments",
                label="Assignments",
                current=round(asg, 2),
                unit="percent",
                recommended=round(levers_rec["assignments"], 2),
                min_value=0,
                max_value=100,
            ),
            WhatIfLever(
                key="dsa",
                label="DSA",
                current=round(dsa, 2),
                unit="score10",
                recommended=round(levers_rec["dsa"], 2),
                min_value=0,
                max_value=10,
            ),
            WhatIfLever(
                key="communication",
                label="Communication",
                current=round(comms, 2),
                unit="score10",
                recommended=round(levers_rec["communication"], 2),
                min_value=0,
                max_value=10,
            ),
        ]

        narrative = (
            f"Current placement readiness is {current:.0f}%. Under the recommended lever targets, "
            f"simulated readiness rises to {simulated:.0f}% (delta {delta:+.1f}). "
            f"Largest improvement driver: {' + '.join(drivers)}."
        )
        if overall:
            # keep overall in the story for counselors without conflicting numbers
            narrative += f" Pipeline composite today is {overall:.1f}% for cross-check."

        return WhatIfScenario(
            current_readiness=current,
            simulated_readiness=simulated,
            delta=delta,
            largest_drivers=drivers,
            levers=lever_models,
            narrative=narrative,
            formula_note=(
                "Readiness = Interview×10×0.30 + Assignments×0.25 + Attendance×0.10 + "
                "DSA×10×0.20 + Communication×10×0.15; attendance <75% caps readiness at 45%."
            ),
        )

    @staticmethod
    def _risk_flags(data: ReportInputs, on_time_rate: float, q_scores: list[int]) -> list[str]:
        flags: list[str] = []
        att = data.attendance
        metrics = data.metrics

        if att.status == "Not Eligible":
            flags.append(
                f"ELIGIBILITY: attendance {att.attendance_percentage:.2f}% marks the student "
                f"Not Eligible, which blocks placement drives outright"
            )
        elif att.attendance_percentage < 80.0:
            flags.append(
                f"ATTENDANCE MARGIN: {att.attendance_percentage:.2f}% is within "
                f"{att.attendance_percentage - 75.0:.2f} points of losing eligibility"
            )

        if data.student.cgpa < 7.0:
            flags.append(
                f"CGPA FILTER: {data.student.cgpa:.2f}/10 falls below the 7.0 cutoff used by "
                f"many recruiters for resume shortlisting"
            )

        weak = [s for s in q_scores if s < 7]
        if weak:
            flags.append(
                f"INTERVIEW GAPS: {len(weak)} of {len(q_scores)} answers scored below 7/10 "
                f"(lowest {min(weak)}/10)"
            )

        if on_time_rate < 100.0 and metrics.total_assignments > 0:
            flags.append(
                f"DELIVERY: on-time submission rate is {on_time_rate:.2f}%, so marks are being "
                f"lost to timing rather than to knowledge"
            )

        if metrics.total_assignments <= 1 or metrics.total_assessments <= 1:
            flags.append(
                f"THIN SAMPLE: only {metrics.total_assignments} assignment(s) and "
                f"{metrics.total_assessments} assessment(s) on record, so averages are volatile "
                f"and should not be over-read"
            )
        return flags

    @staticmethod
    def _placement_readiness(
        data: ReportInputs,
        overall: float,
        status: str,
        eligible: bool,
        strongest: str,
        weakest: str,
        on_time_rate: float,
    ) -> PlacementReadiness:
        interview = data.interview

        confidence = overall
        if not eligible:
            confidence -= 25.0
        if data.student.cgpa < 7.0:
            confidence -= 10.0
        if on_time_rate < 100.0:
            confidence -= 5.0
        confidence = round(max(0.0, min(100.0, confidence)), 2)

        roles = [interview.job_role]
        role_map = {
            "Web & APIs": "Backend Developer (Python/FastAPI)",
            "Machine Learning": "ML / Data Science Intern",
            "Python Fundamentals": "Python Developer",
            "OOP & Design": "Software Development Engineer",
            "SQL & Databases": "Data Engineer",
            "DSA & Problem Solving": "Product-Based SDE",
        }
        extra = role_map.get(strongest)
        if extra and extra not in roles:
            roles.append(extra)
        if len(roles) < 2:
            roles.append("Graduate Software Engineer")

        if status == "Placement Ready":
            fit = [
                "Service-based mass recruiters — clears screening comfortably",
                "Mid-size product companies — competitive with targeted DSA prep",
            ]
        elif status == "Almost Ready":
            fit = [
                "Service-based mass recruiters — realistic near-term target",
                f"Product-based companies — viable once {weakest} is closed",
            ]
        else:
            fit = [
                "Internships and training-linked hiring — best current fit",
                "Service-based recruiters — reachable after one preparation cycle",
            ]

        blockers: list[str] = []
        if not eligible:
            blockers.append(
                f"Attendance status {data.attendance.status} at "
                f"{data.attendance.attendance_percentage:.2f}% must be cleared before any drive"
            )
        blockers.append(f"{weakest} is the lowest-scoring interview topic and will be re-probed")
        if data.student.cgpa < 7.0:
            blockers.append(f"CGPA {data.student.cgpa:.2f} below the common 7.0 shortlisting cutoff")
        if on_time_rate < 100.0:
            blockers.append(f"On-time submission rate of {on_time_rate:.2f}% weakens the discipline story")

        narrative = (
            f"Composite {overall:.2f}% with a {interview.overall_score:.2f}/10 interview puts "
            f"{data.student.name} at {status} with {confidence:.2f}% confidence. {strongest} "
            f"is strong enough to anchor a technical round today, while {weakest} remains the "
            f"blocker that decides product-company outcomes. Attendance status is "
            f"{data.attendance.status}."
        )

        return PlacementReadiness(
            status=status,
            confidence=confidence,
            target_roles=roles,
            company_fit=fit,
            blockers=blockers,
            narrative=narrative,
        )

    @staticmethod
    def _action_plan(
        dimensions: list[DimensionScore],
        weakest_topic: str,
        topic_avgs: dict[str, float],
    ) -> list[ActionItem]:
        # Rank targets by weakness: worst interview topic first, then weakest dimensions.
        targets: list[str] = [weakest_topic]
        for dim in sorted(dimensions, key=lambda d: d.score):
            if dim.name not in targets:
                targets.append(dim.name)
        for topic, _ in sorted(topic_avgs.items(), key=lambda kv: kv[1]):
            if topic not in targets:
                targets.append(topic)

        plan: list[ActionItem] = []
        for index, timeframe in enumerate(TIMEFRAMES):
            key = targets[index] if index < len(targets) else None
            skill, action, metric = ACTION_TEMPLATES.get(
                key, STRETCH_ACTION if index == len(TIMEFRAMES) - 1 else FALLBACK_ACTION
            )
            plan.append(
                ActionItem(
                    priority=index + 1,
                    timeframe=timeframe,
                    skill=skill,
                    action=action,
                    success_metric=metric,
                )
            )
        return plan

    @staticmethod
    def _lagging_areas(
        dimensions: list[DimensionScore],
        topic_avgs: dict[str, float],
        weakest: str,
        on_time_rate: float,
        data: ReportInputs,
    ) -> list[LaggingArea]:
        areas: list[LaggingArea] = []

        # Interview topics below target (scale 0–10 → 0–100).
        for topic, avg in sorted(topic_avgs.items(), key=lambda kv: kv[1]):
            score = round(avg * 10, 2)
            gap = round(max(0.0, TARGET_SCORE - score), 2)
            if gap <= 0 and topic != weakest:
                continue
            if gap <= 0:
                gap = round(max(2.0, TARGET_SCORE - score), 2)
            areas.append(
                LaggingArea(
                    area=topic,
                    current_score=score,
                    target_score=TARGET_SCORE,
                    gap=gap,
                    severity=_severity(gap),
                    evidence=(
                        f"Interview topic average {avg:.2f}/10 "
                        f"({'lowest on transcript' if topic == weakest else 'below target'})"
                    ),
                    fix_hint=(
                        f"Drill {topic} with daily 45-minute practice and one recorded mock "
                        f"answer until the topic average reaches 8/10."
                    ),
                )
            )

        for dim in sorted(dimensions, key=lambda d: d.score):
            gap = round(max(0.0, TARGET_SCORE - dim.score), 2)
            if gap < 5.0:
                continue
            if any(a.area == dim.name for a in areas):
                continue
            areas.append(
                LaggingArea(
                    area=dim.name,
                    current_score=round(dim.score, 2),
                    target_score=TARGET_SCORE,
                    gap=gap,
                    severity=_severity(gap),
                    evidence=f"{dim.name} at {dim.score:.2f}% (band: {dim.band})",
                    fix_hint=(
                        ACTION_TEMPLATES.get(dim.name, FALLBACK_ACTION)[1]
                    ),
                )
            )

        if on_time_rate < 100.0 and data.metrics.total_assignments > 0:
            gap = round(100.0 - on_time_rate, 2)
            areas.append(
                LaggingArea(
                    area="Submission Punctuality",
                    current_score=round(on_time_rate, 2),
                    target_score=100.0,
                    gap=gap,
                    severity=_severity(gap),
                    evidence=(
                        f"On-time rate {on_time_rate:.2f}% across "
                        f"{data.metrics.total_assignments} assignment(s)"
                    ),
                    fix_hint=(
                        "Submit every assignment 24 hours early and log feedback the same day."
                    ),
                )
            )

        if not areas:
            weakest_dim = min(dimensions, key=lambda d: d.score)
            gap = round(max(5.0, TARGET_SCORE - weakest_dim.score), 2)
            areas.append(
                LaggingArea(
                    area=weakest_dim.name,
                    current_score=round(weakest_dim.score, 2),
                    target_score=TARGET_SCORE,
                    gap=gap,
                    severity="mild",
                    evidence=(
                        f"Lowest dimension is {weakest_dim.name} at {weakest_dim.score:.2f}%"
                    ),
                    fix_hint="Treat this as a stretch target — deepen beyond syllabus baseline.",
                )
            )

        # Keep the worst gaps first; cap for readability.
        areas.sort(key=lambda a: (-a.gap, a.area))
        return areas[:6]

    @staticmethod
    def _weakness_analysis(
        data: ReportInputs,
        dimensions: list[DimensionScore],
        questions,
        weakest: str,
        lagging: list[LaggingArea],
        on_time_rate: float,
    ) -> WeaknessAnalysis:
        items: list[WeaknessItem] = []

        for q in sorted(questions, key=lambda q: (q.score, q.question))[:3]:
            if q.score >= 8:
                continue
            topic = _infer_topic(q.question)
            severity = "critical" if q.score < 6 else "moderate" if q.score < 7 else "mild"
            items.append(
                WeaknessItem(
                    weakness=f"Thin {topic} answer on transcript",
                    root_cause=(
                        "Concept recall without a worked example or trade-off under panel pressure"
                        if q.score >= 6 else
                        "Fundamentals incomplete — answer lacks definition, example and edge case"
                    ),
                    evidence=f'"{q.question}" scored {q.score}/10',
                    severity=severity,
                    related_area=topic,
                )
            )

        for dim in sorted(dimensions, key=lambda d: d.score)[:2]:
            if dim.score >= 75.0:
                continue
            items.append(
                WeaknessItem(
                    weakness=f"{dim.name} below placement filter",
                    root_cause=(
                        "Weighted composite is pulled down by this dimension more than by any "
                        "single interview answer"
                    ),
                    evidence=f"{dim.name} at {dim.score:.2f}% (band: {dim.band})",
                    severity="critical" if dim.score < 60 else "moderate",
                    related_area=dim.name,
                )
            )

        for label in data.interview.weaknesses[:3]:
            if len(items) >= 6:
                break
            items.append(
                WeaknessItem(
                    weakness=label,
                    root_cause=f"Named by {data.interview.company} panel; aligns with {weakest}",
                    evidence=(
                        f"Panel weakness list; transcript lowest topic is {weakest}"
                    ),
                    severity="moderate",
                    related_area=weakest,
                )
            )

        if on_time_rate < 100.0 and data.metrics.total_assignments > 0:
            items.append(
                WeaknessItem(
                    weakness="Deadline discipline leaking earned marks",
                    root_cause="Late or pending submissions, not knowledge gaps",
                    evidence=f"On-time rate {on_time_rate:.2f}%",
                    severity="mild" if on_time_rate >= 80 else "moderate",
                    related_area="Assignment Discipline",
                )
            )

        if not items:
            lowest = lagging[0] if lagging else None
            items.append(
                WeaknessItem(
                    weakness="No critical deficit — stretch depth required",
                    root_cause="Scores clear filters; next gains need portfolio depth",
                    evidence=(
                        f"Lowest lagging area: {lowest.area} at {lowest.current_score:.2f}%"
                        if lowest else "All dimensions above target"
                    ),
                    severity="mild",
                    related_area=lowest.area if lowest else "Advanced Differentiation",
                )
            )

        primary = items[0].weakness
        critical_count = sum(1 for i in items if i.severity == "critical")
        if critical_count >= 2:
            pattern = (
                f"Multiple critical gaps cluster around {weakest} and low-scoring dimensions — "
                f"fix before broadening."
            )
        elif any(i.related_area == weakest for i in items):
            pattern = (
                f"Primary pattern: {weakest} underperforms under interview timing, while other "
                f"areas are closer to target."
            )
        else:
            pattern = (
                "Gaps are spread across delivery discipline and academic consistency rather than "
                "a single technical topic."
            )

        top_lag = lagging[0].area if lagging else weakest
        summary = (
            f"Weakness analysis for {data.student.name}: primary issue is '{primary}'. "
            f"The highest-leverage lagging area is {top_lag}. {len(items)} weakness item(s) "
            f"were extracted from interview scores, panel notes and dimension KPIs — close "
            f"these before the next placement cycle."
        )

        return WeaknessAnalysis(
            summary=summary,
            primary_weakness=primary,
            pattern=pattern,
            items=items[:6],
        )

    @staticmethod
    def _study_plan(
        tier: PerformanceTier,
        weakest: str,
        dimensions: list[DimensionScore],
        topic_avgs: dict[str, float],
        lagging: list[LaggingArea],
    ) -> RealWorldStudyPlan:
        # Rank focus skills: weakest topic, then worst dimensions / lagging areas.
        focuses: list[str] = [weakest]
        for area in lagging:
            if area.area not in focuses:
                focuses.append(area.area)
        for dim in sorted(dimensions, key=lambda d: d.score):
            if dim.name not in focuses:
                focuses.append(dim.name)

        phase_defs = (
            ("Days 1-7",  focuses[0] if focuses else weakest, 14.0),
            ("Days 8-30", focuses[1] if len(focuses) > 1 else weakest, 12.0),
            ("Days 31-60", focuses[2] if len(focuses) > 2 else "Interview Performance", 12.0),
            ("Days 61-90", focuses[3] if len(focuses) > 3 else "Advanced Differentiation", 10.0),
        )

        weekly_hours = 18.0 if tier.tier == 3 else 14.0 if tier.tier == 2 else 10.0
        phases: list[StudyPlanPhase] = []

        for phase_name, skill_key, _ in phase_defs:
            template = ACTION_TEMPLATES.get(skill_key)
            if template:
                skill_label, action, metric = template
            elif skill_key == "Advanced Differentiation":
                skill_label, action, metric = STRETCH_ACTION
            else:
                skill_label, action, metric = FALLBACK_ACTION

            resources = list(STUDY_RESOURCES.get(skill_key, DEFAULT_RESOURCES))
            # Guarantee at least 2 resources.
            while len(resources) < 2:
                resources.append(DEFAULT_RESOURCES[len(resources) % len(DEFAULT_RESOURCES)])

            if "Interview" in skill_key or skill_key == weakest:
                tasks = [
                    f"Morning (45 min): concept drill on {skill_label} using listed resources",
                    f"Evening (45 min): answer 2 interview-style questions on camera",
                    f"Weekend (2 hr): one timed mock covering {skill_label}",
                    action,
                ]
                routine = (
                    f"Mon-Fri: 90 minutes focused on {skill_label} (45 concept + 45 spoken). "
                    f"Sat: 2-hour mock. Sun: review mistakes and rewrite weak answers."
                )
            else:
                tasks = [
                    f"Block 60-90 minutes daily on {skill_label}",
                    action,
                    f"Log progress in a weekly tracker against: {metric}",
                    "Share one weekly demo or write-up with a peer/mentor for feedback",
                ]
                routine = (
                    f"Daily deep-work block of 60-90 minutes on {skill_label}, plus one weekly "
                    f"review with a mentor or placement buddy."
                )

            phases.append(
                StudyPlanPhase(
                    phase=phase_name,
                    focus_skill=skill_label,
                    daily_routine=routine,
                    practice_tasks=tasks[:4],
                    real_world_resources=resources[:4],
                    success_checkpoint=metric,
                )
            )

        overview = (
            f"{tier.label} study plan ({tier.title}): 90-day real-world schedule aimed at "
            f"closing '{weakest}' first, then lifting the next lagging dimensions. Expect about "
            f"{weekly_hours:.0f} focused hours per week using public platforms, mock interviews "
            f"and portfolio work — not just notes."
        )

        habits = [
            "Same study start time every weekday (habit > motivation)",
            "Record at least two spoken answers per week and re-watch with a scorecard",
            "Ship one visible artifact weekly (PR, notebook, SQL gist, or blog note)",
            "Sunday 30-minute audit: what moved scores, what still lags",
        ]
        if tier.tier == 3:
            habits.append("Protect attendance — never drop below Eligible status")

        tools = [
            "LeetCode / NeetCode for DSA and SQL",
            "GitHub for portfolio commits and README progress",
            "Pramp, Interviewing.io, or college mock panels",
            "Notion or Google Sheet for deadline + weakness tracker",
            "Loom or phone camera for answer recordings",
        ]

        return RealWorldStudyPlan(
            overview=overview,
            duration="90 days",
            weekly_hours=weekly_hours,
            phases=phases,
            daily_habits=habits[:5],
            tools_and_platforms=tools,
        )

    @staticmethod
    def _board_decision(
        data: ReportInputs,
        overall: float,
        status: str,
        eligible: bool,
        tier: PerformanceTier,
        weakest: str,
        lagging: list[LaggingArea],
    ) -> BoardDecision:
        from datetime import timedelta

        student = data.student
        top_lag = lagging[0].area if lagging else weakest

        if not eligible or tier.tier == 3 or status in ("Not Ready", "Needs Preparation"):
            decision = "INTENSIVE_SUPPORT"
            label = "Intensive support — hold premium drives"
            days = 30
            rationale = (
                f"{student.name} is {tier.label} ({tier.title}) at {overall:.2f}% with status "
                f"{status}. Attendance is {data.attendance.status}. Do not burn drive attempts; "
                f"run the foundation plan and re-score on the next review date."
            )
        elif tier.tier == 1 and status == "Placement Ready":
            decision = "CLEAR_FOR_DRIVES"
            label = "Cleared for active placement drives"
            days = 90
            rationale = (
                f"{student.name} clears Tier 1 gates at {overall:.2f}% with Eligible attendance "
                f"and a strong panel. Authorize active drives; keep depth work on {weakest} "
                f"as polish, not remediation."
            )
        else:
            decision = "HOLD_ONE_CYCLE"
            label = "Hold one cycle — sprint then re-clear"
            days = 45
            rationale = (
                f"{student.name} is {tier.label} at {overall:.2f}% ({status}). Realistic for "
                f"service drives after a focused sprint on {top_lag}; defer premium product "
                f"attempts until the next review."
            )

        review = (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()
        priority = (
            f"This week: close the gap in {top_lag} with daily timed practice and one recorded "
            f"mock answer before anything else."
        )

        return BoardDecision(
            decision=decision,
            decision_label=label,
            rationale=rationale,
            next_review_date=review,
            priority_fix=priority,
            signed_by="Meridian Placement Engine",
        )

    @staticmethod
    def _scorecard(
        data: ReportInputs,
        overall: float,
        status: str,
        eligible: bool,
        on_time_rate: float,
        tier: PerformanceTier,
    ) -> list[ScorecardRow]:
        iv = data.interview.overall_score
        cgpa = data.student.cgpa
        att = data.attendance.attendance_percentage

        def result(pass_ok: bool, watch: bool = False) -> str:
            if pass_ok:
                return "Pass"
            return "Watch" if watch else "Fail"

        return [
            ScorecardRow(
                metric="Composite score",
                value=f"{overall:.2f} / 100",
                benchmark="≥ 70 mass drives · ≥ 85 Tier 1",
                result=result(overall >= 70, watch=overall >= 55),
            ),
            ScorecardRow(
                metric="Performance tier",
                value=f"{tier.label} — {tier.title}",
                benchmark="Tier 1 or Tier 2 for active drives",
                result=result(tier.tier <= 2),
            ),
            ScorecardRow(
                metric="Interview panel",
                value=f"{iv:.2f} / 10",
                benchmark="≥ 7.0 advance · ≥ 8.0 Tier 1",
                result=result(iv >= 7.0, watch=iv >= 6.0),
            ),
            ScorecardRow(
                metric="CGPA filter",
                value=f"{cgpa:.2f} / 10",
                benchmark="≥ 7.0 recruiter shortlist",
                result=result(cgpa >= 7.0, watch=cgpa >= 6.5),
            ),
            ScorecardRow(
                metric="Attendance gate",
                value=f"{att:.2f}% · {data.attendance.status}",
                benchmark="Eligible (≥ 75%)",
                result=result(eligible),
            ),
            ScorecardRow(
                metric="On-time submissions",
                value=f"{on_time_rate:.0f}%",
                benchmark="≥ 90%",
                result=result(on_time_rate >= 90, watch=on_time_rate >= 75),
            ),
            ScorecardRow(
                metric="Placement status",
                value=status,
                benchmark="Placement Ready or Almost Ready",
                result=result(
                    status in ("Placement Ready", "Almost Ready"),
                    watch=status == "Needs Preparation",
                ),
            ),
        ]

    @staticmethod
    def _methodology_note() -> str:
        return (
            "Composite = Interview 40% + Assignments 30% + Assessments 20% + Attendance 10%. "
            "Interview answers are topic-tagged; weakest topic drives the study plan. "
            "Tier 1 requires Eligible attendance, composite ≥ 85 and interview ≥ 8/10. "
            "Tier 2 requires Eligible and composite ≥ 70. All other cases are Tier 3. "
            "Skill graph maps foundation → core → applied → Placement so bottleneck skills "
            "show downstream impact. Early warning compares levers to healthy bands before "
            "drive season. What-if readiness = Interview×10×0.30 + Assignments×0.25 + "
            "Attendance×0.10 + DSA×10×0.20 + Communication×10×0.15 (attendance <75% caps at 45%). "
            "This report is generated from validated source JSON only — no invented scores."
        )

    @staticmethod
    def _counselor_recommendation(
        data: ReportInputs,
        status: str,
        strongest: str,
        weakest: str,
        overall: float,
        tier: PerformanceTier,
    ) -> str:
        student = data.student
        if status == "Placement Ready":
            stance = (
                f"Clear {student.name} for active placement drives now and use the preparation "
                f"window for depth rather than remediation."
            )
        elif status == "Almost Ready":
            stance = (
                f"Shortlist {student.name} for drives in the next cycle and run one focused "
                f"remediation sprint in parallel."
            )
        elif status == "Needs Preparation":
            stance = (
                f"Hold {student.name} back from premium drives for one cycle and enrol in "
                f"structured preparation with weekly checkpoints."
            )
        else:
            stance = (
                f"Place {student.name} on an intensive support track before any drive exposure, "
                f"with fortnightly reviews by the placement cell."
            )

        return (
            f"{stance} Assign {tier.label} ({tier.title}) coaching intensity. Lead every "
            f"interview with {strongest} and rehearse {weakest} until it is no longer the "
            f"weakest topic on the transcript. Composite sits at {overall:.2f}% against a CGPA "
            f"of {student.cgpa:.2f}/10, so the interview transcript — not the marksheet — is "
            f"what decides the next outcome."
        )

    @staticmethod
    def _closing_note(name: str, status: str, weakest: str, tier: PerformanceTier) -> str:
        return (
            f"{name}, you are {tier.label} — {status.lower()}. One topic — {weakest} — separates "
            f"the current result from the next one, and it is a matter of reps, not talent."
        )
