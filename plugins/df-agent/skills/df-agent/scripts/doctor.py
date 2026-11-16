#!/usr/bin/env python3
"""Bounded, read-only DF Agent inventory. Never runs a discovered skill."""
from __future__ import annotations

import sys
sys.dont_write_bytecode = True

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import subprocess
from datetime import datetime, timedelta, timezone

_ACCESS_SPEC = importlib.util.spec_from_file_location("df_agent_doctor_access", Path(__file__).with_name("access.py"))
access = importlib.util.module_from_spec(_ACCESS_SPEC)
_ACCESS_SPEC.loader.exec_module(access)

SCHEMA = "team-advisor-capabilities/1"
STATES = {"passed", "failed", "not_checked", "not_applicable", "unknown"}
CHECKS = ("filesystem", "host_discovery", "resource_access", "dependencies", "smoke_test")
EXTERNAL_CHECKS = {"host_discovery", "dependencies", "smoke_test"}
MAX_BYTES = 2_000_000
MAX_CHILDREN = 256
ENV_KEYS = ("host_product", "client_version", "task_mode", "execution_mode",
            "execution_environment", "local_access", "shell", "repo_commit")
PROFILES = {
    "data-lab.sum_table": {
        "resources": ("references/runtime.md", "references/platforms.md", "references/analysis.md",
                      "references/validation.md", "scripts/run.py"),
        "packages": ("pandas", "numpy", "tzdata")},
    "data-lab.chart": {
        "resources": ("references/runtime.md", "references/platforms.md", "references/charts.md",
                      "scripts/run.py", "scripts/datalab/charts.py"),
        "packages": ("pandas", "numpy", "matplotlib", "tzdata")},
    "data-lab.model": {
        "resources": ("references/runtime.md", "references/platforms.md", "references/modeling.md",
                      "scripts/run.py", "scripts/datalab/modeling.py"),
        "packages": ("pandas", "numpy", "scipy", "scikit-learn", "tzdata")},
    "data-lab.word": {
        "resources": ("references/runtime.md", "references/platforms.md", "references/word.md",
                      "scripts/run.py", "scripts/datalab/word_report.py"),
        "packages": ("pandas", "numpy", "python-docx", "tzdata")},
    "df-mcp.lookup": {
        "resources": ("references/requirements.md", "references/sop.md", "references/tools.md",
                      "references/formats.md"), "packages": ()},
    "etf-comment-drafts-v2.draft": {
        "resources": ("references/contrasts.md", "references/private-library.md"), "packages": ()},
}
SKILLS = ("data-lab", "df-mcp", "etf-comment-drafts-v2")
DATALAB_CORE = tuple("scripts/datalab/" + name + ".py" for name in (
    "__init__", "cli", "analysis", "common", "grouping", "io", "metrics", "profile",
    "quality", "report", "settings", "statistics", "validation"))
# Public code only; no recursive walk, private examples, credentials, caches or vendor tree.
OPTIONAL = {
    "data-lab": tuple("scripts/datalab/" + name + ".py" for name in (
        "__init__", "__main__", "cli", "analysis", "charts", "common", "grouping", "io",
        "metrics", "modeling", "profile", "quality", "report", "settings", "statistics",
        "validation", "word_report", "safety", "dashboard")) + ("scripts/requirements.txt", "references/safety.md"),
    "df-mcp": ("scripts/df-tool.py", "scripts/df-check.py", "references/cli.md", "references/onboarding.md"),
    "etf-comment-drafts-v2": ("scripts/select_examples.py", "references/evaluation.md"),
}
DEFAULT_CONSTRAINTS = {"pandas": ">=2.2,<3", "numpy": ">=1.26,<3", "matplotlib": ">=3.8,<4",
                       "openpyxl": ">=3.1,<4", "python-docx": ">=1.1,<2", "scipy": ">=1.12,<2",
                       "scikit-learn": ">=1.4,<2", "tzdata": ">=2024.1"}


class CheckError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def stamp(value):
    if value is None:
        return
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise CheckError("Timestamp must be ISO 8601 with a timezone.") from None
    return parsed.astimezone(timezone.utc)


def absolute(path):
    return Path(os.path.abspath(os.fspath(path)))


def no_links(path):
    """Reject symlinks/reparse points in every existing component, including ancestors."""
    path = absolute(path)
    for part in reversed((path,) + tuple(path.parents)):
        try:
            details = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(details.st_mode) or getattr(details, "st_file_attributes", 0) & 0x400:
            raise CheckError("Symlink or reparse point rejected.")
    return path


def under(path, root):
    try:
        absolute(path).relative_to(absolute(root))
        return True
    except ValueError:
        return False


def read_bytes(path):
    path = no_links(path)
    with path.open("rb") as handle:
        value = handle.read(MAX_BYTES + 1)
    if len(value) > MAX_BYTES:
        raise CheckError("Public file exceeds the bounded read limit.")
    return value


def read_json(path):
    try:
        return json.loads(read_bytes(path).decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise CheckError("Input must be valid UTF-8 JSON.") from None


def public_strings(value):
    """Avoid accidental personal paths in generated or externally supplied evidence."""
    if isinstance(value, str):
        if re.search(r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|\\\\|/(?:Users|home)/)", value):
            raise CheckError("Shareable reports/evidence must use aliases, not personal absolute paths.")
    elif isinstance(value, dict):
        for key, item in value.items():
            public_strings(key)
            public_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            public_strings(item)


def write_json(path, value, roots=(), protected=(), *, write_access=None):
    destination = no_links(path)
    if any(under(destination, root) for root in roots):
        raise CheckError("Report output must be outside every source root.")
    if destination in [absolute(item) for item in protected if item]:
        raise CheckError("Report output cannot replace an input file.")
    access.require_write(write_access, destination, "output")
    public_strings(value)
    encoded = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    no_links(destination)
    try:
        with destination.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError:
        raise CheckError("Output already exists; choose a new report filename.") from None


def normalize_roots(roots):
    if not roots or len(roots) > 16:
        raise CheckError("Provide between 1 and 16 explicit source roots.")
    unique = []
    for root in roots:
        path = absolute(root)
        if path == Path(path.anchor):
            raise CheckError("A whole-drive/filesystem root is not an allowed skill root.")
        if path not in unique:
            unique.append(path)
    return unique


def check(status="not_checked", *evidence):
    return {"status": status, "evidence": list(evidence)}


def metadata(raw):
    text = raw.decode("utf-8-sig")
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---(?:\s*\r?\n|$)", text, re.S)
    if not match:
        raise CheckError("SKILL.md is missing YAML frontmatter.")
    fields = {}
    for key in ("name", "description"):
        found = re.findall(r"(?m)^" + key + r":\s*(.+?)\s*$", match.group(1))
        if len(found) != 1:
            raise CheckError("SKILL.md requires one name and one description.")
        fields[key] = found[0].strip().strip("\"'")
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", fields["name"]):
        raise CheckError("Skill name is not a supported logical identifier.")
    return fields


def discover(roots):
    candidates, coverage = [], []
    for number, root in enumerate(roots, 1):
        alias = f"ROOT_{number}"
        try:
            no_links(root)
            if not root.is_dir():
                raise CheckError("Source root is not a readable directory.")
            children = []
            with os.scandir(root) as entries:
                for entry in entries:
                    children.append(entry.name)
                    if len(children) > MAX_CHILDREN:
                        raise CheckError("Source root exceeds 256 direct entries; provide narrower roots.")
            for child_name in sorted(children):
                child = root / child_name
                try:
                    no_links(child)
                    if not child.is_dir():
                        continue
                    skill_file = child / "SKILL.md"
                    if not skill_file.exists() and child_name not in SKILLS:
                        continue
                    raw = read_bytes(skill_file)
                    info = metadata(raw)
                    skill_id = info["name"]
                    if skill_id not in SKILLS:
                        if child_name not in SKILLS:
                            continue
                        raise CheckError("Expected skill directory contains a different logical name.")
                    candidates.append({"skill_id": skill_id, "directory": child,
                                       "source_ref": f"{alias}/{child_name}/SKILL.md", "raw": raw})
                except (OSError, CheckError, UnicodeError) as exc:
                    if child_name in SKILLS:
                        candidates.append({"skill_id": child_name, "directory": child,
                                           "source_ref": f"{alias}/{child_name}/SKILL.md",
                                           "error": type(exc).__name__})
                    else:
                        coverage.append(f"{alias}/{child_name}: skipped unreadable or linked candidate")
        except (OSError, CheckError) as exc:
            coverage.append(f"{alias}: bounded scan incomplete ({type(exc).__name__})")
    return candidates, coverage


def probe_python(executable):
    if not executable:
        return None
    path = no_links(executable)
    if not path.is_file():
        return {"error": "interpreter_not_found"}
    code = """import importlib.metadata as m,json,platform,sys
names=['pandas','numpy','matplotlib','openpyxl','python-docx','scipy','scikit-learn','tzdata']
versions={}
for name in names:
 try: versions[name]=m.version(name)
 except m.PackageNotFoundError: versions[name]=None
print(json.dumps({'python':list(sys.version_info[:3]),'implementation':platform.python_implementation(),'packages':versions}))
"""
    try:
        run = subprocess.run([str(path), "-X", "utf8", "-B", "-I", "-c", code], capture_output=True,
                             text=True, encoding="utf-8", timeout=20, check=False)
        if run.returncode or len(run.stdout) > 32_768:
            return {"error": "interpreter_probe_failed"}
        return json.loads(run.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"error": "interpreter_probe_failed"}


def version_tuple(value):
    if not re.fullmatch(r"\d+(?:\.\d+)*", value):
        raise CheckError("Unsupported non-numeric version; requires manual dependency evidence.")
    parts = tuple(map(int, value.split(".")))
    return parts + (0,) * (6 - len(parts))


def compatible(version, expression):
    current = version_tuple(version)
    if not expression.strip():
        return True
    for term in expression.split(","):
        item = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)\s*", term)
        if not item:
            raise CheckError("Unsupported requirement constraint; requires manual dependency evidence.")
        operator, number = item.groups()
        expected = version_tuple(number)
        outcome = {">=": current >= expected, "<=": current <= expected, "==": current == expected,
                   ">": current > expected, "<": current < expected}[operator]
        if not outcome:
            return False
    return True


def dependency_check(skill_id, profile, probe, directory):
    if skill_id == "etf-comment-drafts-v2":
        return check("not_applicable", "Public-reference drafting does not require Python or a private library.")
    if skill_id == "df-mcp":
        return check("unknown", "A real reader connection and approved source must be tested separately; no status/index command was run.")
    if probe is None:
        return check("not_checked", "No explicit task Python interpreter was supplied.")
    if probe.get("error"):
        return check("failed", probe["error"])
    if tuple(probe["python"]) < (3, 11, 0):
        return check("failed", "DataLab requires Python 3.11 or newer.")
    constraints = DEFAULT_CONSTRAINTS.copy()
    unsupported_include = False
    requirement_file = directory / "scripts/requirements.txt"
    try:
        if requirement_file.exists():
            declared = set()
            for line in read_bytes(requirement_file).decode("utf-8-sig").splitlines():
                line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith(("-r", "--requirement", "-c", "--constraint")):
                    unsupported_include = True
                    continue
                # Capture the package first: unsupported valid pip syntax such as
                # ~=, extras, markers or direct URLs must not fall back to defaults.
                match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)(.*)", line)
                if match:
                    package = re.sub(r"[-_.]+", "-", match[1]).lower()
                    if package in constraints:
                        constraint = match[2].strip()
                        if package not in declared:
                            constraints[package] = constraint
                        elif constraint:
                            constraints[package] = (constraints[package] + "," if constraints[package] else "") + constraint
                        declared.add(package)
    except (OSError, CheckError, UnicodeError):
        return check("unknown", "Could not safely parse the installed public dependency constraints.")
    evidence, failures, uncertain = [], [], ["unresolved requirements include"] if unsupported_include else []
    if unsupported_include:
        evidence.append("Requirements include/constraint files were not followed; their constraints need separate verification.")
    for package in PROFILES[profile]["packages"]:
        installed = probe["packages"].get(package)
        wanted = constraints[package]
        display_constraint = wanted if re.fullmatch(r"\s*(?:>=|<=|==|>|<)\s*\d+(?:\.\d+)*(?:\s*,\s*(?:>=|<=|==|>|<)\s*\d+(?:\.\d+)*)*\s*", wanted) else "unsupported constraint syntax" if wanted else "any installed version"
        evidence.append(f"{package}: {installed or 'not installed'}; required {display_constraint}")
        if installed is None:
            failures.append(package)
        else:
            try:
                if not compatible(installed, wanted):
                    failures.append(package)
            except CheckError:
                uncertain.append(package)
    evidence.append("Package metadata only; binary imports and business results are not tested by this probe.")
    return check("failed" if failures else "unknown" if uncertain else "passed", *evidence)


def record(candidate, profile, probe):
    timestamp = now()
    skill_id = candidate["skill_id"]
    directory = candidate["directory"]
    checks = {name: check() for name in CHECKS}
    checks["host_discovery"] = check("unknown", "No current-session host observation has been supplied.")
    limitations = ["Public fingerprint covers only the explicitly listed files; it is not a full installation hash."]
    fingerprint = None
    if candidate.get("error"):
        checks["filesystem"] = check("failed", "Candidate metadata/file could not be safely read: " + candidate["error"])
        checks["resource_access"] = check("not_checked", "Candidate metadata check failed.")
    else:
        checks["filesystem"] = check("passed", "Logical name and description parsed from readable UTF-8 SKILL.md.")
        files = {"SKILL.md": digest(candidate["raw"])}
        required = set(PROFILES[profile]["resources"])
        if skill_id == "data-lab":
            required.update(DATALAB_CORE)
        missing = []
        for relative in sorted(required | set(OPTIONAL[skill_id])):
            resource = directory / relative
            try:
                if not resource.exists() and relative not in required:
                    continue
                files[relative] = digest(read_bytes(resource))
            except (OSError, CheckError):
                if relative in required:
                    missing.append(relative)
                else:
                    limitations.append("Optional public file skipped: " + relative)
        fingerprint = {"algorithm": "sha256", "files": files}
        checks["resource_access"] = check("failed", *("Required public resource unavailable: " + name for name in missing)) if missing else check("passed", "All task-profile public resources were read and hashed.")
        if skill_id == "etf-comment-drafts-v2":
            limitations.append("Use explicit approved library configuration or public references; do not run an implicit private-library lookup.")
    checks["dependencies"] = dependency_check(skill_id, profile, probe, directory)
    return {"skill_id": skill_id, "source_ref": candidate["source_ref"], "source_fingerprint": fingerprint,
            "access_mode": "native_skill", "task_profile": profile, "checks": checks,
            "execution_ready": None, "blockers": [], "limitations": limitations, "checked_at": timestamp}


def readiness(item, ambiguous=False):
    required = list(CHECKS)
    if item["access_mode"] == "explicit_file_playbook":
        required.remove("host_discovery")
    failures = [name for name in required if item["checks"][name]["status"] == "failed"]
    item["blockers"] = ["Required check failed: " + name for name in failures]
    if failures:
        return False
    if ambiguous:
        return None
    for name in required:
        status = item["checks"][name]["status"]
        if status != "passed" and not (name == "dependencies" and status == "not_applicable" and item["skill_id"] == "etf-comment-drafts-v2"):
            return None
    return True


def select_sources(report, bindings=None):
    stored = report.get("source_bindings")
    if stored is None:
        # Preserve confirmed choices from reports produced before source_bindings
        # was added. Unresolved old bindings cannot be reconstructed reliably.
        stored = {"preferred_sources": {
            skill_id: selected["source_ref"] for skill_id, selected in report.get("source_selection", {}).items()
            if selected.get("reason") == "explicit_binding" and selected.get("source_ref")}}
    effective = bindings if bindings is not None else stored
    if not isinstance(effective, dict) or set(effective) != {"preferred_sources"}:
        raise CheckError("Bindings require exactly the preferred_sources object.")
    preferences = effective["preferred_sources"]
    if not isinstance(preferences, dict) or any(key not in SKILLS for key in preferences):
        raise CheckError("Bindings must use known skill IDs in preferred_sources.")
    public_strings(preferences)
    for reference in preferences.values():
        if not isinstance(reference, str) or not re.fullmatch(r"ROOT_[1-9]\d*/[^/]+/SKILL\.md", reference) or "\\" in reference or ".." in PurePosixPath(reference).parts:
            raise CheckError("Bindings must use root aliases and a direct candidate SKILL.md reference.")
    previous = stored.get("preferred_sources", {})
    if bindings is not None and preferences != previous:
        report.setdefault("binding_history", []).append({"changed_at": now(), "previous": copy.deepcopy(previous), "current": copy.deepcopy(preferences)})
    report["source_bindings"] = {"preferred_sources": copy.deepcopy(preferences)}
    selection = {}
    for skill_id in SKILLS:
        items = [item for item in report["skills"] if item["skill_id"] == skill_id]
        references = sorted({item["source_ref"] for item in items if item["source_ref"] and item["checks"]["filesystem"]["status"] == "passed"})
        discovered = sorted({item["source_ref"] for item in items if item["source_ref"] in references and item["checks"]["host_discovery"]["status"] == "passed"})
        preferred = preferences.get(skill_id)
        if preferred:
            chosen = preferred if preferred in references else None
            reason = "explicit_binding" if chosen else "binding_not_found_or_unreadable"
        elif len(discovered) == 1:
            chosen, reason = discovered[0], "unique_host_observed_source"
        elif len(references) == 1:
            chosen, reason = references[0], "unique_candidate_pending_task_checks"
        else:
            chosen, reason = None, "ambiguous_sources" if len(references) > 1 else "no_readable_candidate"
        ambiguous = reason in {"ambiguous_sources", "binding_not_found_or_unreadable"}
        selection[skill_id] = {"status": "selected" if chosen else "ambiguous" if ambiguous else "unavailable",
                               "source_ref": chosen, "reason": reason}
        for item in items:
            item["limitations"] = [value for value in item["limitations"] if value != "Source choice unresolved; confirm a source binding."]
            if ambiguous:
                item["limitations"].append("Source choice unresolved; confirm a source binding.")
            item["execution_ready"] = readiness(item, ambiguous)
    report["source_selection"] = selection
    return report


def environment_values(provided=None):
    values = {key: "unknown" for key in ENV_KEYS}
    if provided:
        if not isinstance(provided, dict) or set(provided) - set(ENV_KEYS):
            raise CheckError("Environment JSON has unsupported fields.")
        if any(not isinstance(value, str) for value in provided.values()):
            raise CheckError("Environment fields must be strings.")
        values.update(provided)
    values["execution_environment"] = "windows_native" if os.name == "nt" else "wsl" if os.environ.get("WSL_DISTRO_NAME") else "unix_local"
    public_strings(values)
    return values


def scan(roots, python=None, environment=None, session_id="unspecified", bindings=None):
    roots = normalize_roots(roots)
    candidates, coverage = discover(roots)
    probe = probe_python(python)
    env = environment_values(environment)
    env["local_access"] = "verified_available" if candidates else "unknown"
    context = {"session_id": session_id,
               "scope_fingerprint": digest({"computer": platform.node(), "roots": [str(root) for root in roots]}),
               "runtime_fingerprint": digest({"python": str(absolute(python)), "probe": probe}) if python else None}
    public_strings(context)
    report = {"schema_version": SCHEMA, "tested_at": now(), "environment": env,
              "observation_context": context, "skills": [], "coverage_limitations": coverage}
    for profile in PROFILES:
        skill_id = profile.rsplit(".", 1)[0]
        matches = [candidate for candidate in candidates if candidate["skill_id"] == skill_id]
        if matches:
            report["skills"].extend(record(candidate, profile, probe) for candidate in matches)
        else:
            item = {"skill_id": skill_id, "source_ref": None, "source_fingerprint": None,
                    "access_mode": "native_skill", "task_profile": profile,
                    "checks": {name: check() for name in CHECKS}, "execution_ready": None,
                    "blockers": [], "limitations": ["No matching candidate in the bounded approved scope; other locations were not checked."],
                    "checked_at": now()}
            item["checks"]["filesystem"] = check("unknown" if coverage else "failed", "No matching candidate was observed in the declared roots.")
            item["checks"]["host_discovery"] = check("unknown", "Host discovery was not observed.")
            report["skills"].append(item)
    return select_sources(report, bindings)


def validate(report):
    if not isinstance(report, dict) or report.get("schema_version") != SCHEMA:
        raise CheckError("Unsupported capability report schema.")
    stamp(report.get("tested_at"))
    if set(report.get("environment", {})) != set(ENV_KEYS):
        raise CheckError("Report environment does not match the contract.")
    context = report.get("observation_context", {})
    if set(context) != {"session_id", "scope_fingerprint", "runtime_fingerprint"}:
        raise CheckError("Report is missing its observation context.")
    if not isinstance(context["session_id"], str) or not re.fullmatch(r"[a-f0-9]{64}", context.get("scope_fingerprint", "")):
        raise CheckError("Invalid observation context.")
    if context["runtime_fingerprint"] is not None and not re.fullmatch(r"[a-f0-9]{64}", context["runtime_fingerprint"]):
        raise CheckError("Invalid runtime fingerprint.")
    seen = set()
    if not isinstance(report.get("skills"), list):
        raise CheckError("Report skills must be a list.")
    if set(report.get("source_selection", {})) != set(SKILLS):
        raise CheckError("Report requires an explicit source-selection result for every logical skill.")
    for item in report["skills"]:
        profile = item.get("task_profile")
        if profile not in PROFILES or item.get("skill_id") != profile.rsplit(".", 1)[0]:
            raise CheckError("Unknown or inconsistent task profile.")
        ref = item.get("source_ref")
        if ref is not None and (not re.fullmatch(r"ROOT_[1-9]\d*/[^/]+/SKILL\.md", ref) or ".." in PurePosixPath(ref).parts or "\\" in ref):
            raise CheckError("Invalid source reference.")
        identity = (ref, profile)
        if identity in seen:
            raise CheckError("Duplicate source/profile record.")
        seen.add(identity)
        if item.get("access_mode") not in {"native_skill", "explicit_file_playbook"}:
            raise CheckError("Unknown access mode.")
        if set(item.get("checks", {})) != set(CHECKS):
            raise CheckError("Report checks do not match the five-layer contract.")
        for name, value in item["checks"].items():
            if value.get("status") not in STATES or not isinstance(value.get("evidence"), list) or not all(isinstance(reason, str) for reason in value["evidence"]):
                raise CheckError("Invalid check status/evidence.")
            if value["status"] in {"passed", "failed", "not_applicable"} and not value["evidence"]:
                raise CheckError("Conclusive checks require evidence.")
            if value["status"] == "not_applicable" and not (name == "dependencies" and item["skill_id"] == "etf-comment-drafts-v2"):
                raise CheckError("A required check cannot be bypassed with not_applicable.")
            observed_time = stamp(value.get("observed_at"))
            if observed_time and observed_time > datetime.now(timezone.utc) + timedelta(seconds=60):
                raise CheckError("A check observation cannot be in the future beyond clock tolerance.")
            if name in {"host_discovery", "smoke_test"} and value["status"] in {"passed", "failed"} and observed_time is None:
                raise CheckError("Conclusive host/task observations require per-check observed_at; re-observe legacy merged reports.")
        fingerprint = item.get("source_fingerprint")
        if fingerprint is not None:
            if fingerprint.get("algorithm") != "sha256" or "SKILL.md" not in fingerprint.get("files", {}):
                raise CheckError("Invalid source fingerprint.")
            for relative, sha in fingerprint["files"].items():
                if PurePosixPath(relative).is_absolute() or ".." in PurePosixPath(relative).parts or "\\" in relative or not re.fullmatch(r"[a-f0-9]{64}", sha):
                    raise CheckError("Fingerprint paths must remain within the skill.")
        elif item["checks"]["filesystem"]["status"] == "passed":
            raise CheckError("Readable sources require a fingerprint.")
        stamp(item.get("checked_at"))
        selected = report.get("source_selection", {}).get(item["skill_id"], {})
        expected = readiness(copy.deepcopy(item), selected.get("status") == "ambiguous")
        if item.get("execution_ready") is not expected:
            raise CheckError("execution_ready contradicts the necessary checks or source ambiguity.")
    for skill_id, selection in report["source_selection"].items():
        if selection.get("status") not in {"selected", "ambiguous", "unavailable"}:
            raise CheckError("Invalid source-selection state.")
        if selection["status"] == "selected":
            if not any(item["skill_id"] == skill_id and item["source_ref"] == selection.get("source_ref") and item["checks"]["filesystem"]["status"] == "passed" for item in report["skills"]):
                raise CheckError("Selected source is not a readable candidate.")
        elif selection.get("source_ref") is not None:
            raise CheckError("An unresolved selection cannot point at a chosen source.")
    stored_bindings = report.get("source_bindings")
    if stored_bindings is not None:
        if not isinstance(stored_bindings, dict) or set(stored_bindings) != {"preferred_sources"} or not isinstance(stored_bindings["preferred_sources"], dict):
            raise CheckError("Invalid persisted source bindings.")
        for skill_id, reference in stored_bindings["preferred_sources"].items():
            if skill_id not in SKILLS or not isinstance(reference, str) or not re.fullmatch(r"ROOT_[1-9]\d*/[^/]+/SKILL\.md", reference) or "\\" in reference or ".." in PurePosixPath(reference).parts:
                raise CheckError("Invalid persisted source binding reference.")
            selection = report["source_selection"][skill_id]
            if selection.get("reason") == "explicit_binding" and selection.get("source_ref") != reference:
                raise CheckError("Selected source contradicts its persisted confirmed binding.")
            if selection.get("reason") not in {"explicit_binding", "binding_not_found_or_unreadable"}:
                raise CheckError("A confirmed binding must retain priority over automatic source selection.")
    for change in report.get("binding_history", []):
        stamp(change.get("changed_at"))
        if not isinstance(change.get("previous"), dict) or not isinstance(change.get("current"), dict):
            raise CheckError("Invalid source binding change record.")
    public_strings(report)
    return True


def merge(report, evidence, bindings=None):
    validate(report)
    if report["observation_context"]["session_id"] == "unspecified":
        raise CheckError("Set an explicit scan --session-id before adding observed host or task evidence.")
    if evidence.get("environment") != report["environment"] or evidence.get("observation_context") != report["observation_context"]:
        raise CheckError("Evidence environment/context mismatch; observe this session and runtime again.")
    observed_time = stamp(evidence.get("observed_at"))
    if not evidence.get("observed_at"):
        raise CheckError("Evidence requires an observed_at timestamp.")
    if observed_time > datetime.now(timezone.utc) + timedelta(seconds=60):
        raise CheckError("Evidence observation cannot be in the future beyond clock tolerance.")
    updated = copy.deepcopy(report)
    by_key = {(item["source_ref"], item["task_profile"]): item for item in updated["skills"]}
    evidence_items = evidence.get("skills", [])
    if not isinstance(evidence_items, list) or not evidence_items:
        raise CheckError("Evidence must contain observed skill records.")
    seen = set()
    for observed in evidence_items:
        key = (observed.get("source_ref"), observed.get("task_profile"))
        if key in seen:
            raise CheckError("Duplicate source/profile in evidence; resolve conflicting observations first.")
        seen.add(key)
        item = by_key.get(key)
        if item is None or item["source_fingerprint"] is None or observed.get("source_fingerprint") != item["source_fingerprint"]:
            raise CheckError("Evidence source/profile/fingerprint mismatch; repeat affected observations.")
        for name, value in observed.get("checks", {}).items():
            if name not in EXTERNAL_CHECKS:
                raise CheckError("External evidence cannot replace static filesystem/resource checks.")
            if name == "dependencies" and item["checks"][name]["status"] == "failed" and value.get("status") != "failed":
                raise CheckError("Evidence cannot override an observed interpreter/declared-package failure.")
            check_time = stamp(value.get("observed_at", evidence["observed_at"]))
            if check_time is None or check_time > observed_time:
                raise CheckError("A check observation needs a timestamp no later than its evidence batch.")
            prior_time = stamp(item["checks"][name].get("observed_at"))
            if prior_time and check_time < prior_time:
                raise CheckError("An older check observation cannot replace a newer observed result.")
            if prior_time and check_time == prior_time and value.get("status") != item["checks"][name]["status"]:
                raise CheckError("Conflicting check states at the same observation time must be resolved explicitly.")
            item["checks"][name] = copy.deepcopy(value)
            item["checks"][name]["observed_at"] = check_time.isoformat()
        if "access_mode" in observed:
            if observed["access_mode"] != item["access_mode"]:
                # Only this explicit evidence changes the execution mode, never the host discovery status.
                item["access_mode"] = observed["access_mode"]
        item["checked_at"] = max(stamp(item["checked_at"]) or observed_time, observed_time).isoformat()
    updated["tested_at"] = now()
    select_sources(updated, bindings)
    validate(updated)
    return updated


def current_report(previous, roots, python, bindings=None):
    """Recheck public source bytes and runtime before accepting older observations."""
    current = scan(roots, python, previous["environment"], previous["observation_context"]["session_id"], bindings)
    if current["observation_context"] != previous["observation_context"] or current["environment"] != previous["environment"]:
        raise CheckError("Scope/runtime/environment changed; collect a new report and new evidence.")
    old = {(item["source_ref"], item["task_profile"]): item for item in previous["skills"]}
    fresh = {(item["source_ref"], item["task_profile"]): item for item in current["skills"]}
    if set(old) != set(fresh):
        raise CheckError("Skill candidates changed; collect a new report and new evidence.")
    for key, item in fresh.items():
        prior = old[key]
        if item["source_fingerprint"] != prior["source_fingerprint"]:
            raise CheckError("Public skill resources changed; repeat affected observations.")
        for name in ("filesystem", "resource_access"):
            if item["checks"][name]["status"] != prior["checks"][name]["status"]:
                raise CheckError("Source access changed; repeat affected observations.")
    return previous


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    access.add_write_arguments(parser)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("scan", help="Read bounded public files; do not run discovered skills")
    combine = commands.add_parser("merge-evidence", help="Recheck sources and merge same-context observations")
    for child in (collect, combine):
        child.add_argument("--roots", nargs="+", required=True)
        child.add_argument("--output", help="New file in an explicitly authorized output directory; omit for stdout")
        child.add_argument("--python", help="Explicit interpreter to probe for task dependencies")
        child.add_argument("--bindings", help="External JSON containing preferred_sources")
    collect.add_argument("--environment", help="Explicit current-session environment metadata JSON")
    collect.add_argument("--session-id", default="unspecified")
    collect.add_argument("--host-evidence", help="Same-context evidence from a prior unchanged scan")
    combine.add_argument("--report", required=True)
    combine.add_argument("--evidence", required=True)
    verify = commands.add_parser("validate", help="Validate consistency only; does not re-observe files")
    verify.add_argument("--report", required=True)
    args = parser.parse_args(argv)
    try:
        write_access = access.from_args(args)
        if args.command == "validate":
            validate(read_json(args.report))
            print(json.dumps({"valid": True, "scope": "schema and internal consistency only"}))
            return 0
        bindings = read_json(args.bindings) if args.bindings else None
        if args.command == "scan":
            report = scan(args.roots, args.python, read_json(args.environment) if args.environment else None,
                          args.session_id, bindings)
            if args.host_evidence:
                report = merge(report, read_json(args.host_evidence), bindings)
            protected = (args.bindings, args.environment, args.host_evidence)
        else:
            report = read_json(args.report)
            validate(report)
            current_report(report, args.roots, args.python, bindings)
            report = merge(report, read_json(args.evidence), bindings)
            protected = (args.report, args.evidence, args.bindings)
        validate(report)
        if args.output:
            write_json(args.output, report, normalize_roots(args.roots), protected, write_access=write_access)
            result = {"written": True, "profiles": len(report["skills"]),
                      "ready": sum(item["execution_ready"] is True for item in report["skills"]),
                      "note": "Report creation succeeded; this is not a claim that every skill is ready."}
        else:
            result = report
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (CheckError, access.AccessError, OSError, KeyError, TypeError, ValueError) as exc:
        # No raw OS exception paths/credential-bearing command output in shared logs.
        message = str(exc) if isinstance(exc, (CheckError, access.AccessError)) else type(exc).__name__
        print(json.dumps({"error": message}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
