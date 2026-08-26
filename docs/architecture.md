# ChatCodex architecture

## Runtime composition

```text
FastAPI lifespan
    |
    +-- Runtime
        +-- Persistence (Database / SettingsStore / AuditRepository)
        +-- Authenticator / WebAuthenticator
        +-- AppServerManager / TunnelManager / EventBroker
        +-- ExecutionService
        |     +-- FilesystemService
        |     +-- SearchService
        |     +-- ShellService
        |     +-- PatchService
        +-- MCP transport adapter
```

`app/main.py` is the HTTP composition root. It does not construct the runtime at import time. The runtime is created during FastAPI lifespan startup and released during shutdown.

## Execution layer

Execution capabilities are transport-independent. `ExecutionService` composes the capability services and normalizes execution errors. The capability modules do not import FastAPI or FastMCP and do not access persistence.

- `filesystem.py`: read/write/edit/delete/image/directory operations.
- `search.py`: glob/grep.
- `shell.py`: local shell execution, timeout, output limiting, and process-tree termination.
- `patch.py`: patch parse/validation/materialization/commit.
- `_common.py`: capability-local algorithms and shared constants.
- `errors.py`: stable execution error taxonomy.

The former `execution/backend.py` implementation has been removed.

## MCP layer

`app/mcp/schemas.py` contains the canonical core tool definitions. The MCP adapter registers handlers with FastMCP but does not use FastMCP private registries. `ContractFastMCP` exposes the canonical input schema and description to MCP clients.

## Persistence layer

`app/persistence/database.py` owns the SQLite connection and schema. Higher-level repositories isolate specific persistence concerns:

- `settings.py`: persistent application settings.
- `audit.py`: approval audit records.
- `oauth.py`: reserved boundary for OAuth client persistence as that concern is extracted from the authentication service.

Execution services remain stateless and persistence-free.

## Security boundary

ChatCodex intentionally uses OS-level full access rather than a workspace sandbox. The OS account running ChatCodex is the effective execution permission boundary. See `SECURITY.md`.
