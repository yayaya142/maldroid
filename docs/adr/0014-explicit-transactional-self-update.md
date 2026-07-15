# ADR 0014: Explicit transactional self-update

Status: accepted, 2026-07-15

## Context

The owner needs a one-command update instead of manually cloning the repository and reinstalling.
An updater necessarily performs network access and executes newly downloaded installer code, while
the normal MalDroid investigation boundary forbids automatic network access. Updating the live
private environment in place can also leave the command broken if dependency installation fails.

## Decision

`maldroid update` is an explicit owner-triggered maintenance operation, never an automatic check.
It requires Git, clones only `https://github.com/yayaya142/maldroid.git`, selects the `main` branch,
and uses a depth-one, single-branch checkout in an OS-managed temporary directory. No repository
URL or branch input is accepted. Every subprocess uses argument arrays and `shell=False`.

The updater runs the downloaded `install.sh --upgrade` with the base Python interpreter. Upgrade
mode never runs setup prompts. It moves the existing private venv to a managed backup, creates and
installs the new venv at the canonical path, and restores the backup on any failure. After success
it removes the backup. The temporary Git checkout is removed by `TemporaryDirectory` on both
success and failure.

The global runtime lease prevents update from overlapping CLI or Web work. Configuration, cases,
knowledge, reports, and external MCP connector files are outside the replaced venv and remain
unchanged.

## Consequences

- Updating is one command and leaves no persistent source checkout.
- Network access occurs only after the owner runs `maldroid update`.
- Trust follows the official repository's current `main` branch and public package index; this is
  convenient rolling delivery, not a cryptographically pinned release channel.
- A failed install returns to the previously working venv whenever one existed.
- A future signed-release channel can replace `main` without changing the transactional installer
  boundary.

