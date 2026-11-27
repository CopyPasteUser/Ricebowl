#!/bin/bash
# local-ci step: sg7-matrix-unit
# Mirrors: sg7-exact-main.yml / dossier / Verify SG7 exact-main collector unit tests
# Environment (set by scripts/local_ci.py): RUNNER_TEMP, GITHUB_SHA, TMPDIR, LCI_* ; cwd = fresh clone.
/usr/bin/python3 -m unittest tests.test_release_workflows tests.test_sg7_exact_main_matrix tests.test_sg7_safe_receipt_io tests.test_sg7_dossier_io tests.test_sg7_local_dossier -v
/usr/bin/python3 -m py_compile scripts/sg7_exact_main_matrix.py scripts/sg7_safe_receipt_io.py scripts/sg7_dossier_io.py scripts/sg7_local_dossier.py
