# Security model

## Execution boundary

ChatCodex uses an **OS-level full-access execution model**. The agent may read, write, edit, search, patch files, and execute shell commands wherever the operating-system account running ChatCodex has permission.

ChatCodex does **not** provide a workspace sandbox or an approval gate as the security boundary for execution. The effective boundary is the OS user/account and its filesystem/process permissions.

Do not treat ChatCodex as a sandbox for untrusted agents or untrusted users. Run it under an account with only the host permissions that should be exposed to the agent.

## Local state and secrets

`file_security.py` protects ChatCodex-managed local state such as the database and secret files. It does not restrict execution paths.

Web access tokens, MCP tokens, OAuth state, and database files must not be committed to source control.

Web and MCP credentials are separate credentials and must be configured independently.

## MCP exposure

MCP transport authentication is configured by `CHATCODEX_MCP_AUTH_MODE` (`token`, `oauth`, `both`, or loopback-only `noauth`). No-auth MCP is restricted to loopback hosts.

When MCP is exposed publicly, use HTTPS and an authenticated mode. OAuth uses authorization code + PKCE and validates redirect/resource boundaries.

## Persistence

SQLite is the default persistence backend. Database access is centralized in `app/persistence/`. Execution capabilities are stateless and do not open database connections directly.

## Threat model

The system is intended for a trusted local operator controlling an agent. Public exposure must be treated as exposure of the full OS-level permissions of the ChatCodex process.
