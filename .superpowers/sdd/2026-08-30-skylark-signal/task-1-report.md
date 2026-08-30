# Task 1 report

## Red command/output summary

Command: `Set-Location backend; python -m pytest tests/test_normalizer.py -q`

Result: collection failed with `ImportError: cannot import name
'normalize_currency' from 'app.cleaning.normalizer'`. The requested interface
did not exist, so the new normalization contract was correctly red.

## Green command/output summary

Focused command: `python -m pytest backend/tests/test_normalizer.py -q`

Result: `35 passed in 0.13s`.

Final verification: `python -m compileall -q backend/app`;
`python -m pytest backend/tests -q`;
`python -m ruff check backend/app/cleaning backend/tests/test_normalizer.py`;
and `git diff --check`.

Result: compilation completed without output; the backend suite reported
`35 passed in 0.12s`; Ruff reported `All checks passed!`; and
`git diff --check` reported no whitespace errors.

## Files changed

- `pyproject.toml`
- `backend/requirements.txt`
- `backend/app/cleaning/__init__.py`
- `backend/app/cleaning/schemas.py`
- `backend/app/cleaning/normalizer.py`
- `backend/app/cleaning/rules.py`
- `backend/app/cleaning/quality_report.py`
- `backend/tests/test_normalizer.py`

## Self-review

- Public behavior tests cover supported and ambiguous date shapes, INR
  multipliers, USD-without-rate, invalid and missing values, sector aliases,
  fuzzy/lower-confidence sectors, report merging, and duplicate/no-duplicate
  cases.
- Currency arithmetic uses `Decimal`; exposed layer models are typed Pydantic
  models.
- Duplicate candidates are flagged rather than merged.

## Concerns

The design names duplicate signals but no numeric tolerance/window. Task 1
makes conservative 5% and 14-day rules explicit constants; product owners can
adjust those two centralized constants if a different policy is required.
