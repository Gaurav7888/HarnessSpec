# Shared benchmark result contract

Validate one finalized task attempt against `pilot/result.schema.json` (JSON Schema Draft 2020-12). The SWE-bench and SWE-QA result files each hold a JSON array of these rows. Every field is required. Diagnostics, energy and pending external grades belong in separate artifacts.

Use `PYTHONPATH=src` and import `validate_result(row)` from `harnessspec.results` before writing a row. Use `read_results([path])` when loading arrays. It rejects duplicate JSON fields and repeated (benchmark, task_id, designer, seed) identities. Use `write_json(path, rows)` for atomic replacement.

Count all prompt and generated tokens consumed by each stage, including unsuccessful replies and design repairs. Keep failed attempts in cost totals. For SWE-QA, finalize an accepted answer's boolean outcome only when external grading is complete. A fixed harness has its actual compiler verdict. An uncompiled B brief has no compiled first-pass verdict. Its boolean wire convention still requires team agreement and B is excluded from validity summaries.
