---
name: save
description: Token-saving working rules for Sonalim ERP. Use at the start of any coding, debugging or planning task in this repo, and whenever the user says "save", "save tokens", "be cheap" or "keep it short".
---

# Save tokens

Get the same result with fewer reads, fewer tool calls and shorter output.

## Before exploring

- Read `CLAUDE.md` and the recalled memories first. Don't rediscover commands, layout or past decisions.
- If the user named a file or line, start there. Don't sweep the module.
- Search with Grep (use `glob`/`type` and `head_limit`) before opening files. Read only the line range you need (`offset`/`limit`), not whole files. `production/api/router.py` alone is over 3,000 lines.
- Don't read `node_modules`, `dist`, `.venv`, `__pycache__`, `*.tsbuildinfo` or `.playwright-mcp`.
- Load a skill only when its trigger actually applies. `erp-platform-architecture` is for module boundaries, events and migrations only, not for every backend edit.

## While working

- Don't spawn subagents unless the user asks. Each one re-reads the code from scratch.
- Don't run reviewer or quality-check passes unless the user asks.
- Batch independent tool calls into one message.
- Don't re-read a file after editing it. Edit and Write already fail loudly.
- Run the narrowest check that proves the change: one test file or test (`pytest path::test -q`), not the whole suite. Frontend: `npx tsc -b --force` once, at the end.
- Pipe noisy output through `tail`/`head`, or use `-q`.
- For small tasks, skip brainstorming and planning ceremonies and just do the task. Save them for new features or multi-file changes.

## When replying

- Keep it short: what changed, where (file links), and what was verified. No recap of the steps, and no restating the request.
- Don't narrate options you won't pursue.
- If you're blocked on a real decision, ask one short question instead of exploring every branch.

## Across sessions

- Save non-obvious decisions to memory so the next session doesn't re-derive them. Keep `MEMORY.md` pruned.
- When a task is done, suggest `/compact` or a fresh session before starting unrelated work.
