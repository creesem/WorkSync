# Bugs / known issues

Bugs and flaky tests that are observed, not yet fixed. This file is the backlog; the
work itself is tracked as tickets when it is scheduled.

## Open

### GUI server HTTP tests flake under parallel test load

- **Where:** `tests/test_gui_server.py` (`test_action_endpoint_applies_a_batch`,
  `test_action_endpoint_completes_an_action`); also an HTTP ingest test
  (`test_http_ingest_scan_and_apply`) once.
- **Symptom:** `TimeoutError` raised from `C:\Python314\Lib\socket.py:725` (an HTTP/urlopen
  read) when the suite runs with `pytest -q -n auto`. Intermittent — usually zero or one
  failure per full run, in different GUI tests each time.
- **Repro:** `.\.venv\Scripts\python.exe -m pytest -q -n auto`. The failing test passes in
  isolation (e.g. `-m pytest -q tests/test_gui_server.py::test_action_endpoint_applies_a_batch`
  → 1 passed) and in a serial `-m pytest -q` run (941 passed).
- **Likely cause:** a load/startup-time race in the loopback HTTP test server under
  `pytest-xdist` (port binding or connect timeout), not a product regression.
- **First observed:** milestone 11, block 1. Reproduced on block 2, the review-fixes
  branch, and the merged tree. Not fixed.
