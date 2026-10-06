"""
app/utils/logger.py — Beautiful, high-tech Stark Industries HUD logger.
"""

import sys
from datetime import datetime


class ConsoleColor:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    RESET = "\033[0m"


class JarvLogger:
    """ASCII diagnostics print utility matching Iron Man JARVIS console style."""

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%H:%M:%S.%f")[:-3]

    @classmethod
    def system(cls, msg: str) -> None:
        print(f"[{cls._timestamp()}] {ConsoleColor.CYAN}[SYS] {msg}{ConsoleColor.RESET}", file=sys.stderr)

    @classmethod
    def info(cls, msg: str) -> None:
        print(f"[{cls._timestamp()}] {ConsoleColor.BOLD}>>> {msg}{ConsoleColor.RESET}", file=sys.stderr)

    @classmethod
    def success(cls, msg: str) -> None:
        print(f"[{cls._timestamp()}] {ConsoleColor.GREEN}[OK]  {msg}{ConsoleColor.RESET}", file=sys.stderr)

    @classmethod
    def warn(cls, msg: str) -> None:
        print(f"[{cls._timestamp()}] {ConsoleColor.YELLOW}[WRN] {msg}{ConsoleColor.RESET}", file=sys.stderr)

    @classmethod
    def error(cls, msg: str) -> None:
        print(f"[{cls._timestamp()}] {ConsoleColor.RED}[ERR] {msg}{ConsoleColor.RESET}", file=sys.stderr)

    @classmethod
    def header(cls, title: str) -> None:
        border = "=" * 65
        print(f"\n{ConsoleColor.CYAN}{ConsoleColor.BOLD}{border}", file=sys.stderr)
        print(f"  {title.center(61)}", file=sys.stderr)
        print(f"{border}{ConsoleColor.RESET}\n", file=sys.stderr)

    @classmethod
    def metrics_summary(cls, label: str, duration_ms: float) -> None:
        print(
            f"  +- {ConsoleColor.MAGENTA}{label:<24}{ConsoleColor.RESET} [ {duration_ms:6.2f} ms ]",
            file=sys.stderr,
        )

    @classmethod
    def show_dashboard(cls, unified) -> None:
        """Draws a beautiful, high-tech ASCII dashboard summarizing computed KPIs."""
        def make_bar(pct: float) -> str:
            blocks = int(round((pct / 100.0) * 30))
            return f"[{'#' * blocks}{'-' * (30 - blocks)}]"

        student = unified.student
        metrics = unified.metrics

        border = "+" + "-" * 63 + "+"
        err = sys.stderr
        print(f"\n{ConsoleColor.CYAN}{ConsoleColor.BOLD}{border}", file=err)
        print(f"| {'[JARVIS DIAGNOSTIC REPORT: ACTIVE]'.center(61)} |", file=err)
        print(f"{border}{ConsoleColor.RESET}", file=err)

        print(f"  {ConsoleColor.BOLD}Student Profile:{ConsoleColor.RESET}", file=err)
        print(f"    Name:   {student.name:<25} ID:     {student.student_id}", file=err)
        print(f"    Dept:   {student.department:<25} Year:   Sem {student.semester} (Year {student.year})", file=err)
        print(f"    CGPA:   {student.cgpa:<25} Phone:  {student.phone_number}", file=err)
        print("-" * 65, file=err)

        print(f"  {ConsoleColor.BOLD}Academic Diagnostics & Key Performance Indicators:{ConsoleColor.RESET}", file=err)

        overall = metrics.overall_performance_score
        bar = make_bar(overall)
        print(f"    Overall Performance: {ConsoleColor.GREEN}{bar} {overall:6.2f}%{ConsoleColor.RESET}", file=err)

        att = metrics.attendance_score
        bar = make_bar(att)
        print(f"    Attendance Metric:   {ConsoleColor.CYAN}{bar} {att:6.2f}%{ConsoleColor.RESET}", file=err)

        assign = metrics.assignment_average
        bar = make_bar(assign)
        print(f"    Assignment Average:  {ConsoleColor.YELLOW}{bar} {assign:6.2f}%{ConsoleColor.RESET}", file=err)

        assess = metrics.assessment_average
        bar = make_bar(assess)
        print(f"    Assessment Average:  {ConsoleColor.MAGENTA}{bar} {assess:6.2f}%{ConsoleColor.RESET}", file=err)

        int_score_pct = metrics.interview_score * 10
        bar = make_bar(int_score_pct)
        print(f"    Interview Score:     {ConsoleColor.CYAN}{bar} {metrics.interview_score:6.2f}/10{ConsoleColor.RESET}", file=err)
        print("-" * 65, file=err)

        print(f"  {ConsoleColor.BOLD}System Alerts & Metrics:{ConsoleColor.RESET}", file=err)
        print(f"    - On-Time Submissions: {ConsoleColor.GREEN}{metrics.on_time_submissions}{ConsoleColor.RESET} / {metrics.total_assignments}", file=err)
        print(f"    - Total Assessments:   {metrics.total_assessments}", file=err)
        print(f"{ConsoleColor.CYAN}{ConsoleColor.BOLD}{border}{ConsoleColor.RESET}\n", file=err)


