#!/usr/bin/env python3
"""Persist explicitly selected local DF Agent roots and runtime; no installation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

_SPEC = importlib.util.spec_from_file_location("team_advisor_setup_doctor", Path(__file__).with_name("doctor.py"))
doctor = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(doctor)

CONFIG_SCHEMA = "team-advisor-setup/1"
PLAN_SCHEMA = "team-advisor-setup-plan/1"
CONFIG_NAME = "setup.local.json"
PLUGIN_ROOT = Path(__file__).resolve().parents[3]


def package_boundaries():
    boundaries = [PLUGIN_ROOT]
    for parent in PLUGIN_ROOT.parents:
        if (parent / ".agents/plugins/marketplace.json").is_file():
            boundaries.append(parent)
            break
    return boundaries


def external(path, roots=()):
    path = doctor.no_links(path)
    if any(doctor.under(path, root) for root in [*package_boundaries(), *roots]):
        raise doctor.CheckError("Local setup state and output must be outside plugin, repository and skill roots.")
    return path


def fingerprint(report):
    """Persist only selected public source fingerprints, plus runtime/scan coverage."""
    return {
        "scope": report["observation_context"]["scope_fingerprint"],
        "runtime": report["observation_context"]["runtime_fingerprint"],
        "selection": copy.deepcopy(report["source_selection"]),
        "sources": [
            {"task_profile": item["task_profile"], "source_ref": item["source_ref"],
             "source_fingerprint": item["source_fingerprint"]}
            for item in report["skills"]
            if item["source_ref"] and report["source_selection"][item["skill_id"]]["source_ref"] == item["source_ref"]
        ],
        "coverage_limitations": report["coverage_limitations"],
    }


def validate_runtime(path):
    path = doctor.no_links(path)
    if "windowsapps" in {part.lower() for part in path.parts}:
        raise doctor.CheckError("Choose a real interpreter, not a WindowsApps execution alias.")
    probe = doctor.probe_python(path)
    version = probe.get("python") if isinstance(probe, dict) else None
    if not isinstance(version, list) or len(version) != 3 or any(type(n) is not int for n in version) or tuple(version) < (3, 11, 0):
        raise doctor.CheckError("The selected interpreter must run Python 3.11 or newer.")
    return str(path)


def validate_config(config, state):
    required = {"schema_version", "revision", "updated_at", "state_dir", "roots", "python", "bindings", "baseline"}
    if not isinstance(config, dict) or set(config) != required or config["schema_version"] != CONFIG_SCHEMA:
        raise doctor.CheckError("Invalid local setup configuration schema.")
    if type(config["revision"]) is not int or config["revision"] < 1:
        raise doctor.CheckError("Invalid local setup revision.")
    doctor.stamp(config["updated_at"])
    if config["state_dir"] != str(state):
        raise doctor.CheckError("Configuration belongs to another state directory; create a new setup plan.")
    if not isinstance(config["roots"], list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in config["roots"]):
        raise doctor.CheckError("Saved roots must be absolute path strings.")
    roots = doctor.normalize_roots(config["roots"])
    if [str(p) for p in roots] != config["roots"]:
        raise doctor.CheckError("Saved roots must be normalized and unique.")
    external(state, roots)
    if not isinstance(config["python"], str) or not Path(config["python"]).is_absolute():
        raise doctor.CheckError("Saved runtime must be an absolute interpreter path.")
    baseline = config["baseline"]
    if not isinstance(baseline, dict) or set(baseline) != {"scope", "runtime", "selection", "sources", "coverage_limitations"}:
        raise doctor.CheckError("Invalid local setup baseline.")
    if not isinstance(baseline["sources"], list) or not isinstance(baseline["coverage_limitations"], list):
        raise doctor.CheckError("Invalid local setup source baseline.")
    # Reuse the detector's strict binding grammar without probing any source.
    dummy = {"skills": [], "source_bindings": {"preferred_sources": {}}}
    doctor.select_sources(dummy, config["bindings"])
    return config


def read_config(state):
    state = external(state)
    path = state / CONFIG_NAME
    if not path.exists():
        return None
    return validate_config(doctor.read_json(path), state)


def current_digest(config):
    return doctor.digest(config) if config is not None else None


def make_plan(state_dir, roots, python, bindings=None, session_id="setup-plan"):
    roots = doctor.normalize_roots(roots)
    for root in roots:
        if not doctor.no_links(root).is_dir():
            raise doctor.CheckError("Each chosen skill root must be an existing readable directory.")
    state = external(state_dir, roots)
    if state.exists() and not state.is_dir():
        raise doctor.CheckError("State path must be a directory.")
    previous = read_config(state)
    python = validate_runtime(python)
    if bindings is None and previous is not None and previous["roots"] == [str(p) for p in roots]:
        bindings = previous["bindings"]
    report = doctor.scan(roots, python, session_id=session_id, bindings=bindings)
    # Pin every unambiguous choice, including a unique readable candidate. Missing
    # optional skills remain unavailable rather than blocking all setup.
    selected = {key: item["source_ref"] for key, item in report["source_selection"].items() if item["status"] == "selected"}
    unresolved = {key: item for key, item in report["source_selection"].items() if item["status"] == "ambiguous"}
    if unresolved:
        raise doctor.CheckError("Multiple or missing bound sources require explicit preferred_sources before setup: " + ", ".join(sorted(unresolved)))
    report = doctor.select_sources(report, {"preferred_sources": selected})
    doctor.validate(report)
    config = {"schema_version": CONFIG_SCHEMA, "revision": (previous["revision"] + 1) if previous else 1,
              "updated_at": doctor.now(), "state_dir": str(state), "roots": [str(p) for p in roots],
              "python": python, "bindings": {"preferred_sources": selected}, "baseline": fingerprint(report)}
    plan = {"schema_version": PLAN_SCHEMA, "created_at": doctor.now(), "state_dir": str(state),
            "previous_config_digest": current_digest(previous), "config": config,
            "capabilities": report, "effects": ["Save local roots, runtime, source bindings and public fingerprints only."],
            "network_calls": False, "professional_scripts_executed": False}
    plan["plan_digest"] = doctor.digest(plan)
    return plan


@contextmanager
def locked(state):
    state.mkdir(parents=True, exist_ok=True)
    doctor.no_links(state)
    lock = state / ".setup.lock"
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise doctor.CheckError("Another setup writer or unfinished setup lock exists; no change made.") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def atomic_save(path, value):
    path = doctor.no_links(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=".setup-", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        doctor.no_links(path)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def apply_plan(state_dir, plan):
    state = external(state_dir)
    required = {"schema_version", "created_at", "state_dir", "previous_config_digest", "config", "capabilities", "effects", "network_calls", "professional_scripts_executed", "plan_digest"}
    if not isinstance(plan, dict) or set(plan) != required or plan["schema_version"] != PLAN_SCHEMA:
        raise doctor.CheckError("Invalid setup plan schema.")
    unsigned = {key: value for key, value in plan.items() if key != "plan_digest"}
    if doctor.digest(unsigned) != plan["plan_digest"] or plan["state_dir"] != str(state):
        raise doctor.CheckError("Setup plan changed or belongs to another state directory.")
    doctor.stamp(plan["created_at"])
    config = validate_config(plan["config"], state)
    doctor.validate(plan["capabilities"])
    if fingerprint(plan["capabilities"]) != config["baseline"]:
        raise doctor.CheckError("Plan baseline does not match the reviewed capability report.")
    validate_runtime(config["python"])
    report = doctor.scan(config["roots"], config["python"], session_id="setup-apply", bindings=config["bindings"])
    doctor.validate(report)
    if fingerprint(report) != config["baseline"]:
        raise doctor.CheckError("Source, coverage or runtime changed after planning; create and review a fresh plan.")
    with locked(state):
        previous = read_config(state)
        expected_revision = previous["revision"] + 1 if previous else 1
        if current_digest(previous) != plan["previous_config_digest"] or config["revision"] != expected_revision:
            raise doctor.CheckError("Saved configuration changed after planning; create a fresh plan.")
        atomic_save(state / CONFIG_NAME, config)
    return {"status": "configured", "revision": config["revision"], "state_dir": str(state),
            "bindings": config["bindings"], "host_discovery": "not_checked", "business_connections": "not_checked",
            "network_calls": False, "professional_scripts_executed": False}


def status(state_dir, session_id="unspecified"):
    state = external(state_dir)
    config = read_config(state)
    if config is None:
        return {"status": "not_configured", "state_dir": str(state), "next_action": "Create a setup plan with explicitly selected skill roots and interpreter."}
    # Status is read-only and never silently rebinds or refreshes the baseline.
    report = doctor.scan(config["roots"], config["python"], session_id=session_id, bindings=config["bindings"])
    doctor.validate(report)
    current = fingerprint(report)
    previous = config["baseline"]
    changes = [key for key in current if current[key] != previous[key]]
    return {"status": "changed" if changes else "unchanged", "revision": config["revision"],
            "state_dir": str(state), "python": config["python"], "roots": config["roots"],
            "bindings": config["bindings"], "changed_components": changes, "capabilities": report,
            "next_action": "Review changed source/runtime and create a fresh plan before using affected bindings." if changes else "Use current task-specific capability checks; saved setup does not prove task readiness.",
            "network_calls": False, "professional_scripts_executed": False}


def write_private_output(path, value, state, roots):
    path = external(path, roots)
    if path == doctor.absolute(state) / CONFIG_NAME or doctor.under(path, state):
        raise doctor.CheckError("Plan/report output must be outside managed setup state.")
    path.parent.mkdir(parents=True, exist_ok=True)
    doctor.no_links(path)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError:
        raise doctor.CheckError("Output already exists; choose a new filename.") from None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    planning = subparsers.add_parser("plan", help="Read approved public roots and prepare a reviewable local setup plan")
    planning.add_argument("--state-dir", required=True)
    planning.add_argument("--roots", nargs="+", required=True)
    planning.add_argument("--python", required=True)
    planning.add_argument("--bindings")
    planning.add_argument("--session-id", default="setup-plan")
    planning.add_argument("--output", required=True)
    applying = subparsers.add_parser("apply", help="Apply a reviewed unchanged plan")
    applying.add_argument("--state-dir", required=True)
    applying.add_argument("--plan", required=True)
    checking = subparsers.add_parser("status", help="Revalidate saved bindings without modifying them")
    checking.add_argument("--state-dir", required=True)
    checking.add_argument("--session-id", default="unspecified")
    checking.add_argument("--output")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = make_plan(args.state_dir, args.roots, args.python, doctor.read_json(args.bindings) if args.bindings else None, args.session_id)
            write_private_output(args.output, result, args.state_dir, args.roots)
            result = {"status": "planned", "plan": str(doctor.absolute(args.output)), "revision": result["config"]["revision"],
                      "selected_sources": result["config"]["bindings"], "state_written": False,
                      "capabilities": result["capabilities"]}
        elif args.command == "apply":
            result = apply_plan(args.state_dir, doctor.read_json(args.plan))
        else:
            result = status(args.state_dir, args.session_id)
            if args.output:
                write_private_output(args.output, result, args.state_dir, result.get("roots", []))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, doctor.CheckError, TypeError, KeyError, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
