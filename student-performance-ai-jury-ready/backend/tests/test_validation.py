"""
tests/test_validation.py — Stress test every domain model field.
Marks [BUG] where bad input passes when it should not.
"""

import sys
sys.path.insert(0, ".")

from pydantic import ValidationError
from app.models.domain import (
    Student, Interview, InterviewQuestion,
    AssignmentItem, AssessmentItem, Attendance
)

PASS = 0
BUGS = 0


def check(label, should_fail, fn):
    global PASS, BUGS
    caught = False
    try:
        fn()
    except (ValidationError, ValueError):
        caught = True

    if should_fail and caught:
        print(f"  [OK]  CAUGHT  -- {label}")
        PASS += 1
    elif should_fail and not caught:
        print(f"  [BUG] SLIPPED -- {label}  <<< NOT CAUGHT")
        BUGS += 1


def valid_student(**kw):
    base = dict(student_id="X001", name="John Doe", email="a@b.com",
                phone_number="9876543210", department="CS", year=2, semester=3, cgpa=8.5)
    base.update(kw)
    return Student(**base)


def valid_interview(**kw):
    base = dict(
        student_id="X001", student_name="John Doe",
        interview_date="2026-06-28", company="Google", job_role="SWE",
        overall_score=8.5,
        questions=[{"question": "Q?", "student_answer": "A.", "score": 8, "feedback": "OK"}],
        interviewer_observation={"communication": "Good"},
        strengths=["Python"], weaknesses=["SQL"],
    )
    base.update(kw)
    return Interview(**base)


def valid_assignment(**kw):
    base = dict(assignment_id="A1", title="Task", subject="CS",
                marks=80, max_marks=100, submission_status="On Time")
    base.update(kw)
    return AssignmentItem(**base)


def valid_assessment(**kw):
    base = dict(assessment_id="AS1", subject="Python", score=85.0, grade="A")
    base.update(kw)
    return AssessmentItem(**base)


def valid_attendance(**kw):
    base = dict(student_id="X001", month="June", working_days=22,
                present_days=21, absent_days=1, leave_days=0,
                attendance_percentage=95.45, status="Eligible")
    base.update(kw)
    return Attendance(**base)


print("\n" + "=" * 60)
print("  VALIDATION FAULT SCAN -- 10 FAULT TARGETS")
print("=" * 60)

# -- Student --
print("\n-- Student " + "-" * 49)
check("Name = '12345' (digits only, no letters)",       True, lambda: valid_student(name="12345"))
check("Name = 'A' (single char, too short)",            True, lambda: valid_student(name="A"))
check("Phone = '12345' (only 5 digits)",                True, lambda: valid_student(phone_number="12345"))
check("CGPA = 11.5 (exceeds 10.0)",                     True, lambda: valid_student(cgpa=11.5))
check("Year = 5 (exceeds max of 4)",                    True, lambda: valid_student(year=5))
check("Semester = 0 (below min of 1)",                  True, lambda: valid_student(semester=0))

# -- Assignment --
print("\n-- Assignment " + "-" * 45)
check("marks=150 > max_marks=100 (no cap check)",       True, lambda: valid_assignment(marks=150, max_marks=100))
check("submission_status = 'Dunno' (invalid literal)",  True, lambda: valid_assignment(submission_status="Dunno"))

# -- Assessment --
print("\n-- Assessment " + "-" * 45)
check("score = 105 (exceeds 100)",                      True, lambda: valid_assessment(score=105))
check("grade = '' (empty string, no validation)",       True, lambda: valid_assessment(grade=""))
check("subject = '' (empty string, no validation)",     True, lambda: valid_assessment(subject=""))

# -- Interview --
print("\n-- Interview " + "-" * 46)
check("overall_score = 11.0 (exceeds 10)",              True, lambda: valid_interview(overall_score=11.0))
check("company = '' (empty string, no validation)",     True, lambda: valid_interview(company=""))
check("job_role = '' (empty string, no validation)",    True, lambda: valid_interview(job_role=""))
check("student_name = '999' (numeric, no validation)",  True, lambda: valid_interview(student_name="999"))
check("student_answer = '' (empty, no validation)",     True,
      lambda: valid_interview(questions=[{"question": "Q?", "student_answer": "", "score": 8, "feedback": "OK"}]))

# -- Attendance --
print("\n-- Attendance " + "-" * 45)
check("attendance_percentage = 110 (exceeds 100)",      True, lambda: valid_attendance(attendance_percentage=110))
check("status = 'Maybe' (invalid literal)",             True, lambda: valid_attendance(status="Maybe"))
check("present_days=30 > working_days=22 (no check)",  True, lambda: valid_attendance(present_days=30))
check("month = 'Octember' (invalid month name)",        True, lambda: valid_attendance(month="Octember"))
check("days don't add up: 20+1+0=21 != 22 working",    True, lambda: valid_attendance(present_days=20))

print("\n" + "=" * 60)
print(f"  RESULT: {PASS} caught  |  {BUGS} slipped through (BUGS TO FIX)")
print("=" * 60 + "\n")
