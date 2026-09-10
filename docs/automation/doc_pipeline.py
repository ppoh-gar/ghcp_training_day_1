"""Documentation pipeline: runs the 5-phase workflow as a state machine.

Phases: SCOPE -> ANALYZE -> DOCUMENT -> SPHINX -> REVIEW -> DONE/FAILED.

Phase 3 (DOCUMENT) inserts template docstring stubs so the pipeline is
runnable standalone; the Documentation Agent then overwrites these stubs
with real, reviewed docstrings before the pipeline continues to SPHINX.
"""
from __future__ import annotations

import argparse
import ast
import enum
import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

LOG_PATH = Path(__file__).parent / "pipeline.log"
REPORT_PATH = Path(__file__).parent / "report.md"

DEFAULT_EXCLUDE_DIRS = {"tests", "docs", ".venv", "venv", "__pycache__", ".git", "node_modules", "data"}

logger = logging.getLogger("doc_pipeline")


def configure_logging(verbose: bool = False) -> None:
    """Log to console and to pipeline.log; called once at startup."""
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

    file_handler = logging.FileHandler(LOG_PATH, mode="w", encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    logger.addHandler(console)
    logger.addHandler(file_handler)


class Phase(enum.Enum):
    SCOPE = "scope_identification"
    ANALYZE = "file_logic_analysis"
    DOCUMENT = "inline_documentation"
    SPHINX = "sphinx_generation"
    REVIEW = "review_and_maintenance"
    DONE = "done"
    FAILED = "failed"


@dataclass
class MissingSymbol:
    file: Path
    name: str
    kind: str  # "module" | "class" | "function"
    lineno: int
    col_offset: int = 0
    body_lineno: int = 1
    args: list[str] = field(default_factory=list)


@dataclass
class PipelineState:
    """Mutable context threaded through every phase; the state machine's memory."""

    source: Path
    output: Path
    style: str = "google"
    exclude_dirs: set[str] = field(default_factory=lambda: set(DEFAULT_EXCLUDE_DIRS))
    files: list[Path] = field(default_factory=list)
    missing_before: list[MissingSymbol] = field(default_factory=list)
    docstrings_added: int = 0
    sphinx_status: str = "not_run"
    coverage_before: float = 0.0
    coverage_after: float = 0.0
    phase: Phase = Phase.SCOPE
    errors: list[str] = field(default_factory=list)


class PhaseError(Exception):
    """Raised when a phase cannot complete; carries whether it is fatal."""

    def __init__(self, message: str, fatal: bool = True):
        super().__init__(message)
        self.fatal = fatal


# ---------------------------------------------------------------------------
# Phase 1: Scope Identification
# ---------------------------------------------------------------------------
def phase_scope_identification(state: PipelineState) -> None:
    """Locate Python files under `state.source`, skipping `state.exclude_dirs`."""
    logger.info("PHASE 1 (Scope Identification): scanning %s", state.source)
    if not state.source.exists():
        raise PhaseError(f"Source path does not exist: {state.source}", fatal=True)

    all_files = sorted(state.source.rglob("*.py"))
    files = [
        f for f in all_files
        if not set(f.relative_to(state.source).parts[:-1]) & state.exclude_dirs
    ]
    if not files:
        raise PhaseError(f"No Python files found under {state.source}", fatal=True)

    state.files = files
    logger.info(
        "Scope defined: %d Python file(s) targeted for documentation (%d excluded)",
        len(files), len(all_files) - len(files),
    )
    for f in files:
        logger.debug("  scoped file: %s", f)


# ---------------------------------------------------------------------------
# Phase 2: File / Logic Analysis
# ---------------------------------------------------------------------------
def _stmt_start_lineno(stmt: ast.stmt) -> int:
    """First line of `stmt`, counting its decorators if any (they must stay attached)."""
    decorators = getattr(stmt, "decorator_list", None)
    if decorators:
        return decorators[0].lineno
    return stmt.lineno


def _find_missing_docstrings(path: Path) -> list[MissingSymbol]:
    """Parse `path` with `ast` and report modules/classes/functions with no docstring."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    missing: list[MissingSymbol] = []

    if ast.get_docstring(tree) is None:
        missing.append(MissingSymbol(path, path.stem, "module", 1))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if ast.get_docstring(node) is None and not node.name.startswith("_"):
                args = [a.arg for a in node.args.args if a.arg != "self"]
                missing.append(
                    MissingSymbol(
                        path, node.name, "function", node.lineno, node.col_offset,
                        _stmt_start_lineno(node.body[0]), args,
                    )
                )
        elif isinstance(node, ast.ClassDef):
            if ast.get_docstring(node) is None:
                missing.append(
                    MissingSymbol(
                        path, node.name, "class", node.lineno, node.col_offset,
                        _stmt_start_lineno(node.body[0]),
                    )
                )

    return missing


def phase_file_analysis(state: PipelineState) -> None:
    """Parse every scoped file and compute docstring coverage before documentation."""
    logger.info("PHASE 2 (File/Logic Analysis): parsing %d file(s)", len(state.files))
    missing: list[MissingSymbol] = []
    total_symbols = 0

    for f in state.files:
        try:
            file_missing = _find_missing_docstrings(f)
        except SyntaxError as exc:
            raise PhaseError(f"Syntax error in {f}: {exc}", fatal=True) from exc
        missing.extend(file_missing)
        total_symbols += _count_symbols(f)

    state.missing_before = missing
    state.coverage_before = _coverage(total_symbols, len(missing))
    logger.info(
        "Analysis complete: %d symbol(s) missing docstrings out of %d (coverage %.0f%%)",
        len(missing), total_symbols, state.coverage_before,
    )


def _count_symbols(path: Path) -> int:
    """Count module + class + function definitions in `path` (the coverage denominator)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    count = 1  # module itself
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            count += 1
    return count


def _coverage(total: int, missing: int) -> float:
    """Return the percentage of symbols that already have docstrings."""
    if total == 0:
        return 100.0
    return 100.0 * (total - missing) / total


# ---------------------------------------------------------------------------
# Phase 3: Inline Documentation Application
# ---------------------------------------------------------------------------
def _stub_docstring(symbol: MissingSymbol, style: str) -> str:
    """Build a docstring stub, unindented; caller applies per-line indentation."""
    if symbol.kind == "module":
        return f'"""{symbol.name} module."""'
    if symbol.kind == "class":
        return f'"""{symbol.name} class."""'
    if style == "numpy":
        params = "".join(f"\n{a} : type\n    Description." for a in symbol.args)
        body = f"Summary of {symbol.name}.\n\nParameters\n----------{params}"
    else:
        args_doc = "".join(f"\n    {a}: Description of {a}." for a in symbol.args)
        body = f"Summary of {symbol.name}.\n\nArgs:{args_doc}"
    return f'"""{body}\n"""'


def _indent_block(text: str, indent: str) -> str:
    """Prefix every line of a (possibly multi-line) docstring with `indent`."""
    return "\n".join(indent + line if line else line for line in text.splitlines())


def phase_inline_documentation(state: PipelineState) -> None:
    """Insert stub docstrings for every symbol found missing in Phase 2."""
    logger.info(
        "PHASE 3 (Inline Documentation): inserting %d stub docstring(s) [style=%s]",
        len(state.missing_before), state.style,
    )
    by_file: dict[Path, list[MissingSymbol]] = {}
    for sym in state.missing_before:
        by_file.setdefault(sym.file, []).append(sym)

    for file, symbols in by_file.items():
        lines = file.read_text(encoding="utf-8").splitlines(keepends=True)
        # Insert bottom-up so earlier line numbers stay valid.
        for sym in sorted(symbols, key=lambda s: s.body_lineno, reverse=True):
            body_indent = "" if sym.kind == "module" else " " * (sym.col_offset + 4)
            docstring = _indent_block(_stub_docstring(sym, state.style), body_indent)
            # Insert right before the first body statement, not after `def`/`class`,
            # since multi-line signatures put the body many lines below the header.
            insert_at = 0 if sym.kind == "module" else sym.body_lineno - 1
            lines.insert(insert_at, docstring + "\n")
            state.docstrings_added += 1
        file.write_text("".join(lines), encoding="utf-8")
        logger.info("  updated %s (+%d docstring stub(s))", file.name, len(symbols))

    logger.info(
        "NOTE: stub docstrings are placeholders. The Documentation Agent must "
        "replace them with accurate, reviewed content before Phase 4 (Sphinx)."
    )


# ---------------------------------------------------------------------------
# Phase 4: Sphinx Automation & Generation
# ---------------------------------------------------------------------------
_CONF_PY_TEMPLATE = '''"""Sphinx configuration auto-generated by doc_pipeline.py."""
import sys

# Source dir itself (for bare-name imports) and its parent (needed when the
# source dir has an __init__.py, so apidoc names modules after the dir itself,
# e.g. `{project}.database`, which is only importable with the parent on path).
sys.path.insert(0, r"{source_abs}")
sys.path.insert(0, r"{source_parent_abs}")

project = "{project}"
extensions = ["sphinx.ext.autodoc", "sphinx.ext.napoleon", "sphinx.ext.autosummary"]
napoleon_google_docstring = {google}
napoleon_numpy_docstring = {numpy}
autosummary_generate = True
exclude_patterns = ["_html", "_build"]
html_theme = "alabaster"
'''

_INDEX_RST_TEMPLATE = """Documentation
=============

.. toctree::
   :maxdepth: 2

   api/modules
"""


def _scaffold_sphinx_project(state: PipelineState) -> None:
    """Create conf.py / index.rst if missing; sphinx-apidoc alone doesn't provide them."""
    conf_path = state.output / "conf.py"
    if not conf_path.exists():
        source_abs = state.source.resolve()
        conf_path.write_text(
            _CONF_PY_TEMPLATE.format(
                source_abs=str(source_abs),
                source_parent_abs=str(source_abs.parent),
                project=source_abs.name,
                google=state.style == "google",
                numpy=state.style == "numpy",
            ),
            encoding="utf-8",
        )
    index_path = state.output / "index.rst"
    if not index_path.exists():
        index_path.write_text(_INDEX_RST_TEMPLATE, encoding="utf-8")


def phase_sphinx_generation(state: PipelineState) -> None:
    """Scaffold a minimal Sphinx project (if needed) and build HTML docs."""
    logger.info("PHASE 4 (Sphinx Generation): building docs into %s", state.output)

    try:
        import sphinx  # noqa: F401
    except ImportError as exc:
        state.sphinx_status = "skipped_not_installed"
        raise PhaseError(
            "sphinx not installed; skipping build (install with `pip install sphinx`)",
            fatal=False,
        ) from exc

    state.output.mkdir(parents=True, exist_ok=True)
    _scaffold_sphinx_project(state)

    html_dir = state.output / "_html"
    exclude_args = []
    for excluded in state.exclude_dirs:
        exclude_args.append(str(state.source / excluded))
    # Invoked via `-m` so it works regardless of whether console scripts are on PATH.
    apidoc_cmd = [
        sys.executable, "-m", "sphinx.ext.apidoc", "-f",
        "-o", str(state.output / "api"), str(state.source), *exclude_args,
    ]
    build_cmd = [sys.executable, "-m", "sphinx", "-b", "html", str(state.output), str(html_dir)]

    for cmd in (apidoc_cmd, build_cmd):
        logger.debug("  running: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            state.sphinx_status = "failed"
            raise PhaseError(f"Command failed ({' '.join(cmd)}): {result.stderr.strip()}", fatal=False)

    state.sphinx_status = "success"
    logger.info("Sphinx build succeeded: %s", html_dir / "index.html")


# ---------------------------------------------------------------------------
# Phase 5: Review & Maintenance
# ---------------------------------------------------------------------------
def phase_review_and_maintenance(state: PipelineState) -> None:
    """Recompute docstring coverage post-documentation and write the summary report."""
    logger.info("PHASE 5 (Review & Maintenance): recomputing coverage and writing report")
    try:
        total_symbols = sum(_count_symbols(f) for f in state.files)
        still_missing = sum(len(_find_missing_docstrings(f)) for f in state.files)
    except SyntaxError as exc:
        raise PhaseError(f"Generated source is invalid Python: {exc}", fatal=True) from exc
    state.coverage_after = _coverage(total_symbols, still_missing)

    report_lines = [
        "# Documentation Pipeline Report",
        "",
        f"- Source: `{state.source}`",
        f"- Files scanned: {len(state.files)}",
        f"- Docstrings added (Phase 3): {state.docstrings_added}",
        f"- Coverage before: {state.coverage_before:.0f}%",
        f"- Coverage after: {state.coverage_after:.0f}%",
        f"- Sphinx status: {state.sphinx_status}",
        f"- Errors encountered: {len(state.errors) or 'none'}",
    ]
    if state.errors:
        report_lines.append("")
        report_lines.append("## Errors")
        report_lines.extend(f"- {e}" for e in state.errors)

    REPORT_PATH.write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    logger.info("Report written to %s", REPORT_PATH)


# ---------------------------------------------------------------------------
# State machine orchestrator
# ---------------------------------------------------------------------------
TRANSITIONS: list[tuple[Phase, callable]] = [
    (Phase.SCOPE, phase_scope_identification),
    (Phase.ANALYZE, phase_file_analysis),
    (Phase.DOCUMENT, phase_inline_documentation),
    (Phase.SPHINX, phase_sphinx_generation),
    (Phase.REVIEW, phase_review_and_maintenance),
]


def run_pipeline(source: Path, output: Path, style: str = "google", exclude_dirs: set[str] | None = None) -> PipelineState:
    """Drive the state machine through all phases; non-fatal errors are logged and skipped."""
    state = PipelineState(source=source, output=output, style=style)
    if exclude_dirs is not None:
        state.exclude_dirs = exclude_dirs

    for phase, handler in TRANSITIONS:
        state.phase = phase
        try:
            handler(state)
        except PhaseError as exc:
            state.errors.append(str(exc))
            if exc.fatal:
                logger.error("Phase %s failed fatally: %s", phase.value, exc)
                state.phase = Phase.FAILED
                return state
            logger.warning("Phase %s failed non-fatally, continuing: %s", phase.value, exc)
        except Exception as exc:  # unexpected error: log full context, abort
            logger.exception("Unexpected error in phase %s", phase.value)
            state.errors.append(f"{phase.value}: {exc}")
            state.phase = Phase.FAILED
            return state

    state.phase = Phase.DONE
    logger.info("Pipeline finished with status: %s", state.phase.value)
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the documentation workflow pipeline.")
    parser.add_argument("--source", required=True, type=Path, help="Path to source code to document")
    parser.add_argument("--output", default=Path("docs/build"), type=Path, help="Sphinx output directory")
    parser.add_argument("--style", default="google", choices=["google", "numpy"])
    parser.add_argument(
        "--exclude", default=",".join(sorted(DEFAULT_EXCLUDE_DIRS)),
        help="Comma-separated directory names to exclude from scope",
    )
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    configure_logging(args.verbose)
    exclude_dirs = {d.strip() for d in args.exclude.split(",") if d.strip()}
    state = run_pipeline(args.source, args.output, args.style, exclude_dirs)

    return 0 if state.phase == Phase.DONE else 1


if __name__ == "__main__":
    raise SystemExit(main())
