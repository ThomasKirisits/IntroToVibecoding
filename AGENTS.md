# AGENTS.md — AI Coding Agent Instructions

> Scope: Default instructions for AI assistants working in this Python software-engineering / quantitative-research repository. Adapt paths and commands to the actual repository before applying them. Existing project configuration and explicitly stated user requirements take precedence over the illustrative layout below.

## 1. Mission and operating principles

Build **correct, readable, maintainable, secure, and reproducible** software. Prefer small, well-scoped changes over speculative rewrites. Explain assumptions, protect user data, validate results, and leave the project in a state a colleague can reproduce.

- **Understand before editing:** inspect `README.md`, existing modules, tests, configuration, dependency manifests, and relevant Git state.
- **Match the codebase:** reuse existing interfaces, naming, project patterns, and installed dependencies rather than introducing parallel abstractions.
- **Make the smallest effective change:** avoid unrelated refactors or broad formatting churn.
- **Work incrementally:** for nontrivial tasks, outline the approach, identify impacted files and risks, then implement and verify in steps.
- **Verify independently:** generated code is a proposal until tests, inspection, and explicit acceptance criteria support it.
- **Report accurately:** state which checks ran, their results, and what could not be verified; never claim unexecuted tests passed.

## 2. Repository map and file ownership

A typical project may be organized as follows (do not create or rename these directories unless the task calls for it):

```text
project/
├── README.md                 # Purpose, installation, usage, reproduction
├── AGENTS.md                 # Agent-specific working conventions
├── .gitignore                # Excluded local/generated/private files
├── .env                      # Local secrets: never commit
├── .env.example              # Names/placeholders only, safe to commit
├── requirements.txt          # Project dependencies, optionally pinned
├── config/
│   └── config.json           # Non-secret parameters
├── src/
│   ├── config_loader.py      # Validated configuration access
│   ├── market_data.py        # External data/API adapter
│   └── backtest_env.py       # Core reusable domain logic
├── tests/                    # Automated behavior and regression checks
├── notebooks/                # Exploratory research and presentation
└── data/                     # Local data and databases (check tracking policy)
```

- Put **reusable business logic, classes, validation, and integrations** in `src/`, not copied across notebooks.
- Use `notebooks/` for exploration, analysis, charts, and communicating research. Notebooks should run top-to-bottom in a clean environment and import reusable code from modules.
- Keep config data separate from code. Non-secret defaults belong in versioned configuration; credentials belong in environment variables or an approved secrets manager.
- Treat existing data, databases, model artifacts, and notebooks as valuable user work. Do not overwrite or delete them without authorization.
- Update `README.md` when setup, interfaces, configuration, usage, or reproduction steps change.

## 3. Python implementation standards

### 3.1 Design and object-oriented programming

- Prefer clear, cohesive modules with **single, well-defined responsibilities**.
- Use classes where they meaningfully encapsulate persistent state or operations; use plain functions for stateless transformations. **Do not add classes solely for stylistic consistency.**
- **Abstraction:** expose simple public interfaces that describe *what* an operation does. Hide incidental implementation details.
- **Encapsulation:** modify object state through controlled methods or validated properties; protect invariants from invalid inputs.
- Favor composition and explicit dependencies over deep inheritance or hidden global state.
- Keep public method behavior stable when changing internal implementations; document intentional breaking changes.

### 3.2 Contracts and types

- Add type hints to public functions/methods and important internal interfaces; annotate return types.
- Document or enforce **preconditions** (valid inputs, required files, expected schema, units, timezone) and **postconditions** (output type, shape, invariants, side effects).
- Validate untrusted inputs at system boundaries; raise appropriate exceptions rather than returning silently corrupted results.
- Use informative names and short docstrings for non-obvious contracts. Avoid redundant comments that merely repeat code.
- For DataFrames, specify required column names, index/timezone expectations, units, missing-value policy, and sorting assumptions where relevant.

### 3.3 Errors, resources, and observability

- Catch **specific exceptions** only where a meaningful recovery, enrichment, or cleanup is possible.
- Do not hide exceptions with broad `except Exception: pass`, fabricated fallback values, or success-looking output.
- Raise actionable errors with enough context for debugging, without printing credentials or private data.
- Use context managers for files, SQLite connections, and other managed resources; ensure cleanup on error.
- Prefer structured logging over incidental `print()` calls in reusable library code.

### 3.4 Simplicity and dependencies

- Prefer the Python standard library and established packages already used by the project.
- For quantitative projects, use `pandas`/`numpy` for tabular and numeric work, `matplotlib` for visualization, and `scikit-learn`/`torch` only when the task genuinely requires them.
- Avoid unnecessary dependencies, premature optimization, hidden network calls, and over-engineered abstractions.
- Preserve backwards compatibility where feasible and call out unavoidable interface changes.

## 4. Python environment and configuration

- Use one local virtual environment per project, conventionally `.venv/`; **never commit it**.
- Prefer the existing dependency-management workflow. If this repo uses `requirements.txt`, the default setup is:

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

- If dependencies change, update the actual manifest/lockfile and document any required setup changes. Do not casually upgrade unrelated packages.
- Read configuration through a single validated interface when feasible (`ConfigLoader` or an existing equivalent). Make parameter defaults explicit.
- Prefer environment variables for credentials. Commit `.env.example` with placeholder variable names only, never real secret values.
- When behavior depends on config, test both valid and invalid configurations.

## 5. APIs and market-data integrations

- Read provider documentation for endpoint, HTTP method, authentication, response schema, pagination, rate limits, quotas, and usage terms before building integrations.
- Make network timeouts explicit; validate HTTP status **before** consuming payloads; validate JSON structure and expected fields.
- Handle authentication failures, network exceptions, timeouts, malformed responses, rate limiting (`429`), and relevant server errors.
- Retry **only transient errors**, with bounded attempts and backoff. Honor `Retry-After` when provided; avoid retrying non-idempotent writes without a safe strategy.
- Never log tokens, authorization headers, private keys, or complete sensitive responses.
- Put network code behind small interfaces so most tests can run offline with mocks/fixtures. Do not make paid or external requests during tests unless explicitly authorized.
- For market data (including `yfinance` when used), verify non-empty results, expected columns, sorted timestamps, timezone, adjusted/unadjusted price semantics, missing values, and provider limits before use.
- Never assume an API call succeeded merely because it returned a response object.

## 6. SQLite and persistence

- Use parameterized SQL queries for values (`?` placeholders); **never interpolate untrusted values** into SQL.
- Define schema, keys, uniqueness constraints, and explicit handling of duplicate records.
- Use transactions for related writes and ensure connections/cursors are cleaned up.
- Do not silently replace existing records; choose `INSERT`, conflict resolution, or updates intentionally and document the semantics.
- Keep database and local data files out of Git unless the repository intentionally versions a small, sanitized fixture.
- Back up or snapshot valuable data before destructive schema/data changes, and ask for approval before destructive operations.
- Include tests for inserts, reads, duplicate keys, invalid data, and transaction rollback.

## 7. Quantitative research and backtesting safeguards

These rules extend the workshop's core engineering practices for quant-specific correctness.

- **Prevent look-ahead bias:** at decision time `t`, use only information actually available at `t`; account for publication/release lag and execution timing.
- **Prevent data leakage:** fit transformations and models only on the training partition; use time-ordered splits when modeling chronological data.
- Record data source, retrieval date, date range, adjustment method, calendar, currency, timezone, and missing-data handling.
- Distinguish research assumptions from observed facts. Never present demonstration prices or synthetic examples as real market observations.
- Model realistic costs and constraints when reporting strategies: fees, slippage, liquidity, and execution assumptions as applicable.
- Set and record random seeds where supported; document nondeterministic GPU or external-provider behavior.
- Validate indexing, date alignment, returns calculations, missing values, and edge cases such as empty or partial data.
- Prefer deterministic, reproducible backtests and document limitations rather than asserting unsupported performance claims.

## 8. Testing and acceptance criteria

For each code change, determine what success looks like **before** implementing it.

- Add or update focused tests covering expected behavior, relevant edge cases, and failure paths.
- Include contract tests for input validation and return shapes where useful.
- For network code, test timeouts, errors, invalid payloads, and rate limits using mocked responses.
- For persistence, test schema constraints, transactions, and duplicate handling using disposable test databases.
- For quant code, test with small, deterministic fixtures and check chronological alignment and no-leakage invariants.
- Prefer the repository's actual test/lint/type-check commands. Discover them from configuration or docs; **do not assume the tools are installed**.
- If `pytest` is installed/configured, a typical test command is `python -m pytest`; otherwise use the project's established runner.
- Run the smallest relevant checks first, then broader checks when feasible. Report both results and gaps.
- Do not weaken or delete tests to make a change appear successful.

## 9. Notebooks, results, and documentation

- Notebooks should document the **question, assumptions, data, method, findings, and limitations** using Markdown alongside executable cells.
- Keep reusable logic in `src/` and treat notebooks as orchestration/presentation layers.
- Check that notebooks execute top-to-bottom from a fresh kernel with declared dependencies and known inputs.
- Clear unnecessary cell outputs before committing, especially large, confidential, or nondeterministic outputs.
- Include enough README detail for a new developer to set up and reproduce results independently.
- Do not commit secrets, raw private data, unapproved model artifacts, or large generated files.

## 10. Git and change control

- Inspect `git status` and relevant diffs before modifying files; respect existing uncommitted user changes.
- For a new, substantial task, use an appropriately named feature branch **if the environment and task permit it**; do not switch branches without considering the working tree.
- Keep commits logically scoped with informative messages, **but only commit, merge, push, or open a PR when explicitly requested or authorized by the surrounding workflow**.
- Review `git diff` and `git status` before and after changes. Stage only intended files rather than blindly using `git add .`.
- Never force-push, reset away user work, delete branches, or rewrite shared history without explicit approval.
- Resolve merge conflicts carefully, validating the merged behavior rather than arbitrarily choosing one side.
- Keep secrets, `.venv/`, `.env`, caches, and unapproved generated data out of commits.

## 11. Security and safety boundaries

- Treat secrets as passwords: never hard-code, echo, paste into prompts, or commit them. Rotate or revoke exposed credentials through appropriate channels.
- Use least-privilege access for files, APIs, and databases.
- Request approval before destructive file/database operations, production modifications, live orders, costly external requests, or irreversible actions.
- Never execute live trades, place orders, or alter production financial data as part of a research or backtesting task unless explicitly authorized.
- Do not bypass security controls or leak sensitive information into logs, notebooks, fixtures, or generated examples.

## 12. Required agent workflow

For each requested task, follow this sequence:

1. **Define:** restate the objective and concrete acceptance criteria; identify ambiguity that materially affects correctness.
2. **Inspect:** read the relevant code, docs, tests, configuration, dependencies, and Git status.
3. **Plan:** for nontrivial work, state a brief implementation plan, expected files, and key risks.
4. **Implement:** change the fewest necessary files, preserving established interfaces and conventions.
5. **Validate:** execute relevant tests and checks; inspect diffs, edge cases, sensitive data, and reproducibility.
6. **Document:** update README, examples, or notebooks when behavior or workflow changes.
7. **Report:** summarize changes, tests actually run, outcomes, known limitations, and any decisions requiring review.

### Completion report format

```text
Summary: <what changed and why>
Files changed: <paths>
Validation: <commands executed and observed results>
Caveats: <remaining risks, assumptions, or unrun checks>
Next steps: <only if useful>
```

## 13. Definition of done

A task is done only when:

- The intended behavior is implemented with clear, stable interfaces.
- Inputs, outputs, state transitions, and relevant errors are handled deliberately.
- Relevant tests have been run, or the reason they could not run is clearly reported.
- No secrets or unapproved data were introduced into version control.
- Changes are scoped, inspected, and documented where needed.
- Quantitative results, if any, are reproducible and do not rely on look-ahead or leaked information.
- The final report distinguishes verified results from assumptions.

---

**Source basis:** WUTIS, *Algo Workshop – Software Engineering*, Thomas Kirisits & Alexander Koblinger (slides 4–30): OOP, abstraction/encapsulation, exceptions, type contracts, Git, software-project layout, virtual environments, configuration, README/AGENTS.md, notebooks, HTTP APIs, credentials, market data, SQLite, and AI-assisted development. Quantitative backtesting safeguards, approval gates, testing policies, and workflow details are practical extensions of those techniques, not direct quotations from the slides.
