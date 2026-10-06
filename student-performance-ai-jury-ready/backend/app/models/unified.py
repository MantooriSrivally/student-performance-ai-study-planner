"""
app/models/unified.py — Final aggregated UnifiedStudent schema.

This object is the program's stdout: one JSON document, nothing else.
"""

from pydantic import BaseModel
from app.models.domain import Student, Interview, Assignment, Assessment, Attendance
from app.models.metrics import PerformanceMetrics
from app.models.report import StudentPerformanceReport


class UnifiedStudent(BaseModel):
    """Single JSON document: sources + KPIs + board-ready AI report."""

    student: Student
    interview: Interview
    assignment: Assignment
    assessment: Assessment
    attendance: Attendance
    metrics: PerformanceMetrics
    report: StudentPerformanceReport
