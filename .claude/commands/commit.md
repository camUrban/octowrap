---
description: Analyze the current staged changes, generate a commit message following proper line width guidelines, and create the commit
---

# Create a Commit

Generate a commit message for the current staged changes, then create the commit.

## Steps

1. **Gather context** by running these commands in parallel:
    - `git status` to see all changed and untracked files
    - `git diff --staged` to see staged changes
    - This sequencer-state check, to detect an in-progress merge, cherry-pick, revert, or rebase:
      ```bash
      state=""
      if [ -f "$(git rev-parse --git-path MERGE_HEAD)" ]; then state="merge"; fi
      if [ -f "$(git rev-parse --git-path CHERRY_PICK_HEAD)" ]; then state="cherry-pick"; fi
      if [ -f "$(git rev-parse --git-path REVERT_HEAD)" ]; then state="revert"; fi
      if [ -d "$(git rev-parse --git-path rebase-merge)" ] || [ -d "$(git rev-parse --git-path rebase-apply)" ]; then state="rebase"; fi
      if [ -n "$state" ]; then echo "IN-PROGRESS: $state"; else echo "CLEAN"; fi
      ```
    - Do not stage additional files.
    - Stop and warn the user if there are no staged changes.
    - Stop and warn the user if you see staged changes that likely contain secrets (e.g., `.env`, credentials, etc.).
    - Stop and warn the user if the sequencer-state check prints anything other than `CLEAN`. Git has already prepared a commit message for this operation (e.g., `Merge branch ...`, `Revert "..."` with its `This reverts commit <SHA>.` line, or a cherry-pick's original message), and committing with `-m` would silently discard it. Tell the user which operation is in progress and that the correct way to conclude it is `git merge --continue`, `git cherry-pick --continue`, `git revert --continue`, or `git rebase --continue` respectively (or plain `git commit --no-edit` for a merge), all of which preserve the prepared message. Do not generate a message or commit.
2. **Draft the commit message** following these rules:

   ### Subject line

    - Use imperative mood (e.g., "Add feature" not "Added feature").
    - Keep it to 50 characters or fewer. This is a hard limit.
    - Do not end with a period.
    - Capitalize the first letter of the first word.

   ### Body (only if needed for non-trivial changes)

    - Separate from the subject with one blank line.
    - Draft each paragraph as one single long line, with a blank line between paragraphs. Wrapping happens mechanically in the next step; do not wrap by hand.
    - Explain *why* the change was made, not *what* was changed (the diff shows that).
    - Use complete sentences ending with periods, each of which written using an imperative mood.

   The entire message (subject and body) must contain only printable ASCII characters. Do not include a footer or co-authorship line.
3. **Validate and wrap the message** in a single Bash call. These tools run without permission prompts, so this step costs the user nothing:
   ```bash
   subject="Your subject line here"
   body="Your body text here, one long line per paragraph."
   fold -s -w 72 <<<"$body" | awk -v s="$subject" '
   BEGIN { print s; print "" }
   /[^ -~]/ { bad = 1 }
   { sub(/ +$/, ""); if (length > max) max = length; print }
   END {
     print ""
     sfail = 0
     if (length(s) > 50) { print "FAIL: subject is " length(s) " chars (max 50)"; sfail = 1 }
     if (s ~ /[^ -~]/) { print "FAIL: subject contains non-ASCII characters"; sfail = 1 }
     if (sfail == 0) print "OK: subject is " length(s) " chars and ASCII-only"
     if (bad == 1) print "FAIL: body contains non-ASCII characters"
     else print "OK: body wrapped at 72 chars and ASCII-only (" NR " lines, longest is " max " chars)"
   }'
   ```
   The output is the full message (subject, blank line, wrapped body) followed by a blank line and one status line per check.
   - Avoid the `!` character anywhere in this call (write `sfail == 0`, not `!sfail`); the harness escapes `!` in Bash commands, which corrupts the awk program.
   - Do not reference awk fields by their numbered forms (a dollar sign followed by a digit) in this snippet; slash-command argument substitution replaces those tokens with the command's arguments (empty when none are passed) and silently corrupts the program. The body loop instead uses awk's implicit current record: a bare `/regex/` pattern, bare `length`, and bare `print` all operate on the whole record without naming it.
   - If any check prints `FAIL`, fix the message and re-run this step before proceeding.
   - Use the wrapped body lines verbatim as the final body text; the status lines after the final blank line are feedback, not message content. The `awk` stage strips the trailing space that `fold -s` leaves at each break point; every resulting line is 72 characters or fewer. This is a hard limit.
   - `fold` hard-splits any token longer than 72 characters (e.g., a long URL). If the body contains such a token, place it on its own line, exclude that line from wrapping, and let it exceed the limit.
   - If there is no body, drop the `fold` stage and run only the subject checks inside an awk `BEGIN` block.
4. **Create the commit** using a heredoc to preserve formatting:
   ```bash
   git commit -m "$(cat <<'EOF'
   Subject line here (50 characters or less)

   Optional body here (wrapped at 72 characters per line).
   EOF
   )"
   ```
   The step 3 output has already displayed the full message to the user. The permission prompt for `git commit` shows the exact heredoc and serves as the user's review gate: approving it creates the commit. If the user denies the prompt, treat any feedback they give as revision input, update the message accordingly, and repeat from step 3. If they deny without feedback, stop and inform the user that the commit was cancelled.

## Important Reminders

- Never use `--no-verify` or skip pre-commit hooks.
- If the pre-commit hook fails, fix the issue and create a NEW commit (do not amend).
- Never push unless the user explicitly asks.
- If there are no changes to commit, inform the user and stop.
