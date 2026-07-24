#!/usr/bin/env python3
"""Cross-check graph-backend callers against a deterministic text-scan floor."""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

EXIT_PASS = 0
EXIT_OMISSION = 2
EXIT_BACKEND_FAILURE = 3
EXIT_INVALID_CONFIG = 4

SUPPORTED_EXTENSIONS = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")
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
    return bool(
        re.search(rf"\b(?:function|class)\s+{escaped}\b", line)
        or re.search(
            rf"^\s*(?:public\s+|private\s+|protected\s+|static\s+|async\s+)*"
            rf"{escaped}\s*\([^)]*\)\s*(?::[^={{]+)?\s*{{",
            line,
        )
    )


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
            is_call = bool(call_re.search(line))
            is_jsx = suffix in JSX_EXTENSIONS and bool(jsx_re.search(line))
            if not (is_call or is_jsx) or _is_definition_line(symbol, suffix, line):
                continue
            callers.add(relative)
            matched_lines.append(f"{relative}:{line_number}:{line}")

    return callers, "\n".join(matched_lines)


def run_graph_backend(template, symbol, root):
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
    return proc.stdout


def build_parser():
    parser = AuditArgumentParser(
        prog="impact-audited",
        description="Cross-check a code-graph impact tool against a text-scan floor.",
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
    parser.add_argument("--json", action="store_true", help="machine-readable output")
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

    try:
        baseline_files, baseline_raw = baseline_caller_files(symbol, root)
    except (OSError, ValueError) as exc:
        return _configuration_error(str(exc), args.json)

    graph_files = None
    graph_raw = ""
    missing = []
    if args.graph:
        try:
            graph_raw = run_graph_backend(args.graph, symbol, root)
        except BackendFailure as exc:
            return _backend_error(symbol, exc, baseline_files, args.json)
        try:
            graph_files = files_in_text(graph_raw, root)
        except OSError as exc:
            return _configuration_error(str(exc), args.json)
        missing = sorted(baseline_files - graph_files)

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
        "final_status": "FAIL" if missing else "PASS",
        # Backward-compatible v0.1 fields:
        "grep_caller_files": sorted(baseline_files),
        "graph_caller_files": sorted(graph_files) if graph_files is not None else None,
        "omitted_by_graph": missing,
        "complete_caller_files": sorted(baseline_files | (graph_files or set())),
        "audit_pass": (not missing) if args.graph else None,
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
        print(f"Final: {'FAIL' if missing else 'PASS'}")
        if not args.graph:
            print("Note: baseline-only mode; no graph backend was audited.")
        if token_count:
            print(f"Approximate tokens: {token_count}")

    return EXIT_OMISSION if args.graph and missing else EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
