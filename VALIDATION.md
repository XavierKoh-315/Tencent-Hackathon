# Starter validation — 8 October 2026

The following checks were completed before packaging:

- 14 standard-library unit tests passed, including all 12 labelled synthetic
  policy scenarios, refund caps, context isolation, invalid evidence references,
  invalid model amounts, low confidence and SQLite persistence.
- ADP protocol handling was checked with simulated responses: multi-line SSE,
  text replacement, final reply handling, excluding thought messages, failed or
  incomplete streams, JSON errors and missing credentials.
- Streamlit AppTest ran the actual interface in Python 3.12 / Streamlit 1.65.0:
  NS01 produced S$5.00 refund, NS02 retained the charge, RT01 produced S$3.69
  refund, and NS04 required human review. Changing trips did not display a stale
  ruling. Selecting ADP mode without a key showed a clear configuration error.
- Offline evaluation matched the declared policy outcome on 12/12 scenarios.
- RT01 monetary expectation was independently checked using spherical-law-of-
  cosines distances against the application's haversine calculation.

**Not yet verified:** a live ADP provider session with the user's published app,
model configuration and quota. Provider-contract tests are not live AI evaluation.
The user still needs to perform genuine CodeBuddy development and capture evidence.
All data and policy rules are explicitly synthetic/demo-only.

Reproduce the core checks with:

```text
python -m unittest discover -s tests -v
python evaluate.py --mode offline
```
