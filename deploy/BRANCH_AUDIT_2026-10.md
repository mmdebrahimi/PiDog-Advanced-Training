# Branch audit — 2026-10-30

Question answered: do the three side branches hold verified work that main lacks ("stranded
commits")? Method: `git rev-list --count` ahead/behind, `git cherry` patch-equivalence, and a
content diff (`git diff main <branch> --numstat`). REPORT ONLY — no merges performed; deleting
or merging a side branch is the user's call.

| branch | ahead / behind | verdict |
|---|---|---|
| laptop/sim-axis-defect-findings | 6 / 22 | **Substance fully in main.** The 6 "ahead" commits are patch-id artifacts of how main absorbed the same content (deploy/, residual env, eval_mvp, parity tests all present on main). Content diff vs main: main is strictly newer except 11 trivial lines (minor wording in CLAUDE.md/TODOS.md/companion.py/WHEN_PI_IS_BACK.md/project_state ledger) that main's later edits superseded. Historical value only (contains the axis-defect claim + same-day retraction in sequence). Safe to delete after user review. |
| stage-dr-robust | 1 / 21 | Single commit is patch-equivalent in main (`git cherry` "-"): run19 policy already staged in deploy/. Safe to delete. |
| stand-doctor-safety | 0 / 59 | Fully merged. Safe to delete. |

Bottom line: **no stranded verified work.** main is the single source of truth as of
c79e353 ("verdicts: back-left shin servo dead, P0 channel good, P3 pending swap test").

New side branch `laptop/oct-reconciliation` (this one) carries the October laptop work;
the Pi session pulls it for review — it is NOT auto-merged to main.
