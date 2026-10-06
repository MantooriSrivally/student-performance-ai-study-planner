import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(BACKEND))

from app.core.pipeline import StudentDataPipeline


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: pipeline_runner.py <data_dir>")
    data_dir = Path(sys.argv[1]).resolve()
    unified = StudentDataPipeline(data_dir=data_dir, logging=False).run()
    # Write UTF-8 bytes so Windows cp1252 consoles cannot break on report text.
    payload = unified.report.model_dump_json(indent=2) + "\n"
    try:
        sys.stdout.buffer.write(payload.encode("utf-8"))
    except AttributeError:
        print(payload, end="")


if __name__ == "__main__":
    main()
