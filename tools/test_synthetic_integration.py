#!/usr/bin/env python3
"""Run an explicitly scoped local-reader -> DataLab -> ETF synthetic integration.

All installed-skill, interpreter, source-fixture and output paths are parameters.
The source is exactly four public fixtures; existing user profiles are not used.
This exercises the real local reader, not a production source or OS sandbox.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from decimal import Decimal

sys.dont_write_bytecode = True
FILES = ("product.md", "products.csv", "fund_flows.csv", "synthetic_corpus.md")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inside(path, parent):
    return Path(path).resolve().is_relative_to(Path(parent).resolve())


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def new_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--df-skill", required=True, type=Path)
    parser.add_argument("--data-skill", required=True, type=Path)
    parser.add_argument("--etf-skill", required=True, type=Path)
    parser.add_argument("--target", required=True, type=Path)
    parser.add_argument("--resume", action="store_true", help="Resume this exact synthetic source and saved plan only")
    parser.add_argument("--reader-only", action="store_true")
    args = parser.parse_args()
    project, target = args.project.resolve(), args.target.resolve()
    source, logs, state = target / "source", target / "logs", target / "state"
    fixtures = project / "evals" / "fixtures"
    if target.exists() and not args.resume:
        raise RuntimeError("Target exists; choose a new isolated target or explicitly resume this run")
    if not target.exists():
        source.mkdir(parents=True)
        logs.mkdir()
        for name in FILES:
            fixture = fixtures / name
            if fixture.is_symlink() or not fixture.is_file():
                raise RuntimeError("Expected regular public fixture is missing")
            shutil.copy2(fixture, source / name)
    if not source.is_dir() or not logs.is_dir() or source.is_symlink():
        raise RuntimeError("Expected synthetic source/log directories are missing or linked")
    actual = sorted(path.name for path in source.iterdir())
    if actual != sorted(FILES):
        raise RuntimeError("Synthetic source contains an unexpected file or subdirectory")
    before = {name: sha256(source / name) for name in FILES}
    if any(before[name] != sha256(fixtures / name) for name in FILES):
        raise RuntimeError("Synthetic source differs from the approved project fixtures")
    python = str(args.python.resolve())
    df_init = str((args.df_skill / "scripts" / "df-init.py").resolve())
    df_tool = str((args.df_skill / "scripts" / "df-tool.py").resolve())

    def call(label, script, argv, cached=True):
        output = logs / (label + ".json")
        if args.resume and cached and output.exists():
            result = read_json(output)
            if result.get("ok") is False:
                raise RuntimeError(f"Saved operation failed: {label}; inspect it before deciding a retry")
            return result
        command = [python, "-X", "utf8", "-B", str(script), *map(str, argv)]
        completed = subprocess.run(command, text=True, encoding="utf-8", capture_output=True, timeout=55)
        with (logs / (label + ".command.json")).open("x", encoding="utf-8") as stream:
            json.dump({"argv": command, "exit_code": completed.returncode,
                       "observed_at": datetime.now(timezone.utc).isoformat()}, stream, ensure_ascii=False)
        if completed.stderr:
            with (logs / (label + ".stderr.txt")).open("x", encoding="utf-8") as stream:
                stream.write(completed.stderr)
        try:
            result = json.loads(completed.stdout)
        except ValueError:
            with (logs / (label + ".stdout.txt")).open("x", encoding="utf-8") as stream:
                stream.write(completed.stdout)
            raise RuntimeError(f"Operation did not return JSON: {label}")
        new_json(output, result)
        if completed.returncode or result.get("ok") is False:
            raise RuntimeError(f"Operation failed: {label}; no bypass or source substitution performed")
        return result

    plan_path = target / "plan.json"
    if plan_path.exists() and args.resume:
        plan = read_json(plan_path)
    else:
        plan = call("plan", df_init, ["plan", "--choice", "local", "--source", source, "--state-dir", state])
        new_json(plan_path, plan)
    if plan["config"]["provider"] != "local" or Path(plan["config"]["root"]).resolve() != source:
        raise RuntimeError("Plan source/provider does not match the approved synthetic tree")
    if not inside(plan["config"]["state_dir"], state) or not inside(plan["config_path"], state):
        raise RuntimeError("Plan state/config escaped the isolated state base")
    if plan.get("account_binding") is not None or plan["request"].get("selection") is not None:
        raise RuntimeError("A cloud account appeared in a local-only test")
    applied = call("apply", df_init, ["apply", "--plan", plan_path, "--confirmed"])
    config = Path(applied["config_path"]).resolve()
    if config != Path(plan["config_path"]).resolve():
        raise RuntimeError("Apply returned a different configuration")

    def tool(label, method, parameters=None, paginate=False, wait=False):
        argv = [method, "--config", config]
        if parameters is not None:
            params_path = logs / (label + ".params.json")
            if not params_path.exists():
                new_json(params_path, parameters)
            elif read_json(params_path) != parameters:
                raise RuntimeError("Parameters changed during resume")
            argv += ["--params-file", params_path]
        if paginate:
            argv.append("--paginate")
        if wait:
            argv += ["--wait-ready", "30"]
        return call(label, df_tool, argv)

    status = tool("status", "status", wait=True)
    job = tool("job_status", "job_status")
    if job["job"]["status"] != "complete":
        raise RuntimeError("The initial scan has not completed")
    if status["provider"] != "local" or not status["coverage"]["inventory_complete"]:
        raise RuntimeError("Local inventory is not complete")
    if status["coverage"]["present_files"] != len(FILES) or status["coverage"]["indexed_files"] != len(FILES):
        raise RuntimeError("Unexpected synthetic file count")
    if status.get("network_calls") or status["retrieval"].get("network_calls_enabled"):
        raise RuntimeError("Network retrieval unexpectedly enabled")
    inventory = tool("list", "list", paginate=True)
    if not inventory["pagination_complete"]:
        raise RuntimeError("Synthetic inventory pagination is incomplete")
    files = [file for page in inventory["pages"] for file in page["files"]]
    if sorted(file["path"] for file in files) != sorted(FILES):
        raise RuntimeError("Inventory does not equal the approved four-file source")
    evidence = {}
    for file in files:
        name, file_id = file["path"], file["file_id"]
        inspected = tool("inspect-" + name, "inspect", {"file_id": file_id}, paginate=True)
        versions = {page["source_version"] for page in inspected["pages"]}
        if len(versions) != 1:
            raise RuntimeError("Inspect changed source version")
        version = versions.pop()
        read = tool("read-" + name, "read", {"file_id": file_id, "expected_version": version}, paginate=True)
        if not read["pagination_complete"] or any(page["source_version"] != version for page in read["pages"]):
            raise RuntimeError("Read is partial or changed version")
        exported = tool("export-" + name, "export", {"file_id": file_id, "expected_version": version, "format": "jsonl"})
        artifact = Path(exported["artifact_path"]).resolve()
        if not inside(artifact, state) or not artifact.is_file():
            raise RuntimeError("Export is inaccessible or outside isolated state")
        export_rows = [json.loads(line) for line in artifact.read_text(encoding="utf-8").splitlines() if line]
        evidence[name] = {"file_id": file_id, "source_version": version,
                          "export_artifact": str(artifact), "export_sha256": sha256(artifact),
                          "export_records": len(export_rows),
                          "read_segments": sum(len(page["segments"]) for page in read["pages"])}
    if {name: sha256(source / name) for name in FILES} != before:
        raise RuntimeError("Synthetic source changed during the test")
    report = {"observed_at": datetime.now(timezone.utc).isoformat(),
              "scope": "real reader code, synthetic local provider only",
              "production_connection_verified": False, "os_read_only_enforced": False,
              "source_hashes": before, "service_version": status["service_version"],
              "provider": status["provider"], "job_status": job["job"]["status"],
              "coverage": status["coverage"], "network_calls": status["network_calls"],
              "files": evidence, "source_unchanged": True}
    reader_report = target / "reader-evidence.json"
    if not reader_report.exists():
        new_json(reader_report, report)
    if args.reader_only:
        print(json.dumps({"ok": True, "reader_evidence": str(reader_report), "files": len(evidence)}, ensure_ascii=False))
        return 0
    flow_export = Path(evidence["fund_flows.csv"]["export_artifact"])
    exported_rows = [json.loads(line) for line in flow_export.read_text(encoding="utf-8").splitlines() if line]
    header, rows, row_locators = None, [], []
    for record in exported_rows:
        if record["source_version"] != evidence["fund_flows.csv"]["source_version"]:
            raise RuntimeError("Export record version differs from the inspected version")
        segment, ordinal = record["segment"], record["ordinal"]
        if segment.get("warnings") or segment["locator"].get("part") != 1:
            raise RuntimeError("This fixed-fixture adapter requires complete single-part rows")
        values = [cell["value"] for cell in segment["data"]["cells"]]
        if ordinal == 0:
            header = values
            if len(header) != len(set(header)):
                raise RuntimeError("Duplicate column in the exported header")
            continue
        if header is None or len(values) != len(header):
            raise RuntimeError("Incomplete exported row")
        row = dict(zip(header, values))
        if row["month"] != "2026-10" or row["currency"] != "CNY":
            raise RuntimeError("Unexpected test period or currency")
        row["net_inflow"] = str(Decimal(row["creation_amount"]) - Decimal(row["redemption_amount"]))
        rows.append(row)
        row_locators.append({"product_id": row["product_id"], "locator": segment["locator"]})
    expected = {"SYN-A": Decimal("900"), "SYN-B": Decimal("-150"), "SYN-C": Decimal("300")}
    actual_flows = {row["product_id"]: Decimal(row["net_inflow"]) for row in rows}
    if len(rows) != 3 or actual_flows != expected:
        raise RuntimeError("Independently calculated flows differ from the fixture expectations")
    derived = target / "derived"
    derived.mkdir(exist_ok=True)
    derived_csv = derived / "fund_flows_from_export.csv"
    if not derived_csv.exists():
        with derived_csv.open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=[*header, "net_inflow"])
            writer.writeheader()
            writer.writerows(rows)
    else:
        with derived_csv.open(encoding="utf-8-sig", newline="") as stream:
            if list(csv.DictReader(stream)) != rows:
                raise RuntimeError("Existing derived file differs from the verified export")
    derivation = {"input_artifact": str(flow_export), "input_sha256": sha256(flow_export),
                  "source_version": evidence["fund_flows.csv"]["source_version"],
                  "algorithm": "Read structured export segment.data.cells; first row is header; Decimal(creation_amount) - Decimal(redemption_amount); retain negative values",
                  "period": "2026-10", "currency": "CNY", "unit": "yuan", "rows": row_locators,
                  "expected_flows": {key: str(value) for key, value in expected.items()},
                  "expected_total": str(sum(expected.values())), "output_sha256": sha256(derived_csv)}
    if not (derived / "derivation.json").exists():
        new_json(derived / "derivation.json", derivation)
    result_dir = target / "analysis" / "net-flows-001"
    data_cli = args.data_skill / "scripts" / "run.py"
    analysis = call("datalab-analyze", data_cli, ["analyze", "--input", derived_csv, "--out", result_dir,
                    "--metric", "net_inflow", "--group", "product_id", "--agg", "sum",
                    "--unit", "currency", "--currency", "CNY", "--precision", "0", "--no-charts",
                    "--title", "Synthetic October 2026 net flows"])
    bundle = read_json(result_dir / "result.json")
    checks = read_json(result_dir / "checks.json")
    if checks.get("checks_status") != "passed":
        raise RuntimeError("DataLab automatic checks did not pass; preserve the result for review")
    grouped = next(table for table in bundle["tables"] if table["id"] == "by_group")
    key_index, value_index = grouped["columns"].index("product_id"), grouped["columns"].index("指标值")
    observed = {row[key_index]: Decimal(str(row[value_index])) for row in grouped["rows"]}
    observed_total = Decimal(str(bundle["metric"]["value"]))
    if observed != expected or observed_total != sum(expected.values()):
        raise RuntimeError("Actual DataLab bundle differs from independently computed expected flows")
    observed_check = {"observed_at": datetime.now(timezone.utc).isoformat(), "passed": True,
                      "result_sha256": sha256(result_dir / "result.json"),
                      "by_group": {key: str(value) for key, value in observed.items()},
                      "total": str(observed_total), "negative_value_preserved": observed["SYN-B"] == Decimal("-150"),
                      "native_checks_status": checks["checks_status"], "native_status": checks["status"]}
    if not (target / "analysis-verification.json").exists():
        new_json(target / "analysis-verification.json", observed_check)
    public_cases = project / "plugins" / "df-agent" / "skills" / "df-agent" / "references" / "public-examples" / "cases.jsonl"
    public_profile = public_cases.with_name("profile.json")
    if not public_cases.is_file() or not public_profile.is_file():
        raise RuntimeError("Explicit public style fixture is incomplete")
    style_rows = [json.loads(line) for line in public_cases.read_text(encoding="utf-8").splitlines() if line]
    if any(row.get("source", {}).get("kind") != "synthetic" or row.get("preference") != "unrated" for row in style_rows):
        raise RuntimeError("Unexpected nonpublic or rated style example")
    profile = read_json(public_profile)
    if profile.get("style_preferences") or profile.get("feedback"):
        raise RuntimeError("Public profile contains unexpected preferences")
    selection = call("etf-public-selection", args.etf_skill / "scripts" / "select_examples.py",
                     ["--library", public_cases, "--query", "月度净流入 申购 赎回 数字比较", "--limit", "6"])
    handoff = {"scope": "Three internal simulation comments only; all products and numbers are fictional",
               "period": "2026-10", "currency": "CNY", "unit": "yuan", "draft_count": 3,
               "facts": [{"product_id": key, "net_inflow": str(value)} for key, value in actual_flows.items()],
               "total": str(sum(actual_flows.values())), "evidence_bundle": str(result_dir / "result.json"),
               "reader_evidence": str(reader_report), "source_locators": row_locators,
               "public_style_file": str(public_cases), "private_library_read": False,
               "native_validation": bundle["validation"],
               "limitations": ["Synthetic local provider only", "No performance or real product claims", "Automatic numerical checks do not certify prose"]}
    if not (target / "etf-handoff.json").exists():
        new_json(target / "etf-handoff.json", handoff)
    report["analysis"] = {"result": str(result_dir / "result.json"), "checks": str(result_dir / "checks.json"),
                          "source_sha256": sha256(derived_csv), "checks_status": checks["checks_status"],
                          "status": checks["status"], "expected_net_flows": derivation["expected_flows"],
                          "expected_total": derivation["expected_total"]}
    report["style_selection"] = {"explicit_public_library": True, "private_library_read": False,
                                 "examples": len(selection["examples"]), "script_log": str(logs / "etf-public-selection.json")}
    report["drafting"] = {"handoff": str(target / "etf-handoff.json"),
                          "status": "Agent drafts and reviews three comments from this handoff; no generic Skill invocation API is assumed"}
    report["source_unchanged"] = {name: sha256(source / name) for name in FILES} == before
    if not report["source_unchanged"]:
        raise RuntimeError("Source changed during analysis")
    summary_path = target / "integration-evidence.json"
    if not summary_path.exists():
        new_json(summary_path, report)
    print(json.dumps({"ok": True, "integration_evidence": str(summary_path),
                      "draft_handoff": str(target / "etf-handoff.json"), "checks_status": checks["checks_status"],
                      "status": checks["status"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
