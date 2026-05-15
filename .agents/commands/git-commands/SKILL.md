---
name: git-commands
description: Git operations assistant. Use when the user invokes git commands like /gsave, /gpush, /gpull, /gbranch, /gmerge, /gswitch, /gstatus, /glog, /gdelete, or /gundo. Triggers include requests to commit changes, push to GitHub, pull from remote, create branches, merge branches, switch branches, check status, view logs, delete branches, or undo commits.
---

# Git Command Controller

Execute git commands based on the subcommand provided.

## Commands

### /gsave [message]

Commit all changes with a descriptive commit message.

1. Stage all changes: `git add -A`
2. If no message provided, analyze the changes with `git diff --staged` and generate a clear, conventional commit message in the format `type(scope): description`
3. Commit the changes

**Examples:**
- `/gsave` → Stage all changes, auto-generate commit message based on diff, then commit
- `/gsave fix: resolve login bug` → Stage all changes and commit with message "fix: resolve login bug"

---

### /gpush [branchname]

Commit changes in the specified branch and push that branch to GitHub.

1. Stage all changes: `git add -A`
2. Generate a proper commit message based on the changes if none provided
3. Commit the changes
4. Push the branch to GitHub:
   - If branch exists on remote: `git push origin <branchname>`
   - If branch doesn't exist on remote: `git push -u origin <branchname>`

**If no branch name provided:**
- Ask: "Which branch do you want to push to GitHub?"
- Show a list of available branches: `git branch`
- The first option (and default) must be "main" branch
- Wait for user to choose before proceeding

**Examples:**
- `/gpush main` → Commit all changes in main branch, then push main to GitHub
- `/gpush develop` → Commit all changes in develop branch, then push develop to GitHub
- `/gpush feature/login` → Commit all changes in feature/login, then push to GitHub
- `/gpush` → Ask "Which branch do you want to push to GitHub?" and show available branches (main as default)

---

### /gpull [branch]

Pull latest changes from the remote repository.

- If branch specified, pull that branch: `git pull origin <branch>`
- If no branch specified, pull the current branch: `git pull origin <current-branch>`

**Examples:**
- `/gpull` → Pull latest changes for current branch
- `/gpull main` → Pull latest changes from main branch

---

### /gbranch <branchname>

Create a new branch and switch to it.

- Create and switch: `git checkout -b <branchname>`
- Confirm the switch was successful by showing the new branch name

**Examples:**
- `/gbranch test` → Create a new branch called "test" and switch to it
- `/gbranch feature/auth` → Create branch "feature/auth" and switch to it

---

### /gmerge <branchname>

Merge the specified branch INTO the current branch.

1. Show which branch you're currently on: `git branch --show-current`
2. Merge: `git merge <branchname>`
3. Report success or any conflicts

**Examples:**
- `/gmerge test` → Merge "test" branch into current branch
- `/gmerge develop` → Merge "develop" into current branch

---

### /gswitch <branchname>

Switch to an existing branch.

- Use: `git checkout <branchname>`
- Warn if there are uncommitted changes that would be lost

**Examples:**
- `/gswitch test` → Switch to the "test" branch
- `/gswitch main` → Switch to the main branch

---

### /gstatus

Show the current repository status.

Display:
- Current branch
- Staged, unstaged, and untracked files
- Ahead/behind status compared to remote

**Examples:**
- `/gstatus` → Show full repository status

---

### /glog [n]

Show commit history.

- Default: show last 10 commits: `git log --oneline -10`
- If n specified, show last n commits: `git log --oneline -n`

**Examples:**
- `/glog` → Show last 10 commits
- `/glog 5` → Show last 5 commits

---

### /gdelete <branchname>

Delete a branch with safety checks. **Requires user confirmation.**

**Before deleting, you MUST:**

1. Check if the branch has been merged to main: `git branch --merged main`
2. Show a clear report:
   - If merged to main: "Branch 'X' has been merged to main."
   - If NOT merged to main: "⚠️ WARNING: Branch 'X' has NOT been merged to main. Deleting will lose all unmerged changes."
3. Ask for explicit permission: "Do you want to proceed with deleting this branch? (yes/no)"
4. Only delete after user confirms with "yes"

**Important:** Do NOT merge the branch to main before deleting. Only report the merge status.

**Deletion command:** `git branch -d <branchname>` (safe delete) or `git branch -D <branchname>` (force delete if not merged)

**Examples:**
- `/gdelete test` → Check if "test" is merged to main, warn user, ask for confirmation, then delete if approved
- `/gdelete feature/old` → Report merge status, warn if unmerged, ask permission before deleting

---

### /gundo

Revert to the previous commit. Use this when development went wrong and you want to discard recent changes.

**Before reverting, you MUST:**

1. Show the current commit that will be discarded (commit hash, message, date): `git log -1 --format="%H%n%s%n%cd" HEAD`
2. Warn: "⚠️ WARNING: This will permanently discard the last commit and all its changes."
3. Ask for explicit permission: "Do you want to revert to the previous commit? (yes/no)"
4. Only revert after user confirms with "yes"

**When confirmed:**
- Run `git reset --hard HEAD~1` to discard the last commit and all changes
- Show the commit you are now on

**Examples:**
- `/gundo` → Show last commit info, warn about losing changes, ask confirmation, then revert if approved

---

## Behavior Guidelines

1. **Always confirm destructive operations** (`/gdelete`, `/gundo`)
2. **For `/gpush` without branch:** Show available branches and let user choose (main as default)
3. **Show clear warnings** for unmerged branches before deletion and before reverting commits
4. **Handle errors gracefully** and provide helpful suggestions
5. **For `/gsave` without message:** Analyze `git diff --staged` to understand what changed and generate an appropriate conventional commit message

## Quick Reference

| Command | Description | Example |
| --- | --- | --- |
| `/gsave` | Commit changes | `/gsave feat: add login` |
| `/gpush` | Commit + push branch | `/gpush main` |
| `/gpull` | Pull from remote | `/gpull develop` |
| `/gbranch` | Create & switch to new branch | `/gbranch feature/auth` |
| `/gmerge` | Merge branch into current | `/gmerge test` |
| `/gswitch` | Switch to existing branch | `/gswitch main` |
| `/gstatus` | Show repo status | `/gstatus` |
| `/glog` | Show commit history | `/glog 5` |
| `/gdelete` | Delete branch (with confirmation) | `/gdelete old-branch` |
| `/gundo` | Revert to previous commit | `/gundo` |