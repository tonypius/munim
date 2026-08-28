# Monorepo Restructure (uv workspace) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Relocate the existing `munim` classifier into `packages/classify/` under a `uv` workspace root, with zero behavior change, so future packages (`ingest`, `viz`) can be added as independent workspace members.

**Architecture:** The repo root becomes a *virtual* uv workspace root (a `pyproject.toml` with only a `[tool.uv.workspace]` table, no `[project]` table — it is not itself an installable package). `packages/classify/` becomes the first workspace member, holding exactly what's at the repo root today (`munim/`, `tests/`, `eval/`, `pyproject.toml`), moved with `git mv` to preserve history. No source file inside `munim/` changes.

**Tech Stack:** uv 0.8+ (already installed at this machine, confirmed `uv 0.8.19`), setuptools build backend (unchanged), pytest.

## Global Constraints

- Python `>=3.10` — unchanged from the current `pyproject.toml`.
- All 15 existing tests in `tests/test_pipeline.py` must still pass, unchanged, after the move.
- `eval/run_eval.py` must print the same benchmark numbers as `eval/RESULTS.md` (90.0% coverage, 100.0% precision) after the move — this is the regression check that matters most.
- The installed console script name stays `munim` (not renamed).
- No dependency versions change. No source code inside `munim/*.py` changes.
- Use `git mv` for every directory relocation so git preserves rename history — never delete-and-recreate.
- Do not touch `~/.munim` (the real user data directory) at any point during verification.

---

### Task 1: Move the classify package into `packages/classify/` under a uv workspace root

**Files:**
- Move (`git mv`): `pyproject.toml` → `packages/classify/pyproject.toml`
- Move (`git mv`): `munim/` → `packages/classify/munim/`
- Move (`git mv`): `tests/` → `packages/classify/tests/`
- Move (`git mv`): `eval/` → `packages/classify/eval/`
- Create: `pyproject.toml` (new, at repo root — the virtual workspace root)

**Interfaces:**
- Consumes: nothing (first task).
- Produces: a working `munim` console script installed via `uv run --package munim <cmd>` from the repo root; this is what every later task (2 and 3) and every future workspace member (Phase 1's `packages/ingest/`) relies on existing.

- [ ] **Step 1: Record the pre-move baseline**

Run from the repo root, in the current (pre-move) layout:

```bash
python3 -m pytest tests/ -q
```

Expected: `15 passed`. Write down this number — it's what Step 6 must reproduce after the move. If it's not 15 passed right now, stop and fix that first; don't restructure on top of a red baseline.

- [ ] **Step 2: Move the three directories with `git mv`**

```bash
mkdir -p packages/classify
git mv munim packages/classify/munim
git mv tests packages/classify/tests
git mv eval packages/classify/eval
git mv pyproject.toml packages/classify/pyproject.toml
```

Do not edit `packages/classify/pyproject.toml`'s contents — it's moving unchanged; it is still a complete, correct package manifest for `munim` (name, dependencies, `[project.scripts]`, `[tool.setuptools.packages.find]`, and `[tool.setuptools.package-data]` are all unaffected by which directory the file lives in, since every path in it — e.g. `web/index.html`, `normalize/packs/*.yaml` — is already relative to the package source, not the repo root).

- [ ] **Step 3: Write the new root-level workspace `pyproject.toml`**

```toml
[tool.uv.workspace]
members = ["packages/*"]
```

This is a *virtual* workspace root — no `[project]` table, so `uv` won't try to build or install "the repo root" as a package. Verified working with `uv 0.8.19` on this machine before writing this plan (a two-member scratch workspace built and ran cleanly with this exact pattern).

- [ ] **Step 4: Sync the workspace**

```bash
uv sync
```

Expected: creates `.venv` at the repo root, resolves and installs `munim` (editable) from `packages/classify`, prints `+ munim==0.1.0 (from file://.../packages/classify)`.

- [ ] **Step 5: Confirm the console script resolves**

```bash
uv run --package munim munim --help
```

Expected: the same Typer help output as before the move (command list: `init`, `import`, `review`, `reclassify`, `report`, `stats`, `web`, `classify`, `learn`, `categories`, `accounts`, `export`, `doctor`, `contribute`, `relabel`, `eval`).

- [ ] **Step 6: Run the test suite from the new location**

```bash
uv run --package munim pytest packages/classify/tests -q
```

Expected: `15 passed` — matching Step 1's baseline exactly.

- [ ] **Step 7: Run the eval benchmark from the new location and confirm reproducibility**

The `eval` command's local import (`from eval.run_eval import evaluate` in `munim/cli.py`) only resolves when the current working directory contains `eval/` as a sibling of the installed `munim` import path — i.e. when cwd is `packages/classify/`. Use `--directory`:

```bash
uv run --package munim --directory packages/classify munim eval
```

Expected output matches `packages/classify/eval/RESULTS.md` exactly:
```
Fixture: synthetic_in.csv (30 transactions)
Coverage  (classified without user input): 90.0%
Precision (of those, correct):             100.0%
```

Also confirm the standalone script path still works (this is what a future CI job would call directly, without going through the CLI's local import):

```bash
uv run --package munim --directory packages/classify python eval/run_eval.py
```

Expected: identical output to the command above.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "Restructure into a uv workspace: move classify into packages/classify"
```

---

### Task 2: Update the Makefile to delegate through the uv workspace

**Files:**
- Modify: `Makefile` (repo root)

**Interfaces:**
- Consumes: Task 1's working `uv run --package munim` invocations (Steps 4–7).
- Produces: `make install` / `make test` / `make eval` / `make demo` / `make clean` as the stable entry points later tasks and contributors use — don't rename these targets.

- [ ] **Step 1: Replace the Makefile contents**

```makefile
.PHONY: install test eval demo clean

install:
	uv sync

test:
	uv run --package munim pytest packages/classify/tests -q

eval:
	uv run --package munim --directory packages/classify python eval/run_eval.py

demo: ## import the fixture into a throwaway store and show a report
	uv run --package munim munim init && \
	uv run --package munim munim import packages/classify/eval/fixtures/synthetic_in.csv

clean:
	rm -rf packages/*/build packages/*/dist packages/*/*.egg-info .pytest_cache .venv
```

(Dropped the old `demo` target's `MUNIM_DEMO=1 python -c "print(...)"` — it never actually ran anything, just printed instructions. The new version actually runs the demo, which is more useful and no riskier: `munim init`/`munim import` write to `~/.munim`, same as any real invocation always has.)

- [ ] **Step 2: Verify all targets work end to end**

```bash
make install
make test
make eval
```

Expected: `install` completes without error, `test` prints `15 passed`, `eval` prints the same `90.0% / 100.0%` numbers as Task 1 Step 7.

- [ ] **Step 3: Commit**

```bash
git add Makefile
git commit -m "Point Makefile targets at the uv workspace layout"
```

---

### Task 3: Fix repo-relative path references in docs and update the roadmap status

**Files:**
- Modify: `docs/adding-a-bank-adapter.md:28`
- Modify: `docs/pipeline.md:9`
- Modify: `CONTRIBUTING.md:7`
- Modify: `CONTRIBUTING.md:18`
- Modify: `README.md` (Quick start block)
- Modify: `docs/phases.md` (Phase 0 status line)

**Interfaces:**
- Consumes: nothing new — this task only touches prose/docs, no code.
- Produces: accurate paths for anyone (human or agent) reading the docs after the move; an accurate Phase 0 status for Phase 1 planning to reference.

These four are the *only* doc references to the old `munim/<subpath>` file-path form in the repo (confirmed by grep before writing this plan: `grep -rn "munim/data\|munim/normalize" docs/*.md CONTRIBUTING.md`). Every other `munim ...` mention in the docs refers to the CLI command or the package name itself, not a file path — leave those alone.

- [ ] **Step 1: Fix `docs/adding-a-bank-adapter.md:28`**

Change:
```
`munim/normalize/packs/<region>.yaml`. Each rule needs a fixture line in
```
to:
```
`packages/classify/munim/normalize/packs/<region>.yaml`. Each rule needs a fixture line in
```

- [ ] **Step 2: Fix `docs/pipeline.md:9`**

Change the table cell:
```
| 2 | Normalize | `munim/normalize/` | raw string -> merchant candidate / payee handle, via region pack | — |
```
to:
```
| 2 | Normalize | `packages/classify/munim/normalize/` | raw string -> merchant candidate / payee handle, via region pack | — |
```

- [ ] **Step 3: Fix `CONTRIBUTING.md:7` and `:18`**

Change:
```
Add patterns to `munim/data/dictionary/<region>.yaml`:
```
to:
```
Add patterns to `packages/classify/munim/data/dictionary/<region>.yaml`:
```

Change:
```
- Use categories from `munim/data/categories.yaml`.
```
to:
```
- Use categories from `packages/classify/munim/data/categories.yaml`.
```

- [ ] **Step 4: Update the README Quick start block**

Change:
```
pip install munim            # (or: pip install -e . from this repo)
```
to:
```
uv sync                      # from a checkout of this repo (uv workspace)
```

Leave the rest of the Quick start block (`munim init`, `munim import statement.csv`, etc.) exactly as is — those are commands run *inside* the activated environment (`uv run munim init`, or `source .venv/bin/activate` first), and this plan isn't changing the CLI's own command surface. Add one line directly under the code block:

```markdown
This repo is a uv workspace — `packages/classify/` is the classifier
you just installed; see [docs/phases.md](docs/phases.md) for what's
being added alongside it.
```

- [ ] **Step 5: Update `docs/phases.md`'s Phase 0 status**

Change:
```
## Phase 0 — Monorepo restructure (uv workspace)
**Status: planned**
```
to:
```
## Phase 0 — Monorepo restructure (uv workspace)
**Status: done**
```

- [ ] **Step 6: Verify no stale path references remain**

```bash
grep -rn '`munim/normalize\|`munim/data\|munim/data/\|munim/normalize/' docs/*.md CONTRIBUTING.md README.md
```

Expected: no output (all four original hits fixed, and the README's new line doesn't match this pattern since it says `packages/classify/`).

- [ ] **Step 7: Commit**

```bash
git add docs/adding-a-bank-adapter.md docs/pipeline.md CONTRIBUTING.md README.md docs/phases.md
git commit -m "Update doc paths and roadmap status for the packages/classify move"
```

---

## Post-plan state

After Task 3, the repo root has: a virtual-workspace `pyproject.toml`, `packages/classify/` (the entire previous repo contents, working identically), `docs/` (including the new `phases.md` roadmap and this plan), and `Makefile`/`README.md`/`CONTRIBUTING.md`/`LICENSE` unchanged at the root. `packages/ingest/` does not exist yet — it's created from scratch as the first task of the Phase 1 plan (Gmail fetch), not here, so this plan stays a pure, independently-testable relocation with no speculative scaffolding.
