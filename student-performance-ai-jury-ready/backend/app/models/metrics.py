"""
app/models/metrics.py — Computed performance metrics schema.
"""

from pydantic import BaseModel


class PerformanceMetrics(BaseModel):
    """Calculated KPI metrics derived from all student data sources."""

    # Averages (all as percentages 0–100)
    assignment_average: float        # avg of (marks / max_marks * 100) across assignments
    assessment_average: float        # avg of score across assessments
    interview_score: float           # overall_score from interview (0–10 scale)
    attendance_score: float          # attendance_percentage

    # Composite
    overall_performance_score: float  # weighted sum of the above

    # Counts
    total_assignments: int
    total_assessments: int
    on_time_submissions: int          # assignments with submission_status == "On Time"
