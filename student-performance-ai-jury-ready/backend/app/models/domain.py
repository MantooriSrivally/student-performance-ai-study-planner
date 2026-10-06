"""
app/models/domain.py — Core student domain definitions with Pydantic validations.
"""

import re
from datetime import date
from typing import Optional, List, Dict, Literal
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


VALID_MONTHS = {
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
}


def _empty_to_none(v: Optional[str]) -> Optional[str]:
    if isinstance(v, str) and not v.strip():
        return None
    return v


def _reject_empty(field: str, v: str) -> str:
    if not v or not v.strip():
        raise ValueError(f"{field} cannot be empty")
    return v.strip()


def _validate_name(v: str) -> str:
    v = v.strip()
    if len(v) < 2:
        raise ValueError(f"Name must be at least 2 characters, got '{v}'")
    if not re.search(r"[a-zA-Z]", v):
        raise ValueError("Name must contain at least one letter")
    if not re.match(r"^[a-zA-Z\s.\-']+$", v):
        raise ValueError(f"Name contains invalid characters: '{v}'")
    return v.title()


# ── Student ───────────────────────────────────────────────────────────────────

class Student(BaseModel):
    """Represents a student's profile information."""
    model_config = ConfigDict(str_strip_whitespace=True)

    student_id: str
    name: str
    email: EmailStr
    phone_number: str
    department: str
    year: int = Field(ge=1, le=4)
    semester: int = Field(ge=1, le=8)
    cgpa: float = Field(ge=0.0, le=10.0)

    @field_validator("name", mode="before")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_name(v)

    @field_validator("email", mode="before")
    @classmethod
    def normalize_email(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("department", mode="before")
    @classmethod
    def normalize_department(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("phone_number", mode="before")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = re.sub(r"\D", "", str(v))
        if len(digits) != 10:
            raise ValueError(f"Phone must contain exactly 10 digits, got {len(digits)}")
        return v.strip()


# ── Interview ─────────────────────────────────────────────────────────────────

class InterviewQuestion(BaseModel):
    """A single interview question with student's answer and evaluation."""
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str
    student_answer: str  # FIX 7: validated non-empty below
    score: int = Field(ge=0, le=10)
    feedback: Optional[str] = None

    @field_validator("question", mode="before")
    @classmethod
    def validate_question(cls, v: str) -> str:
        return _reject_empty("question", v)

    # FIX 7: student_answer cannot be empty
    @field_validator("student_answer", mode="before")
    @classmethod
    def validate_student_answer(cls, v: str) -> str:
        return _reject_empty("student_answer", v)

    @field_validator("feedback", mode="before")
    @classmethod
    def coerce_feedback(cls, v: Optional[str]) -> Optional[str]:
        return _empty_to_none(v)


class Interview(BaseModel):
    """Full technical interview evaluation record."""
    model_config = ConfigDict(str_strip_whitespace=True)

    student_id: str
    student_name: str   # FIX 6: validated below
    interview_date: date
    company: str        # FIX 4: validated below
    job_role: str       # FIX 5: validated below
    overall_score: float = Field(ge=0.0, le=10.0)
    questions: List[InterviewQuestion] = Field(min_length=1)
    interviewer_observation: Dict[str, str]
    strengths: List[str]
    weaknesses: List[str]
    overall_feedback: Optional[str] = None

    # FIX 6: student_name must contain letters like Student.name
    @field_validator("student_name", mode="before")
    @classmethod
    def validate_student_name(cls, v: str) -> str:
        return _validate_name(v)

    # FIX 4: company cannot be empty
    @field_validator("company", mode="before")
    @classmethod
    def validate_company(cls, v: str) -> str:
        return _reject_empty("company", v)

    # FIX 5: job_role cannot be empty
    @field_validator("job_role", mode="before")
    @classmethod
    def validate_job_role(cls, v: str) -> str:
        return _reject_empty("job_role", v)

    @field_validator("overall_feedback", mode="before")
    @classmethod
    def coerce_feedback(cls, v: Optional[str]) -> Optional[str]:
        return _empty_to_none(v)


# ── Assignment ────────────────────────────────────────────────────────────────

class AssignmentItem(BaseModel):
    """An individual assignment submission record."""
    model_config = ConfigDict(str_strip_whitespace=True)

    assignment_id: str
    title: str
    subject: str
    marks: int = Field(ge=0)
    max_marks: int = Field(gt=0)
    submission_status: Literal["On Time", "Late", "Pending"]
    feedback: Optional[str] = None

    @field_validator("feedback", mode="before")
    @classmethod
    def coerce_feedback(cls, v: Optional[str]) -> Optional[str]:
        return _empty_to_none(v)

    # FIX 1: marks cannot exceed max_marks
    @model_validator(mode="after")
    def marks_within_range(self) -> "AssignmentItem":
        if self.marks > self.max_marks:
            raise ValueError(
                f"[{self.title}] marks ({self.marks}) cannot exceed max_marks ({self.max_marks})"
            )
        return self


class Assignment(BaseModel):
    """Collection of assignments for a student."""
    model_config = ConfigDict(str_strip_whitespace=True)

    student_id: str
    assignments: List[AssignmentItem] = Field(default_factory=list)


# ── Assessment ────────────────────────────────────────────────────────────────

class AssessmentItem(BaseModel):
    """A single assessment record with score and grade."""
    model_config = ConfigDict(str_strip_whitespace=True)

    assessment_id: str
    subject: str    # FIX 3: validated below
    score: float = Field(ge=0.0, le=100.0)
    grade: str      # FIX 2: validated below

    # FIX 2: grade cannot be empty
    @field_validator("grade", mode="before")
    @classmethod
    def validate_grade(cls, v: str) -> str:
        return _reject_empty("grade", v)

    # FIX 3: subject cannot be empty
    @field_validator("subject", mode="before")
    @classmethod
    def validate_subject(cls, v: str) -> str:
        return _reject_empty("subject", v)


class Assessment(BaseModel):
    """Collection of assessments for a student."""
    model_config = ConfigDict(str_strip_whitespace=True)

    student_id: str
    assessments: List[AssessmentItem] = Field(default_factory=list)


# ── Attendance ────────────────────────────────────────────────────────────────

class Attendance(BaseModel):
    """Monthly attendance aggregates."""
    model_config = ConfigDict(str_strip_whitespace=True)

    student_id: str
    month: str      # FIX 10: validated below
    working_days: int = Field(gt=0)
    present_days: int = Field(ge=0)
    absent_days: int = Field(ge=0)
    leave_days: int = Field(ge=0)
    attendance_percentage: float = Field(ge=0.0, le=100.0)
    status: Literal["Eligible", "Not Eligible"]

    # FIX 10: month must be a real calendar month
    @field_validator("month", mode="before")
    @classmethod
    def validate_month(cls, v: str) -> str:
        if v.strip().lower() not in VALID_MONTHS:
            raise ValueError(f"Invalid month: '{v}'. Must be a full month name (e.g. 'June')")
        return v.strip().title()

    # FIX 8: present_days cannot exceed working_days
    # FIX 9: present + absent + leave must equal working_days
    @model_validator(mode="after")
    def validate_day_counts(self) -> "Attendance":
        if self.present_days > self.working_days:
            raise ValueError(
                f"present_days ({self.present_days}) cannot exceed working_days ({self.working_days})"
            )
        total = self.present_days + self.absent_days + self.leave_days
        if total != self.working_days:
            raise ValueError(
                f"present_days + absent_days + leave_days ({total}) must equal working_days ({self.working_days})"
            )
        return self


# ── AI Analysis (mock data) ───────────────────────────────────────────────────

class OverallPerformance(BaseModel):
    """Pre-computed performance summary."""
    score: int = Field(ge=0, le=100)
    grade: str
    status: str


class AIAnalysis(BaseModel):
    """Legacy 3-field mock. Live reports use app.models.report.StudentPerformanceReport."""
    model_config = ConfigDict(str_strip_whitespace=True)

    student_id: str
    student_name: str
    overall_performance: OverallPerformance
