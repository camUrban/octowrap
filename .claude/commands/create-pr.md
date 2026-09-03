---
description: Draft a pull request in this repository's concise prose style, then open it with the GitHub CLI
---

# Create a Pull Request

Draft a pull request for the current branch whose body follows this repository's concise prose style, then open it with `gh pr create`.

This command takes two independent, optional inputs through its argument, in any order. They are unrelated: setting one has no effect on the other.

- A base branch name, which is any token other than `draft`. If omitted, the base defaults to `main`.
- The literal keyword `draft`, which opens the PR as a draft. If omitted, the PR is opened ready for review.

Examples: `/create-pr` (base `main`, ready), `/create-pr develop` (base `develop`, ready), `/create-pr draft` (base `main`, draft), and `/create-pr develop draft` (base `develop`, draft).

## Environment constraints

- `git push` is denied in this environment, so this command cannot push the branch. The branch must already exist on the remote and be up to date. If it is not, stop and ask the user to push, then re-run.
- `gh api` is denied. Use only the `gh pr` porcelain subcommands. Do not fall back to the REST or GraphQL API.
- The title and body must contain only printable ASCII characters. Do not add a footer or any "Generated with" or "Co-Authored-By" line. The only permitted trailing line is the AI-use policy's `Assisted-by:` disclosure described in step 3.

## Steps

1. **Gather context** by running these read-only commands (all run without permission prompts):
    - `git status -sb` to read the current branch and its upstream state from the first line:
        - `## <branch>` with no `...<remote>` segment means the branch has no upstream. Stop: tell the user to push the branch first.
        - `...<remote> [gone]` means the upstream was deleted. Stop: tell the user to push the branch first.
        - `...<remote> [ahead N]` or `[ahead N, behind M]` means there are unpushed local commits. Stop: tell the user to push first so the PR includes them.
        - `...<remote>` with no `ahead`/`gone` marker means the branch is pushed and current. Proceed.
        - If the branch is the base branch itself (e.g., `main`), stop: a PR cannot be opened from the base onto itself.
    - `gh pr list --head <branch> --state open` to check for an existing open PR for this branch. If one exists, stop and report its number and URL rather than opening a duplicate.
    - `git log --oneline <base>..HEAD` to see the commits the PR will contain. If this is empty, stop: there is nothing to propose.
    - `git diff --stat <base>...HEAD` and `git diff <base>...HEAD` to understand the actual changes. Base the description on this diff, not on the commit messages alone.
2. **Choose and verify the title** following this repository's conventions:
    - Sentence case, imperative mood, no trailing period.
    - Do not prefix the title with `[FEATURE]`, `[BUG]`, or any other bracketed tag. Classification lives in the labels, not the title.
    - A title may state an outcome (e.g., "Add --diff-only mode for incremental adoption").
    - The entire title must be at most 42 characters. This repository squash-merges every PR, and GitHub uses the PR title plus a ` (#<number>)` suffix as the squash commit's subject, so 42 characters keeps that subject within the 50-character commit subject limit through four-digit PR numbers. Verify the length and ASCII-only content with a single awk call (this runs without a permission prompt, so it costs the user nothing):
      ```bash
      title="Your title here"
      awk -v s="$title" 'BEGIN {
        fail = 0
        if (length(s) > 42) { print "FAIL: title is " length(s) " chars (max 42)"; fail = 1 }
        if (s ~ /[^ -~]/) { print "FAIL: title contains non-ASCII characters"; fail = 1 }
        if (fail == 0) print "OK: title is " length(s) " chars and ASCII-only"
      }'
      ```
      Avoid the `!` character anywhere in this call (write `fail == 0`, not `!fail`); the harness escapes `!` in Bash commands, which corrupts the awk program. If the check prints `FAIL`, shorten the title and re-run this check before proceeding.
3. **Draft the body** as concise prose. This repository has no pull request template, and its PR bodies carry no headings, section labels, bullet lists, checklists, or test plans. Match the level of detail seen in this repository's recent substantive PRs.

   Apply these writing conventions throughout the body:
    - Do not hard-wrap. Write each paragraph as a single continuous line; this repository never hard-wraps Markdown and GitHub reflows it for display. This is the opposite of the commit-message convention, which wraps at 72 characters.
    - Enclose every file, path, module, class, function, flag, and any other identifier or inline code in backticks (for example, `rewrap.py`, `process_content()`, and `--diff-only`).

   Structure the body as follows:
    - One prose paragraph for a small change, and up to three or four for a larger one, with a blank line between paragraphs. Never pad a small change to fill space.
    - Each paragraph opens with the problem or the state of affairs that motivated the change, then states what the change does about it. Explain *why* the change was made and what behavior it alters or leaves alone, rather than narrating the diff file by file.
    - For a bug fix, characterize the symptom, distinguish an incidental artifact from intended behavior, and state what behavior is left unchanged. For a new feature, note backward compatibility when relevant (e.g., a new default that leaves existing callers unaffected). For a larger change, cover the mechanism and the scope, including anything deliberately left out.
    - When the PR groups unrelated housekeeping with the main change, give the housekeeping its own short closing paragraph rather than mixing it into the others.
    - Link genuinely related issues inline using GitHub's closing syntax (`Fixes #<n>` for a bug, `Closes #<n>` for a feature) in the paragraph that addresses them. Do not add an issues line if there are none.
   Always end the body with the AI-use policy's disclosure (docs/AI_USE_POLICY.md): a final line of the form `Assisted-by: MODEL_OR_TOOL_NAME`, separated from the last paragraph by a single blank line. Running this command is AI drafting assistance by definition, so the line is unconditional. Write the tag's casing exactly as shown, include no email address, and use your own model name.
4. **Choose labels, assignee, and draft status**:
    - Read `.github/labels.yml`, the canonical label set, and pick the applicable labels from it. Include `feature` or `bug` (or both) when the change warrants them, since the labels alone carry the classification. Use `maintenance` for documentation, testing, robustness, or tooling work, and add `github_actions`, `pre_commit`, or `dependencies` when the change touches those areas.
    - Always assign the PR to the current user with `--assignee "@me"`. The `@me` token resolves to whoever `gh` is authenticated as.
    - Do not attach a milestone or a project, and do not request any reviewers. Never pass `--milestone`, `--project`, or `--reviewer`.
    - Open the PR as a draft only if the argument requested it; otherwise open it ready for review.
5. **Present the draft** in your reply: the chosen base branch, title, full body, selected labels, assignee, and whether it is a draft. This is the user's review opportunity.
6. **Open the PR** with a single command. Provide the body on stdin via a quoted heredoc so its backticks and markdown are preserved literally and the permission prompt shows the user the exact body as a final review gate:
   ```bash
   gh pr create \
     --base main \
     --title "Your title here" \
     --assignee "@me" \
     --label "label-one" --label "label-two" \
     --body-file - <<'EOF'
   First paragraph of the body.

   Assisted-by: MODEL_OR_TOOL_NAME
   EOF
   ```
    - Repeat `--label` once per label. Add `--draft` if requested. The head branch defaults to the current branch, so `--head` is not needed. Do not add `--milestone`, `--project`, or `--reviewer`.
    - The `gh pr create` permission prompt is the final gate. If the user denies it, treat any feedback as revision input, update the draft, and repeat from step 5. If they deny without feedback, stop and report that no PR was opened.
7. **Confirm** by reporting the new PR's URL, which `gh pr create` prints on success.

## Important Reminders

- Never push, and never use `--no-verify` or any flag that bypasses checks. If the branch is not pushed and current, stop and ask the user to push.
- Never use `gh api`; stick to the `gh pr` porcelain.
- The body is concise prose: no headings, section labels, bullet lists, checklists, or test plans.
- Never prefix the title with `[FEATURE]`, `[BUG]`, or any other bracketed tag (classification lives in the labels), and keep the whole title to at most 42 characters, verified with the awk check.
- Keep the title and body ASCII-only, with no footer beyond the policy's `Assisted-by:` disclosure line.
- The body is Markdown: do not hard-wrap it, and backtick every identifier, path, and inline code span.
- Do not open a PR from the base branch, and do not open a duplicate when one already exists for the branch.
- Do not attach a milestone or project, and do not request reviewers. Always self-assign with `--assignee "@me"`, which targets whoever `gh` is authenticated as.
