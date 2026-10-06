"""
main.py — Entrypoint. Outputs only the generated performance report.

On success, stdout contains the strict AI report JSON and nothing else.
If loading, cleaning, validation, or report generation fails, stdout contains
one JSON error object instead.
"""

import json
import sys

from app.core.pipeline import StudentDataPipeline


def _load_env() -> None:
    """Load .env if python-dotenv is installed; its absence is not an error."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv()


def _force_utf8_streams() -> None:
    """
    JSON is UTF-8 by definition, but a Windows console defaults to cp1252 and
    would emit the report's em dashes as undecodable bytes. Without this, a
    redirected stdout is not valid JSON.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")


def main() -> None:
    _force_utf8_streams()
    _load_env()

    try:
        unified = StudentDataPipeline(logging=False).run()
    except Exception as e:
        # Keep failures machine-readable without mixing them into valid reports.
        print(json.dumps({"error": type(e).__name__, "detail": str(e)}, indent=2))
        sys.exit(1)

    print(unified.report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
