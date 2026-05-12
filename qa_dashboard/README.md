# QA Dashboard

Auto-generated QA dashboard for the EventFlow Payment Service.  
Collects test results, code coverage, lint status, and quality-gap analysis,
then renders an interactive HTML report with Chart.js visualisations.

## Quick Start

```bash
# Install dependencies (if not already done)
poetry install

# Generate the dashboard
poetry run python -m qa_dashboard.generate_dashboard
```

The output is written to `qa_dashboard/dashboard.html`.  
Open it in any browser — no server required.

## KPIs & Metrics

| Metric | Source |
|---|---|
| **Pass Rate** | pytest results |
| **Total / Passed / Failed / Skipped** | pytest results |
| **Code Coverage (%)** | pytest-cov |
| **Per-file Coverage** | pytest-cov JSON report |
| **Lint Status** | ruff |
| **Quality Gaps** | Static analysis of code + test coverage |
| **Test Duration** | pytest-json-report |

## Dashboard Sections

1. **KPI Cards** — top-level pass rate, test counts, coverage, duration, gap count.
2. **Test Results by Category** — stacked bar chart grouped by test class.
3. **Code Coverage by File** — horizontal stacked bar (covered vs missing).
4. **Test Outcome Distribution** — donut chart (passed / failed / skipped / errors).
5. **Overall Statement Coverage** — donut chart (covered vs uncovered).
6. **Test Results Detail** — full table of every test with status badge and timing.
7. **Coverage by File** — table with inline coverage bars.
8. **Lint Status** — ruff output.
9. **Quality Gaps & Recommendations** — auto-detected issues (low coverage, known bugs, missing tests).
