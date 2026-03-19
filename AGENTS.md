# Repository Guidelines

## Project Structure & Module Organization
- `feishu/`: Core API workflow scripts.
- `feishu/get_token.py`: Retrieves `tenant_access_token`.
- `feishu/get_kb_files.py`: Crawls a Feishu wiki space and writes `kb_tree.json` and `files_to_download.json`.
- `feishu/download_files.py`: Downloads/export files from `files_to_download.json` into a local source directory.
- `compare_move_file.py`: Compares/moves files from a staging folder into the NAS target tree with optional protection rules.
- `api_docs/`: API reference notes (`*.md`) for Feishu endpoints.

## Build, Test, and Development Commands
- `python -m feishu.get_kb_files`: Build knowledge-base inventory and download manifest.
- `python -m feishu.download_files`: Download files listed in `files_to_download.json`.
- `python compare_move_file.py`: Run sync/move workflow example (review paths and `dry_run` settings before execution).
- `python -m py_compile feishu/*.py compare_move_file.py`: Quick syntax check.

## Coding Style & Naming Conventions
- Use Python 3 with 4-space indentation and UTF-8 source files.
- Follow `snake_case` for functions/variables, `UPPER_SNAKE_CASE` for module constants (for example `API_REQUEST_INTERVAL`).
- Keep functions small and task-oriented; prefer explicit error handling for network and file I/O paths.
- Preserve current style: clear docstrings, typed signatures where helpful, and direct log/print messages.

## Testing Guidelines
- There is currently no formal test suite (`tests/` and pytest config are absent).
- For changes, run a syntax check and a dry-run style validation with safe sample paths.
- Validate key outputs after workflow runs: `space_list.json`, `kb_tree.json`, and `files_to_download.json`.
- If adding tests, place them under `tests/` and name files `test_<module>.py`.

## Commit & Pull Request Guidelines
- Git history is minimal (initial commit only), so use clear imperative messages like `feat: add blacklist extension filter`.
- Keep commits focused by concern (API crawl, download flow, sync logic, docs).
- PRs should include: purpose, affected scripts/files, sample command used, and before/after behavior.
- Link related issue/task IDs when available and include JSON/output snippets for behavior changes.

## Security & Configuration Tips
- Do not commit real `APP_ID`, `APP_SECRET`, or tenant tokens.
- Prefer local environment injection or private config files ignored by Git.
- Double-check target directories before running move/delete operations.
