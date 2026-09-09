# Refactoring Rules

- Preserve all current observable behavior in the ticketing system.
- Do not change API routes, parameter aliases, validation behavior, request/response models, status codes, error messages, or not-found exception chaining behavior.
- Do not change database schema, initialization, seed data, timestamp semantics, lock boundaries, query ordering, filter ordering, sorting, or persistence behavior.
- Keep SQL values parameterized and keep SQL field names limited to the known `TicketUpdate` / repository field set already supported by the code.
- Do not change NiceGUI layout, text, classes, props, styles, notifications, callback ordering, or ticket-ID callback binding behavior.
- Do not change compatibility wildcard re-export behavior in `app/database.py`, `app/api.py`, or `app/ui.py`.
- Keep the diff purpose-driven: no dependency changes, no unrelated bug fixes, no generated files, and no broad formatting churn.

# Extracted Helpers

## `TicketRepository._build_list_query` (`/home/runner/work/ghcp_training/ghcp_training/database.py`)
- Why it exists: separates filter-to-SQL construction from query execution so the list contract is easier to read and test directly.
- Behavior it preserves: status filter first, priority filter second, search predicates last; parameterized `?` placeholders; `%{search}%` wildcard wrapping; `ORDER BY created_at ASC, id ASC`.
- Tests validating it: `tests/test_refactoring_regressions.py::test_repository_build_list_query_keeps_values_parameterized_and_in_filter_order`

## `TicketRepository._build_update_assignments` (`/home/runner/work/ghcp_training/ghcp_training/database.py`)
- Why it exists: isolates update assignment construction from the `UPDATE ... RETURNING` orchestration.
- Behavior it preserves: `model_dump(exclude_unset=True)` field iteration order, existing enum-to-string conversion, and parameterized assignments.
- Tests validating it: `tests/test_refactoring_regressions.py::test_repository_build_update_assignments_preserves_model_field_order_and_enum_values`

## `TicketRepository._require_ticket` (`/home/runner/work/ghcp_training/ghcp_training/database.py`)
- Why it exists: keeps row-to-ticket conversion and missing-row handling in one place for `get`/`update`.
- Behavior it preserves: raises `TicketNotFoundError(f"Ticket {ticket_id} was not found")` for missing rows and otherwise uses the existing strict row-to-model mapping.
- Tests validating it: existing repository and API not-found tests plus `tests/test_refactoring_regressions.py::test_ticket_api_missing_ticket_messages_remain_unchanged`

## `TicketRepository._raise_not_found` (`/home/runner/work/ghcp_training/ghcp_training/database.py`)
- Why it exists: centralizes the exact repository not-found message used by multiple methods.
- Behavior it preserves: exact exception type and message for missing IDs.
- Tests validating it: existing repository/API missing-ticket tests plus `tests/test_refactoring_regressions.py::test_ticket_api_missing_ticket_messages_remain_unchanged`

## `_ticket_not_found_http_exception` (`/home/runner/work/ghcp_training/ghcp_training/api.py`)
- Why it exists: removes repeated FastAPI 404 construction without changing route signatures or catch behavior.
- Behavior it preserves: only `TicketNotFoundError` is translated, the HTTP status remains 404, and `detail` remains `str(error)`.
- Tests validating it: `tests/test_refactoring_regressions.py::test_ticket_api_missing_ticket_messages_remain_unchanged`

## `_build_ticket_filters` (`/home/runner/work/ghcp_training/ghcp_training/ui.py`)
- Why it exists: extracts page-control value normalization into a pure helper.
- Behavior it preserves: `"all"` becomes `None`, search uses `search.value or None`, and `TicketFilters` validation still normalizes whitespace-only search to `None`.
- Tests validating it: `tests/test_refactoring_regressions.py::test_ui_helpers_preserve_filter_mapping_and_ticket_create_validation`

## `_ticket_filters_or_none` (`/home/runner/work/ghcp_training/ghcp_training/ui.py`)
- Why it exists: keeps the UI rule for when `repository.list` should receive `None` versus a `TicketFilters` instance separate from callback orchestration.
- Behavior it preserves: repository receives `None` only when every filter field is absent after existing model normalization.
- Tests validating it: `tests/test_refactoring_regressions.py::test_ui_helpers_preserve_filter_mapping_and_ticket_create_validation`

## `_build_ticket_create` (`/home/runner/work/ghcp_training/ghcp_training/ui.py`)
- Why it exists: extracts form-value to `TicketCreate` conversion into a pure helper that can be tested without NiceGUI callbacks.
- Behavior it preserves: `TicketCreate` is still constructed inside the UI `try` block, Pydantic/enum validation still raises `ValueError`, and successful values still normalize through the existing model validators.
- Tests validating it: `tests/test_refactoring_regressions.py::test_ui_helpers_preserve_filter_mapping_and_ticket_create_validation`

# Verification

- Baseline command from README: `uv run pytest`
  - Result in this sandbox before setup: failed because `uv` was not installed (`/bin/bash: uv: command not found`).
- Environment setup for equivalent local validation: installed the already-pinned packages from `pyproject.toml` with `python -m pip install ...` and then ran `python -m pytest`.
- Baseline result after setup: `5 passed`.
- Final verification commands/results:
  - `python -m pytest tests/test_refactoring_regressions.py`
  - `python -m pytest`
