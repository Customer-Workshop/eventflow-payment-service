"""QA Dashboard Generator for EventFlow Payment Service.

Collects test results, code coverage, and lint metrics, then renders
an interactive HTML dashboard with Chart.js visualisations.

Usage:
    poetry run python -m qa_dashboard.generate_dashboard
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TestResult:
    """Single test outcome."""

    nodeid: str
    outcome: str  # "passed", "failed", "skipped", "error"
    duration: float  # seconds
    category: str = ""

    def __post_init__(self) -> None:
        if not self.category:
            self.category = _derive_category(self.nodeid)


@dataclass
class CoverageFile:
    """Coverage data for one source file."""

    filename: str
    statements: int
    missing: int
    covered: int
    percent: float
    missing_lines: list[int] = field(default_factory=list)


@dataclass
class DashboardData:
    """Aggregated metrics consumed by the HTML template."""

    generated_at: str
    # Tests
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    pass_rate: float = 0.0
    total_duration: float = 0.0
    tests: list[TestResult] = field(default_factory=list)
    categories: dict[str, dict[str, int]] = field(default_factory=dict)
    # Coverage
    overall_coverage: float = 0.0
    total_statements: int = 0
    total_covered: int = 0
    total_missing: int = 0
    coverage_files: list[CoverageFile] = field(default_factory=list)
    # Lint
    lint_clean: bool = True
    lint_issues: int = 0
    lint_output: str = ""
    # Quality gaps
    quality_gaps: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _derive_category(nodeid: str) -> str:
    """Extract a human-readable category from a pytest nodeid."""
    parts = nodeid.split("::")
    if len(parts) >= 2:
        return parts[1]
    return "Uncategorised"


def _run(cmd: list[str], cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)  # noqa: S603


# ---------------------------------------------------------------------------
# Collectors
# ---------------------------------------------------------------------------

def collect_test_results(data: DashboardData) -> None:
    """Run pytest with JSON report output and populate *data*."""
    json_path = PROJECT_ROOT / "qa_dashboard" / "test_results.json"
    result = _run(
        [
            sys.executable, "-m", "pytest",
            "-v", "--tb=short",
            f"--json-report-file={json_path}",
            "--json-report",
        ],
    )

    # If pytest-json-report is not installed, fall back to parsing verbose output
    if json_path.exists():
        _parse_json_report(json_path, data)
    else:
        _parse_verbose_output(result.stdout, data)

    if data.total_tests:
        data.pass_rate = round(data.passed / data.total_tests * 100, 1)


def _parse_json_report(path: Path, data: DashboardData) -> None:
    raw = json.loads(path.read_text())
    data.total_duration = raw.get("duration", 0.0)
    for t in raw.get("tests", []):
        tr = TestResult(
            nodeid=t["nodeid"],
            outcome=t["outcome"],
            duration=t.get("duration", 0.0),
        )
        data.tests.append(tr)
        _tally(data, tr)


def _parse_verbose_output(stdout: str, data: DashboardData) -> None:
    """Fallback parser when pytest-json-report is unavailable."""
    for line in stdout.splitlines():
        upper = line.upper()
        if " PASSED" in upper or " FAILED" in upper or " SKIPPED" in upper or " ERROR" in upper:
            parts = line.rsplit(" ", 1)
            if len(parts) == 2:
                nodeid = parts[0].strip()
                outcome = parts[1].strip().lower()
                # Strip ANSI and brackets
                for char in "[]":
                    outcome = outcome.replace(char, "")
                outcome = outcome.strip().split()[0] if outcome.strip() else "passed"
                tr = TestResult(nodeid=nodeid, outcome=outcome, duration=0.0)
                data.tests.append(tr)
                _tally(data, tr)
    # Try to parse total duration from summary line
    for line in stdout.splitlines():
        if "passed" in line and "in " in line:
            try:
                segment = line.split("in ")[-1]
                data.total_duration = float(segment.replace("s", "").strip())
            except ValueError:
                pass


def _tally(data: DashboardData, tr: TestResult) -> None:
    data.total_tests += 1
    if tr.outcome == "passed":
        data.passed += 1
    elif tr.outcome == "failed":
        data.failed += 1
    elif tr.outcome == "skipped":
        data.skipped += 1
    else:
        data.errors += 1

    cat = tr.category
    if cat not in data.categories:
        data.categories[cat] = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    bucket = "errors" if tr.outcome not in ("passed", "failed", "skipped") else tr.outcome
    data.categories[cat][bucket] += 1


def collect_coverage(data: DashboardData) -> None:
    """Run pytest with coverage and parse the JSON report."""
    cov_json = PROJECT_ROOT / "qa_dashboard" / "coverage.json"
    _run(
        [
            sys.executable, "-m", "pytest",
            "--cov=app",
            f"--cov-report=json:{cov_json}",
            "--cov-report=term-missing",
            "-q",
        ],
    )
    if not cov_json.exists():
        return

    raw = json.loads(cov_json.read_text())
    totals = raw.get("totals", {})
    data.overall_coverage = round(totals.get("percent_covered", 0.0), 1)
    data.total_statements = totals.get("num_statements", 0)
    data.total_covered = totals.get("covered_lines", 0)
    data.total_missing = totals.get("missing_lines", 0)

    for fname, fdata in raw.get("files", {}).items():
        summary = fdata.get("summary", {})
        cf = CoverageFile(
            filename=fname,
            statements=summary.get("num_statements", 0),
            missing=summary.get("missing_lines", 0),
            covered=summary.get("covered_lines", 0),
            percent=round(summary.get("percent_covered", 0.0), 1),
            missing_lines=fdata.get("missing_lines", []),
        )
        data.coverage_files.append(cf)


def collect_lint(data: DashboardData) -> None:
    """Run ruff and record results."""
    result = _run([sys.executable, "-m", "ruff", "check", "app/", "tests/"])
    data.lint_output = result.stdout.strip()
    if data.lint_output:
        data.lint_issues = len(
            [ln for ln in data.lint_output.splitlines() if ln.strip()]
        )
    else:
        data.lint_issues = 0
    data.lint_clean = data.lint_issues == 0


def analyse_quality_gaps(data: DashboardData) -> None:
    """Identify notable quality gaps from collected data."""
    # Low coverage files
    for cf in data.coverage_files:
        if cf.statements > 0 and cf.percent < 50:
            data.quality_gaps.append(
                f"Low coverage: {cf.filename} at {cf.percent}% "
                f"({cf.missing} of {cf.statements} statements uncovered)"
            )

    # Known JPY/KRW bug documented in processor.py
    processor = PROJECT_ROOT / "app" / "processor.py"
    if processor.exists() and "BUG" in processor.read_text():
        data.quality_gaps.append(
            "Known bug: Zero-decimal currency conversion (JPY/KRW) "
            "- no test coverage for this code path"
        )

    # Missing test categories
    test_file = PROJECT_ROOT / "tests" / "test_processor.py"
    if test_file.exists():
        content = test_file.read_text()
        if "JPY" not in content and "KRW" not in content:
            data.quality_gaps.append(
                "Missing tests: No JPY or KRW currency test cases "
                "(zero-decimal currencies are untested)"
            )

    if not data.lint_clean:
        data.quality_gaps.append(
            f"Lint issues: {data.lint_issues} issue(s) reported by ruff"
        )


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_html(data: DashboardData) -> str:
    """Return complete HTML dashboard string."""
    # Prepare JSON-safe data for Chart.js
    cov_labels = json.dumps([cf.filename.replace("app/", "") for cf in data.coverage_files])
    cov_values = json.dumps([cf.percent for cf in data.coverage_files])
    cov_missing = json.dumps([cf.missing for cf in data.coverage_files])
    cov_covered = json.dumps([cf.covered for cf in data.coverage_files])

    cat_labels = json.dumps(list(data.categories.keys()))
    cat_passed = json.dumps([v["passed"] for v in data.categories.values()])
    cat_failed = json.dumps([v["failed"] for v in data.categories.values()])
    cat_skipped = json.dumps([v["skipped"] for v in data.categories.values()])

    test_rows = ""
    for t in data.tests:
        badge_cls = {
            "passed": "badge-pass",
            "failed": "badge-fail",
            "skipped": "badge-skip",
        }.get(t.outcome, "badge-fail")
        test_rows += (
            f"<tr>"
            f"<td class='nodeid'>{t.nodeid}</td>"
            f"<td><span class='badge {badge_cls}'>{t.outcome.upper()}</span></td>"
            f"<td>{t.duration:.4f}s</td>"
            f"</tr>\n"
        )

    cov_rows = ""
    for cf in data.coverage_files:
        bar_cls = "bar-high" if cf.percent >= 80 else ("bar-mid" if cf.percent >= 50 else "bar-low")
        cov_rows += (
            f"<tr>"
            f"<td>{cf.filename}</td>"
            f"<td>{cf.statements}</td>"
            f"<td>{cf.covered}</td>"
            f"<td>{cf.missing}</td>"
            f"<td>"
            f"  <div class='cov-bar-bg'><div class='cov-bar {bar_cls}' style='width:{cf.percent}%'></div></div>"
            f"  <span class='cov-pct'>{cf.percent}%</span>"
            f"</td>"
            f"</tr>\n"
        )

    gaps_html = ""
    for g in data.quality_gaps:
        icon = "bug" if "bug" in g.lower() else ("alert" if "missing" in g.lower() else "info")
        gaps_html += f"<li class='gap-item gap-{icon}'>{g}</li>\n"

    lint_status = (
        "<span class='badge badge-pass'>CLEAN</span>"
        if data.lint_clean
        else f"<span class='badge badge-fail'>{data.lint_issues} ISSUE(S)</span>"
    )

    return _HTML_TEMPLATE.format(
        generated_at=data.generated_at,
        total_tests=data.total_tests,
        passed=data.passed,
        failed=data.failed,
        skipped=data.skipped,
        errors=data.errors,
        pass_rate=data.pass_rate,
        total_duration=f"{data.total_duration:.2f}",
        overall_coverage=data.overall_coverage,
        total_statements=data.total_statements,
        total_covered=data.total_covered,
        total_missing=data.total_missing,
        lint_status=lint_status,
        lint_output=data.lint_output or "No issues found.",
        test_rows=test_rows,
        cov_rows=cov_rows,
        cov_labels=cov_labels,
        cov_values=cov_values,
        cov_missing=cov_missing,
        cov_covered=cov_covered,
        cat_labels=cat_labels,
        cat_passed=cat_passed,
        cat_failed=cat_failed,
        cat_skipped=cat_skipped,
        gaps_html=gaps_html,
        gap_count=len(data.quality_gaps),
    )


# ---------------------------------------------------------------------------
# HTML Template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>QA Dashboard &mdash; EventFlow Payment Service</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
  :root {{
    --bg: #0f172a; --surface: #1e293b; --border: #334155;
    --text: #e2e8f0; --muted: #94a3b8;
    --green: #22c55e; --red: #ef4444; --yellow: #eab308; --blue: #3b82f6;
    --cyan: #06b6d4; --purple: #a78bfa;
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: 'Segoe UI',system-ui,-apple-system,sans-serif; background:var(--bg); color:var(--text); line-height:1.6; }}

  /* Header */
  .header {{ background:linear-gradient(135deg,#1e3a5f 0%,#0f172a 100%); padding:2rem 2.5rem; border-bottom:1px solid var(--border); }}
  .header h1 {{ font-size:1.75rem; font-weight:700; }}
  .header p {{ color:var(--muted); font-size:.85rem; margin-top:.25rem; }}

  /* Grid */
  .container {{ max-width:1400px; margin:0 auto; padding:1.5rem; }}
  .kpi-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:1rem; margin-bottom:1.5rem; }}
  .kpi {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1.25rem; text-align:center; }}
  .kpi .value {{ font-size:2rem; font-weight:700; }}
  .kpi .label {{ color:var(--muted); font-size:.8rem; text-transform:uppercase; letter-spacing:.05em; margin-top:.25rem; }}
  .kpi.green .value {{ color:var(--green); }}
  .kpi.red .value   {{ color:var(--red); }}
  .kpi.yellow .value {{ color:var(--yellow); }}
  .kpi.blue .value  {{ color:var(--blue); }}
  .kpi.cyan .value  {{ color:var(--cyan); }}
  .kpi.purple .value {{ color:var(--purple); }}

  /* Cards */
  .card {{ background:var(--surface); border:1px solid var(--border); border-radius:12px; padding:1.5rem; margin-bottom:1.5rem; }}
  .card h2 {{ font-size:1.15rem; margin-bottom:1rem; display:flex; align-items:center; gap:.5rem; }}
  .row {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5rem; }}
  @media (max-width:900px) {{ .row {{ grid-template-columns:1fr; }} }}

  /* Tables */
  table {{ width:100%; border-collapse:collapse; font-size:.85rem; }}
  th {{ text-align:left; color:var(--muted); font-weight:600; padding:.6rem .5rem; border-bottom:1px solid var(--border); }}
  td {{ padding:.55rem .5rem; border-bottom:1px solid #1e293b; }}
  .nodeid {{ font-family:monospace; font-size:.8rem; word-break:break-all; }}

  /* Badges */
  .badge {{ display:inline-block; padding:.15rem .55rem; border-radius:999px; font-size:.7rem; font-weight:700; text-transform:uppercase; }}
  .badge-pass {{ background:#166534; color:#bbf7d0; }}
  .badge-fail {{ background:#991b1b; color:#fecaca; }}
  .badge-skip {{ background:#854d0e; color:#fef08a; }}

  /* Coverage bars */
  .cov-bar-bg {{ display:inline-block; width:120px; height:8px; background:#334155; border-radius:4px; vertical-align:middle; margin-right:.5rem; }}
  .cov-bar {{ height:100%; border-radius:4px; }}
  .bar-high {{ background:var(--green); }}
  .bar-mid  {{ background:var(--yellow); }}
  .bar-low  {{ background:var(--red); }}
  .cov-pct  {{ font-size:.8rem; font-weight:600; }}

  /* Gaps */
  .gap-list {{ list-style:none; }}
  .gap-item {{ padding:.75rem 1rem; border-left:3px solid var(--yellow); background:#1e293b; margin-bottom:.5rem; border-radius:0 8px 8px 0; font-size:.85rem; }}
  .gap-bug  {{ border-left-color:var(--red); }}
  .gap-alert {{ border-left-color:var(--yellow); }}
  .gap-info  {{ border-left-color:var(--blue); }}

  /* Chart containers */
  .chart-wrap {{ position:relative; height:280px; }}

  /* Lint */
  .lint-pre {{ background:#0f172a; padding:1rem; border-radius:8px; font-family:monospace; font-size:.8rem; color:var(--muted); white-space:pre-wrap; max-height:200px; overflow-y:auto; }}

  /* Footer */
  .footer {{ text-align:center; color:var(--muted); font-size:.75rem; padding:2rem 0 1rem; }}
</style>
</head>
<body>

<div class="header">
  <h1>QA Dashboard</h1>
  <p>EventFlow Payment Service &mdash; Generated {generated_at}</p>
</div>

<div class="container">

  <!-- KPI Cards -->
  <div class="kpi-grid">
    <div class="kpi green"><div class="value">{pass_rate}%</div><div class="label">Pass Rate</div></div>
    <div class="kpi blue"><div class="value">{total_tests}</div><div class="label">Total Tests</div></div>
    <div class="kpi green"><div class="value">{passed}</div><div class="label">Passed</div></div>
    <div class="kpi red"><div class="value">{failed}</div><div class="label">Failed</div></div>
    <div class="kpi cyan"><div class="value">{overall_coverage}%</div><div class="label">Code Coverage</div></div>
    <div class="kpi purple"><div class="value">{total_duration}s</div><div class="label">Duration</div></div>
    <div class="kpi yellow"><div class="value">{gap_count}</div><div class="label">Quality Gaps</div></div>
  </div>

  <!-- Charts Row -->
  <div class="row">
    <div class="card">
      <h2>Test Results by Category</h2>
      <div class="chart-wrap"><canvas id="catChart"></canvas></div>
    </div>
    <div class="card">
      <h2>Code Coverage by File</h2>
      <div class="chart-wrap"><canvas id="covChart"></canvas></div>
    </div>
  </div>

  <!-- Pass/Fail Donut + Coverage Donut -->
  <div class="row">
    <div class="card">
      <h2>Test Outcome Distribution</h2>
      <div class="chart-wrap"><canvas id="outcomeChart"></canvas></div>
    </div>
    <div class="card">
      <h2>Overall Statement Coverage</h2>
      <div class="chart-wrap"><canvas id="covDonut"></canvas></div>
    </div>
  </div>

  <!-- Test Details Table -->
  <div class="card">
    <h2>Test Results Detail</h2>
    <table>
      <thead><tr><th>Test</th><th>Status</th><th>Duration</th></tr></thead>
      <tbody>{test_rows}</tbody>
    </table>
  </div>

  <!-- Coverage Details Table -->
  <div class="card">
    <h2>Coverage by File</h2>
    <table>
      <thead><tr><th>File</th><th>Stmts</th><th>Covered</th><th>Missing</th><th>Coverage</th></tr></thead>
      <tbody>{cov_rows}</tbody>
    </table>
  </div>

  <!-- Lint Status -->
  <div class="card">
    <h2>Lint Status &nbsp; {lint_status}</h2>
    <div class="lint-pre">{lint_output}</div>
  </div>

  <!-- Quality Gaps -->
  <div class="card">
    <h2>Quality Gaps &amp; Recommendations</h2>
    <ul class="gap-list">{gaps_html}</ul>
  </div>

</div>

<div class="footer">
  QA Dashboard &mdash; EventFlow Payment Service &mdash; Auto-generated by qa_dashboard
</div>

<script>
// Test results by category (stacked bar)
new Chart(document.getElementById('catChart'), {{
  type: 'bar',
  data: {{
    labels: {cat_labels},
    datasets: [
      {{ label: 'Passed',  data: {cat_passed},  backgroundColor: '#22c55e' }},
      {{ label: 'Failed',  data: {cat_failed},  backgroundColor: '#ef4444' }},
      {{ label: 'Skipped', data: {cat_skipped}, backgroundColor: '#eab308' }},
    ]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
    scales: {{
      x: {{ stacked: true, ticks: {{ color:'#94a3b8' }}, grid: {{ color:'#334155' }} }},
      y: {{ stacked: true, ticks: {{ color:'#94a3b8', stepSize:1 }}, grid: {{ color:'#334155' }} }}
    }}
  }}
}});

// Coverage horizontal bar
new Chart(document.getElementById('covChart'), {{
  type: 'bar',
  data: {{
    labels: {cov_labels},
    datasets: [
      {{ label: 'Covered',  data: {cov_covered},  backgroundColor: '#22c55e' }},
      {{ label: 'Missing',  data: {cov_missing},  backgroundColor: '#ef4444' }},
    ]
  }},
  options: {{
    indexAxis: 'y',
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }},
    scales: {{
      x: {{ stacked: true, ticks: {{ color:'#94a3b8' }}, grid: {{ color:'#334155' }} }},
      y: {{ stacked: true, ticks: {{ color:'#94a3b8' }}, grid: {{ color:'#334155' }} }}
    }}
  }}
}});

// Outcome donut
new Chart(document.getElementById('outcomeChart'), {{
  type: 'doughnut',
  data: {{
    labels: ['Passed','Failed','Skipped','Errors'],
    datasets: [{{ data: [{passed},{failed},{skipped},{errors}], backgroundColor: ['#22c55e','#ef4444','#eab308','#a78bfa'] }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }}
  }}
}});

// Coverage donut
new Chart(document.getElementById('covDonut'), {{
  type: 'doughnut',
  data: {{
    labels: ['Covered','Uncovered'],
    datasets: [{{ data: [{total_covered},{total_missing}], backgroundColor: ['#06b6d4','#334155'] }}]
  }},
  options: {{
    responsive: true, maintainAspectRatio: false,
    plugins: {{ legend: {{ labels: {{ color: '#94a3b8' }} }} }}
  }}
}});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Collecting QA metrics ...")

    data = DashboardData(
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
    )

    print("  [1/4] Running tests ...")
    collect_test_results(data)

    print("  [2/4] Collecting coverage ...")
    collect_coverage(data)

    print("  [3/4] Running lint ...")
    collect_lint(data)

    print("  [4/4] Analysing quality gaps ...")
    analyse_quality_gaps(data)

    out = PROJECT_ROOT / "qa_dashboard" / "dashboard.html"
    out.write_text(render_html(data))
    print(f"\nDashboard written to {out}")
    print(f"  Tests: {data.passed}/{data.total_tests} passed ({data.pass_rate}%)")
    print(f"  Coverage: {data.overall_coverage}%")
    print(f"  Lint: {'clean' if data.lint_clean else f'{data.lint_issues} issues'}")
    print(f"  Quality gaps: {len(data.quality_gaps)}")


if __name__ == "__main__":
    main()
