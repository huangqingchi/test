"""Run real GPU smoke generation per workflow in separate processes, recording partial failures."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from h3_config import MODEL_ID, MODEL_REVISION, WORKFLOWS
from smoke_fixtures import create_fixtures
from verify_media import verify_media
from process_runner import cancellation_signals, run_generation, TerminationRequested


def save_report(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temp = Path(stream.name)
        json.dump(data, stream, indent=2, ensure_ascii=False)
    try:
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def workflow_arguments(workflow: str, fixtures: dict[str, Path]) -> list[str]:
    if workflow == "fl2va":
        return ["--image", str(fixtures["first"]), "--last-image", str(fixtures["last"])]
    if workflow == "ref2va":
        return ["--reference", "image", str(fixtures["first"]),
                "--reference", "video", str(fixtures["video"]),
                "--reference", "audio", str(fixtures["audio"])]
    return []


def run_acceptance(*, full: bool, output: Path, report_path: Path,
                   prompt: str, timeout: int) -> int:
    from preflight import validate_output
    output = validate_output(output, prompt)
    if report_path.resolve() == output:
        raise ValueError("Report and video output must be different paths")
    with cancellation_signals():
        return _run_acceptance(full=full, output=output, report_path=report_path,
                               prompt=prompt, timeout=timeout)


def _run_acceptance(*, full: bool, output: Path, report_path: Path,
                   prompt: str, timeout: int) -> int:
    selected = WORKFLOWS if full else ("t2va",)
    report = {
        "model_id": MODEL_ID, "revision": MODEL_REVISION,
        "scope": "all-workflows" if full else "quick-t2va-only",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "all_workflows_passed": False,
        "workflows": {name: {"status": "pending" if name in selected else "not_run"} for name in WORKFLOWS},
    }
    save_report(report_path, report)
    started = time.monotonic()
    current = None
    code = 1
    quick_directory = None
    try:
        fixtures = {}
        output.parent.mkdir(parents=True, exist_ok=True)
        if full:
            # Separate run directory means old sample files cannot look like new successes.
            run_dir = Path(tempfile.mkdtemp(prefix="h3-full-", dir=output.parent))
            fixtures = create_fixtures(run_dir / "inputs")
            report["run_directory"] = str(run_dir)
        else:
            quick_directory = tempfile.TemporaryDirectory(prefix=".h3-quick-", dir=output.parent)
            run_dir = Path(quick_directory.name)
        for workflow in selected:
            current = workflow
            entry = report["workflows"][workflow]
            destination = run_dir / f"{workflow}.mp4"
            published_output = destination if full else output
            entry.update(status="running", requested_output=str(published_output))
            save_report(report_path, report)
            command = [sys.executable, str(Path(__file__).with_name("generate.py")),
                       "--workflow", workflow, "--prompt", prompt, "--output", str(destination),
                       "--width", "960", "--height", "544", "--frames", "124", "--steps", "9",
                       *workflow_arguments(workflow, fixtures)]
            env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
            item_started = time.monotonic()
            print(f"Acceptance {workflow}: starting separate GPU process", flush=True)
            try:
                result = run_generation(command, env=env, timeout=timeout or None)
                code = result.returncode if result.returncode >= 0 else 128 - result.returncode
                entry["exit_code"] = code
                if code:
                    entry["status"] = "failed"
                    raise RuntimeError(f"{workflow} generation exited {code}")
                # Validate independently as well as inside generate.py.
                if not destination.is_file() or destination.stat().st_size == 0:
                    raise RuntimeError(f"{workflow} exited successfully without writing a new MP4")
                verify_media(destination, width=960, height=544, frames=124)
                if not full:
                    os.replace(destination, output)
                entry.update(status="passed", validated_output=str(published_output))
            except subprocess.TimeoutExpired:
                code = 124
                entry.update(status="timeout", exit_code=code)
                raise RuntimeError(f"{workflow} exceeded {timeout}s") from None
            finally:
                entry["elapsed_seconds"] = round(time.monotonic() - item_started, 3)
                save_report(report_path, report)
        report["status"] = "passed"
        report["all_workflows_passed"] = full
        code = 0
    except (Exception, KeyboardInterrupt) as exc:
        code = code or 1
        if isinstance(exc, KeyboardInterrupt):
            code = 130
        if isinstance(exc, TerminationRequested):
            code = 128 + exc.signum
        report.update(status="failed", error=str(exc) or "Interrupted")
        if current and report["workflows"][current]["status"] == "running":
            report["workflows"][current].update(
                status="cancelled" if isinstance(exc, (TerminationRequested, KeyboardInterrupt)) else "failed",
                exit_code=code)
        for entry in report["workflows"].values():
            if entry["status"] == "pending":
                entry["status"] = "not_run"
        print(f"Acceptance failed: {report['error']}", file=sys.stderr, flush=True)
    finally:
        if quick_directory is not None:
            quick_directory.cleanup()
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        save_report(report_path, report)
    print(f"Acceptance report: {report_path}", flush=True)
    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("quick", "all"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--timeout", type=int, default=0, help="Per workflow loading/generation deadline, seconds")
    args = parser.parse_args()
    if args.timeout < 0:
        parser.error("timeout must not be negative")
    raise SystemExit(run_acceptance(full=args.scope == "all", output=args.output.expanduser().resolve(),
                                   report_path=args.report.expanduser().resolve(), prompt=args.prompt,
                                   timeout=args.timeout))
