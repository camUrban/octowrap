---
description: Refresh an existing pull request's title, body, and labels to reflect new commits, following the same conventions as create-pr
---

# Update a Pull Request

Refresh the open pull request for the current branch so its title, body, and labels reflect the commits added (or undone) since it was last written, then apply the changes with `gh pr edit`. This is an incremental refresh: it preserves human-authored content and changes only what the new or removed work requires.

This command takes no arguments. It operates on the single open PR whose head is the current branch, and it leaves that PR's base branch and draft status unchanged.

## Shared conventions

Read `.claude/commands/create-pr.md` and apply every convention it defines: the concise prose body style (no headings, section labels, bullet lists, checklists, or test plans) and its level of detail, the body writing conventions (no hard-wrapping, and backticking every identifier, path, and inline code span), the title rules (no `[FEATURE]`, `[BUG]`, or other bracketed prefix, and the 42-character limit with its awk check), label selection from `.github/labels.yml`, and the environment constraints (an already-pushed branch; only the `gh pr` porcelain and never `gh api`; an ASCII-only title and body with no footer beyond the AI-use policy's `Assisted-by:` disclosure line; and never attaching a milestone or project or requesting reviewers). Only the differences specific to updating an existing PR are spelled out below.

## Environment constraints

- `git push` is denied, so this command cannot push. The new commits must already be on the remote; if the branch has unpushed commits, stop and ask the user to push, then re-run.
- `gh api` is denied. Use only the `gh pr` porcelain (`gh pr view`, `gh pr edit`).

## Steps

1. **Locate the PR and gather context** with these read-only commands (all run without permission prompts):
    - `git status -sb` to confirm the branch is pushed and current, using the same first-line interpretation as create-pr. If the branch has no upstream, a `[gone]` upstream, or any `[ahead N]` marker, stop and tell the user to push first so the PR reflects the new commits.
    - `gh pr list --head <branch> --state open` to find the open PR. If there is none, stop and tell the user to run `/create-pr` first. If there is more than one, stop and report them rather than guessing.
    - `gh pr view <number> --json number,url,title,body,labels,baseRefName,isDraft` to read the PR's current state. Use `baseRefName` as the base for all diffs; do not assume `main`.
    - `git log --oneline <base>..HEAD`, `git diff --stat <base>...HEAD`, and `git diff <base>...HEAD` to see the full, current change set the PR should describe.
    - Read `.github/labels.yml` so the labels come from the canonical set.
2. **Diff the PR against reality.** Compare the existing body against the current diff to identify (a) new changes not yet described, (b) described changes that have since been undone or reverted and no longer appear in the diff, and (c) prose that is now inaccurate or has formatting defects.
3. **Refresh the body incrementally**, preserving human-authored content and changing only what is required:
    - Keep the author's motivating prose and any inline issue references, except where the edits below require a change.
    - Extend the body to cover genuinely new scope, and trim it where scope was removed. Add a paragraph only when the new work is a distinct concern; otherwise fold it into the paragraph it belongs to. Keep the result as concise as create-pr requires, so do not let repeated refreshes accrete padding.
    - Correct typos and formatting defects anywhere in the body, including removing hard wraps, fixing backticking, and stripping any headings, section labels, bullet lists, checklists, or test plans that have crept in, even in otherwise-preserved passages.
    - Apply the AI-use policy's disclosure (docs/AI_USE_POLICY.md): keep any existing `Assisted-by:` line as the body's last line. When none is present, add one of the form `Assisted-by: MODEL_OR_TOOL_NAME` (preceded by a single blank line) if the conversation context makes clear the user used AI on the PR, or if the requested updates to the description go beyond formatting and typo corrections. Write the tag's casing exactly as shown, include no email address, and use your own model name unless the context names a different assisting tool.
4. **Re-evaluate the title and labels** against the new change set:
    - Confirm the title still fits and still describes the change set, and remove any legacy `[FEATURE]` or `[BUG]` prefix it carries. Change it only if it carries such a prefix, the new work makes it inaccurate, or it breaks the rules, and re-run the 42-character and ASCII awk check from create-pr on any new title.
    - Recompute the applicable labels from `.github/labels.yml`. Plan to add newly applicable labels and remove labels that no longer apply.
5. **Present the planned update** in your reply: the PR number and URL, the old and new title (or "unchanged"), the labels to add and remove (or "unchanged"), and the full new body. This is the user's review opportunity. If nothing needs to change, say so and stop without editing.
6. **Apply the update** with `gh pr edit`. Provide the body on stdin via a quoted heredoc so the permission prompt shows the exact new body as the final review gate:
   ```bash
   gh pr edit <number> \
     --title "Updated title here" \
     --add-label "new-label" \
     --remove-label "stale-label" \
     --body-file - <<'EOF'
   First paragraph of the refreshed body.

   Assisted-by: MODEL_OR_TOOL_NAME
   EOF
   ```
    - Include `--title` only if the title changed. Repeat `--add-label` and `--remove-label` once per label, and omit them when labels are unchanged. Do not pass `--milestone`, `--project`, `--reviewer`, `--base`, or any draft flag; this command leaves the base branch and draft status as they are.
    - The `gh pr edit` permission prompt is the final gate. If the user denies it, treat any feedback as revision input, update the plan, and repeat from step 5. If they deny without feedback, stop and report that the PR was not changed.
7. **Confirm** by reporting the PR's URL.

## Important Reminders

- This command edits an existing PR; if none exists for the branch, stop and direct the user to `/create-pr`.
- Preserve human-authored content by default; change prose only to add new scope, remove undone scope, or fix typos and formatting (including hard wraps and any structure the concise style forbids).
- Never push; if the new commits are not on the remote, stop and ask the user to push.
- Never use `gh api`; use only the `gh pr` porcelain.
- Apply all create-pr conventions to the refreshed title, body, and labels: ASCII-only with no hard-wrapping, no title prefixes and the 42-character title limit, backticked identifiers, concise prose with no headings or lists, the policy's `Assisted-by:` line as the only permitted footer, and no milestone, project, or reviewer changes.
- Leave the PR's base branch and draft status unchanged.
