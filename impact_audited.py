#!/usr/bin/env python3
"""Cross-check graph-backend callers against a deterministic text-scan floor.

Languages: Python, Rust, TypeScript, JavaScript (including JSX/TSX, MJS, CJS),
and Go. Call-site detection is ``sym(`` minus definition lines and FULL-LINE
comments; trailing comments, block-comment interiors, and TS interface method
signatures are NOT excluded (known over-count sources, same as plain grep).
Vendored/build dirs (node_modules/target/.venv/...) are pruned from both
detection and the floor so that asymmetric pruning never turns vendored call
sites into false AUDIT FAILED.

Fail-closed rules (v0.3.0):
- A graph backend that exits 0 but reports an error envelope ("ambiguous",
  "not found", a JSON ``error`` key, ...) is a backend failure (exit 3), not an
  empty caller list. See ``backend_failure_reason``.
- In the default ``text`` graph format a path mention cannot distinguish "this
  file calls the symbol" from "this is where the symbol is defined" (tools echo
  the target's own location). A baseline caller that also *declares* the symbol
  (same-file call) is therefore UNVERIFIED (exit 5) unless a structured graph
  format (``lines`` or ``gitnexus``) lists it as a caller.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

__version__ = "0.3.0"

EXIT_PASS = 0
EXIT_OMISSION = 2
EXIT_BACKEND_FAILURE = 3
EXIT_INVALID_CONFIG = 4
EXIT_UNVERIFIED = 5

GRAPH_FORMATS = ("text", "lines", "gitnexus")

# Default failure markers, matched in backend stdout as standalone words (not as
# part of a path such as ``src/ambiguous.ts``). Disable with
# --no-default-fail-markers; add more with --graph-fail-pattern.
_TOKEN_LEFT = r"(?<![\w./\\-])"
_TOKEN_RIGHT = r"(?![\w./\\-])"
DEFAULT_FAILURE_MARKERS = (
    re.compile(rf"(?i){_TOKEN_LEFT}ambiguous{_TOKEN_RIGHT}"),
    re.compile(rf"(?i){_TOKEN_LEFT}not\s+found{_TOKEN_RIGHT}"),
)
JSON_FAILURE_STATUSES = {"ambiguous", "error", "failed", "failure", "not_found", "not found"}

SUPPORTED_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".rs", ".go")
JSX_EXTENSIONS = {".tsx", ".jsx"}
SKIPPED_DIRECTORIES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
    "venv",
}


class AuditArgumentParser(argparse.ArgumentParser):
    """Use the documented invalid-input exit code instead of argparse's default 2."""

    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(EXIT_INVALID_CONFIG, f"{self.prog}: error: {message}\n")


class BackendFailure(RuntimeError):
    """The configured graph backend did not produce a usable successful result."""

    def __init__(self, message, returncode=None, stdout="", stderr=""):
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def count_tokens(text):
    try:
        import tiktoken

        return len(tiktoken.get_encoding("cl100k_base").encode(text))
    except Exception:
        return None


def _raise_walk_error(error):
    raise error


def source_files(root):
    """Yield supported source files as (absolute path, POSIX relative path)."""
    for directory, dirnames, filenames in os.walk(root, onerror=_raise_walk_error):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIPPED_DIRECTORIES)
        for filename in sorted(filenames):
            path = Path(directory, filename)
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                yield path, path.relative_to(root).as_posix()


def files_in_text(text, root):
    """Return supported source paths that a graph backend mentioned.

    Relative and absolute paths are accepted. A bare basename is accepted only
    when it identifies exactly one supported source file in the repository.
    """
    normalized = text.replace("\\", "/")
    candidates = list(source_files(root))
    by_basename = {}
    for path, relative in candidates:
        by_basename.setdefault(path.name, []).append(relative)

    found = set()
    for path, relative in candidates:
        absolute = path.resolve().as_posix()
        if (
            _contains_path(normalized, relative)
            or _contains_path(normalized, f"./{relative}")
            or _contains_path(normalized, absolute)
        ):
            found.add(relative)
        elif len(by_basename[path.name]) == 1 and _contains_path(normalized, path.name):
            found.add(relative)
    return found


def _contains_path(text, path):
    """Match a path as a backend-output token, not as part of another path."""
    return bool(
        re.search(
            rf"(?<![\w./\\-]){re.escape(path)}(?![\w./\\-])",
            text,
        )
    )


def _is_definition_line(symbol, suffix, line):
    escaped = re.escape(symbol)
    if suffix == ".py":
        return bool(
            re.search(rf"\b(?:async\s+def|def|class)\s+{escaped}\b", line)
        )
    if suffix == ".rs":
        return bool(
            re.search(
                rf"\b(?:fn|struct|enum|trait|mod|macro_rules!)\s+{escaped}\b", line
            )
        )
    if suffix == ".go":
        return bool(
            re.search(rf"\b(?:func|type)\s+{escaped}\b", line)
        )
    return bool(
        re.search(rf"\b(?:function|class)\s+{escaped}\b", line)
        or re.search(
            rf"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*"
            rf"{escaped}\s*\([^)]*\)\s*(?::[^={{]+)?\s*{{",
            line,
        )
    )


def _is_whole_line_comment(suffix, line):
    """Return True when the *entire* line is a comment (leading whitespace ignored).

    Only full-line comments are excluded; trailing comments on code lines are
    preserved (they are known over-count sources, same as plain grep, and are
    documented as such). Docstring / block-comment interiors are NOT excluded.

    Markers: Python uses ``#``; Rust, Go, and the JS/TS family use ``//``.
    """
    stripped = line.lstrip()
    if suffix == ".py":
        return stripped.startswith("#")
    return stripped.startswith("//")


def baseline_caller_files(symbol, root):
    """Find direct textual call sites, including JSX component references."""
    escaped = re.escape(symbol)
    call_re = re.compile(rf"(?<![\w$]){escaped}\s*\(")
    jsx_re = re.compile(rf"<\s*{escaped}(?=[\s/>.])")
    callers = set()
    matched_lines = []

    for path, relative in source_files(root):
        suffix = path.suffix.lower()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise ValueError(f"cannot read source file {relative}: {exc}") from exc

        for line_number, line in enumerate(lines, start=1):
            if _is_whole_line_comment(suffix, line):
                continue
            is_call = bool(call_re.search(line))
            is_jsx = suffix in JSX_EXTENSIONS and bool(jsx_re.search(line))
            if not (is_call or is_jsx) or _is_definition_line(symbol, suffix, line):
                continue
            callers.add(relative)
            matched_lines.append(f"{relative}:{line_number}:{line}")

    return callers, "\n".join(matched_lines)


def _is_declaration_line(symbol, suffix, line):
    """Broader than ``_is_definition_line``: any line that declares ``symbol``.

    Used only to decide whether a baseline caller file is also the symbol's own
    definition file (where a graph tool's echo of the target location would be
    indistinguishable from a caller entry in plain-text output). Over-matching
    here makes the audit stricter (more UNVERIFIED), never more lenient.
    """
    if _is_definition_line(symbol, suffix, line):
        return True
    escaped = re.escape(symbol)
    keyword = (
        r"\b(?:const|let|var|function\*?|class|interface|type|enum|namespace|"
        r"def|fn|struct|trait|mod|func|static|impl)\s+"
    )
    if re.search(rf"{keyword}{escaped}\b", line):
        return True
    if suffix == ".go" and re.search(rf"\bfunc\s*\([^)]*\)\s*{escaped}\s*\(", line):
        return True
    # ``sym = ...``, ``sym := ...``, ``sym: ...`` (class fields, object methods,
    # Python module-level assignments), with optional modifiers / ``self.``.
    return bool(
        re.search(
            rf"^\s*(?:(?:export|default|public|private|protected|static|readonly|async|pub)\s+)*"
            rf"(?:self\.|this\.)?{escaped}\s*(?::=|=(?!=)|:(?!:))",
            line,
        )
    )


def declaration_files(symbol, root):
    """Return files that appear to declare ``symbol`` (see ``_is_declaration_line``)."""
    found = set()
    for path, relative in source_files(root):
        suffix = path.suffix.lower()
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as exc:
            raise ValueError(f"cannot read source file {relative}: {exc}") from exc
        for line in lines:
            if _is_whole_line_comment(suffix, line):
                continue
            if _is_declaration_line(symbol, suffix, line):
                found.add(relative)
                break
    return found


def backend_failure_reason(stdout, stderr, extra_patterns=(), use_defaults=True):
    """Return why an exit-0 backend result is actually a failure, or None.

    Checks, in order:
    1. (defaults) stdout is a JSON object with a truthy ``error`` key, or a
       ``status`` in JSON_FAILURE_STATUSES (e.g. GitNexus ``"ambiguous"``).
    2. (defaults) stdout contains a standalone DEFAULT_FAILURE_MARKERS word.
    3. any user ``--graph-fail-pattern`` regex matches stdout or stderr.
    """
    if use_defaults:
        try:
            data = json.loads(stdout)
        except ValueError:
            data = None
        if isinstance(data, dict):
            if data.get("error"):
                return f"backend reported error: {data['error']}"
            status = data.get("status")
            if isinstance(status, str) and status.strip().lower() in JSON_FAILURE_STATUSES:
                message = data.get("message")
                return f"backend reported status {status!r}" + (f": {message}" if message else "")
        for marker in DEFAULT_FAILURE_MARKERS:
            match = marker.search(stdout)
            if match:
                return f"backend output contains failure marker {match.group(0)!r}"
    for pattern in extra_patterns:
        for stream_name, text in (("stdout", stdout), ("stderr", stderr)):
            match = pattern.search(text)
            if match:
                return (
                    f"backend {stream_name} matches --graph-fail-pattern "
                    f"{pattern.pattern!r} ({match.group(0)!r})"
                )
    return None


def gitnexus_caller_paths(stdout):
    """Parse ``gitnexus impact`` JSON; return the caller file paths it lists.

    Only ``byDepth`` entries count as callers; ``target`` (the symbol's own
    location) and ``candidates`` (ambiguity lists) never do. Anything other
    than a well-formed successful impact result is a BackendFailure.
    """
    try:
        data = json.loads(stdout)
    except ValueError as exc:
        raise BackendFailure(f"--graph-format gitnexus: stdout is not JSON ({exc})") from exc
    if not isinstance(data, dict):
        raise BackendFailure("--graph-format gitnexus: stdout is not a JSON object")
    if data.get("error"):
        raise BackendFailure(f"gitnexus reported error: {data['error']}")
    status = data.get("status")
    if status not in (None, "ok", "success"):
        message = data.get("message")
        raise BackendFailure(
            f"gitnexus reported status {status!r}" + (f": {message}" if message else "")
        )
    by_depth = data.get("byDepth")
    if not isinstance(by_depth, dict):
        raise BackendFailure("--graph-format gitnexus: result has no 'byDepth' object")
    paths = []
    for depth, entries in by_depth.items():
        if not isinstance(entries, list):
            raise BackendFailure(f"--graph-format gitnexus: byDepth[{depth!r}] is not a list")
        for entry in entries:
            file_path = entry.get("filePath") if isinstance(entry, dict) else None
            if not isinstance(file_path, str) or not file_path.strip():
                raise BackendFailure(
                    f"--graph-format gitnexus: byDepth[{depth!r}] entry has no filePath"
                )
            paths.append(file_path.strip())
    impacted = data.get("impactedCount")
    if isinstance(impacted, int) and impacted != len(paths):
        raise BackendFailure(
            f"--graph-format gitnexus: impactedCount={impacted} but byDepth lists "
            f"{len(paths)} entries (truncated or unrecognised output)"
        )
    return paths


def graph_caller_files(graph_raw, root, graph_format):
    """Map backend stdout to repo-relative caller files for the chosen format."""
    if graph_format == "text":
        return files_in_text(graph_raw, root)
    if graph_format == "gitnexus":
        paths = gitnexus_caller_paths(graph_raw)
    else:  # "lines": one caller path per non-empty line, authoritative
        paths = [line.strip() for line in graph_raw.splitlines() if line.strip()]
    found = set()
    for path_text in paths:
        matched = files_in_text(path_text, root)
        if matched:
            found |= matched
            continue
        candidate = Path(path_text)
        if not candidate.is_absolute():
            candidate = root / candidate
        if not candidate.exists():
            raise BackendFailure(
                f"--graph-format {graph_format}: caller path {path_text!r} is not a file "
                "in the repository"
            )
        # Existing file with an unsupported extension: outside the audit's scope.
    return found


def run_graph_backend(template, symbol, root, fail_patterns=(), default_markers=True):
    """Run the legacy shell-template backend at one documented trust boundary.

    SECURITY: ``shell=True`` is retained because ``--graph`` has historically
    supported shell templates and pipelines. The symbol is shell-quoted, but the
    template itself is executable code and must come from trusted configuration.
    """
    command = template.replace("{sym}", shlex.quote(symbol))
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise BackendFailure(f"could not start graph backend: {exc}") from exc

    if proc.returncode != 0:
        raise BackendFailure(
            f"graph backend exited with status {proc.returncode}",
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    if not proc.stdout.strip():
        raise BackendFailure(
            "graph backend produced no stdout",
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    reason = backend_failure_reason(proc.stdout, proc.stderr, fail_patterns, default_markers)
    if reason:
        raise BackendFailure(
            f"graph backend exited 0 but did not return a usable result ({reason})",
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )
    return proc.stdout


def build_parser():
    parser = AuditArgumentParser(
        prog="impact-audited",
        description="Cross-check a code-graph impact tool against a text-scan floor.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "PASS rule: every baseline caller file must be shown to be covered by the\n"
            "graph backend. In --graph-format text, a baseline caller that also declares\n"
            "the symbol (same-file call) cannot be told apart from the backend echoing\n"
            "the symbol's own location, so it is UNVERIFIED unless a structured format\n"
            "(lines, gitnexus) lists it as a caller.\n"
            "\n"
            "Backend failure: non-zero exit, empty stdout, or exit 0 with an error\n"
            "envelope (JSON 'error' key / failure 'status', or the standalone words\n"
            "'ambiguous' / 'not found' in stdout; see --no-default-fail-markers and\n"
            "--graph-fail-pattern).\n"
            "\n"
            "Exit codes: 0 PASS; 2 missing callers (FAIL); 3 graph backend failed;\n"
            "4 invalid configuration; 5 UNVERIFIED (no missing callers, but at least one\n"
            "caller could not be confirmed). 2 takes precedence over 5."
        ),
    )
    parser.add_argument("symbol", help="function, class, method, or JSX component name")
    parser.add_argument("--path", default=".", help="repository root (default: cwd)")
    parser.add_argument(
        "--graph",
        default=None,
        help=(
            "trusted graph-tool shell command template containing exactly one literal "
            "'{sym}' placeholder; it is replaced with the shell-quoted symbol and "
            "stdout is scanned for source paths"
        ),
    )
    parser.add_argument(
        "--graph-format",
        choices=GRAPH_FORMATS,
        default="text",
        help=(
            "how to read backend stdout: 'text' (default) scans for any source path; "
            "same-file callers are UNVERIFIED. 'lines' treats every non-empty line as "
            "one caller path (authoritative). 'gitnexus' parses `gitnexus impact` JSON "
            "and counts only byDepth entries as callers"
        ),
    )
    parser.add_argument(
        "--graph-fail-pattern",
        action="append",
        default=[],
        metavar="REGEX",
        help=(
            "extra Python regex; if it matches backend stdout or stderr the backend "
            "is treated as failed (exit 3). Repeatable"
        ),
    )
    parser.add_argument(
        "--no-default-fail-markers",
        action="store_true",
        help=(
            "disable the built-in exit-0 failure detection (JSON error/status envelope, "
            "standalone 'ambiguous' / 'not found' in stdout)"
        ),
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def _configuration_error(message, as_json=False):
    if as_json:
        print(
            json.dumps(
                {"error": "invalid_configuration", "message": message, "final_status": "FAIL"},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"impact-audited configuration error: {message}\nFinal: FAIL", file=sys.stderr)
    return EXIT_INVALID_CONFIG


def _backend_error(symbol, failure, baseline_files, as_json=False):
    detail = failure.stderr.strip() or failure.stdout.strip() or str(failure)
    if as_json:
        print(
            json.dumps(
                {
                    "symbol": symbol,
                    "error": "graph_backend_failed",
                    "message": str(failure),
                    "backend_exit_code": failure.returncode,
                    "backend_detail": detail,
                    "baseline_caller_count": len(baseline_files),
                    "graph_caller_count": None,
                    "missing_callers": None,
                    "final_status": "FAIL",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            f"impact-audited  «{symbol}»\n"
            f"Audited symbol: {symbol}\n"
            f"Baseline caller count: {len(baseline_files)}\n"
            "Graph caller count: N/A\n"
            "Missing callers: N/A (backend failed)\n"
            f"Graph backend error: {failure}\n"
            f"Backend detail: {detail or '(none)'}\n"
            "Final: FAIL",
            file=sys.stderr,
        )
    return EXIT_BACKEND_FAILURE


def main(argv=None):
    args = build_parser().parse_args(argv)
    symbol = args.symbol.strip()
    root = Path(args.path).expanduser().resolve()

    if not symbol:
        return _configuration_error("symbol must not be empty", args.json)
    if not root.exists():
        return _configuration_error(f"repository path does not exist: {root}", args.json)
    if not root.is_dir():
        return _configuration_error(f"repository path is not a directory: {root}", args.json)
    if args.graph is not None:
        placeholder_count = args.graph.count("{sym}")
        if placeholder_count != 1:
            return _configuration_error(
                "--graph must contain exactly one literal '{sym}' placeholder "
                f"(found {placeholder_count})",
                args.json,
            )
    elif (
        args.graph_format != "text" or args.graph_fail_pattern or args.no_default_fail_markers
    ):
        return _configuration_error(
            "--graph-format / --graph-fail-pattern / --no-default-fail-markers "
            "require --graph",
            args.json,
        )
    fail_patterns = []
    for pattern in args.graph_fail_pattern:
        try:
            fail_patterns.append(re.compile(pattern))
        except re.error as exc:
            return _configuration_error(
                f"invalid --graph-fail-pattern {pattern!r}: {exc}", args.json
            )

    try:
        baseline_files, baseline_raw = baseline_caller_files(symbol, root)
    except (OSError, ValueError) as exc:
        return _configuration_error(str(exc), args.json)

    graph_files = None
    graph_raw = ""
    missing = []
    unverified = []
    if args.graph:
        try:
            graph_raw = run_graph_backend(
                args.graph,
                symbol,
                root,
                fail_patterns=fail_patterns,
                default_markers=not args.no_default_fail_markers,
            )
            graph_files = graph_caller_files(graph_raw, root, args.graph_format)
        except BackendFailure as exc:
            return _backend_error(symbol, exc, baseline_files, args.json)
        except OSError as exc:
            return _configuration_error(str(exc), args.json)
        missing = sorted(baseline_files - graph_files)
        if args.graph_format == "text":
            try:
                declared_in = declaration_files(symbol, root)
            except (OSError, ValueError) as exc:
                return _configuration_error(str(exc), args.json)
            unverified = sorted((baseline_files & graph_files) & declared_in)

    if missing:
        verdict = "OMISSION"
    elif unverified:
        verdict = "UNVERIFIED"
    else:
        verdict = "PASS"
    final_status = "PASS" if verdict == "PASS" else "FAIL"

    graph_count = len(graph_files) if graph_files is not None else None
    token_count = None
    graph_tokens = count_tokens(graph_raw) if args.graph else 0
    baseline_tokens = count_tokens(baseline_raw)
    if baseline_tokens is not None and graph_tokens is not None:
        token_count = baseline_tokens + graph_tokens

    result = {
        "symbol": symbol,
        "supported_extensions": list(SUPPORTED_EXTENSIONS),
        "baseline_caller_count": len(baseline_files),
        "graph_caller_count": graph_count,
        "missing_caller_count": len(missing),
        "missing_callers": missing,
        "unverified_caller_count": len(unverified),
        "unverified_callers": unverified,
        "audit_verdict": verdict if args.graph else "BASELINE_ONLY",
        "graph_format": args.graph_format if args.graph else None,
        "final_status": final_status,
        # Backward-compatible v0.1 fields:
        "grep_caller_files": sorted(baseline_files),
        "graph_caller_files": sorted(graph_files) if graph_files is not None else None,
        "omitted_by_graph": missing,
        "complete_caller_files": sorted(baseline_files | (graph_files or set())),
        "audit_pass": (verdict == "PASS") if args.graph else None,
        "approx_tokens": token_count,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"impact-audited  «{symbol}»")
        print(f"Audited symbol: {symbol}")
        print(f"Baseline caller count: {len(baseline_files)}")
        print(f"Graph caller count: {graph_count if graph_count is not None else 'N/A'}")
        print(f"Missing callers ({len(missing)}): {missing}")
        if unverified:
            print(
                f"Unverified callers ({len(unverified)}): {unverified} "
                "(file declares the symbol; a path mention in text output cannot prove "
                "the same-file call is covered - use --graph-format lines/gitnexus)"
            )
        if verdict == "UNVERIFIED":
            print("Final: FAIL (UNVERIFIED)")
        else:
            print(f"Final: {final_status}")
        if not args.graph:
            print("Note: baseline-only mode; no graph backend was audited.")
        if token_count:
            print(f"Approximate tokens: {token_count}")

    if not args.graph:
        return EXIT_PASS
    if verdict == "OMISSION":
        return EXIT_OMISSION
    if verdict == "UNVERIFIED":
        return EXIT_UNVERIFIED
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
