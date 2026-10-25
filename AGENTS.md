# AGENTS.md

Read `CLAUDE.md` for this repository's catalog conventions and validation workflow.

## Git synchronization requires explicit permission

- Never run `git pull` without the user's explicit permission for that synchronization.
- Do not substitute an equivalent operation, such as `git fetch` followed by
  `git merge` / `git rebase`, or otherwise advance a local branch to the remote
  state without that permission.
- The maintainer reviews incoming changes and handles synchronization in GitHub
  Desktop. Implementing a task, publishing a release or completing a PR does not
  authorize synchronizing the local checkout.

