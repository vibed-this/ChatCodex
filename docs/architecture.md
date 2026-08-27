# ChatCodex architecture

## Runtime composition

```text
FastAPI lifespan
    |
    +-- Runtime
        +-- Persistence (Database / SettingsStore)
        +-- Authenticator / WebAuthenticator
        +-- NativeRuntimeManager / TunnelManager
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
- `shell.py`: synchronous shell execution plus managed background shells. `shell_spawn` returns immediately with a shell ID and a temporary output path; stdout/stderr are redirected directly to that file. `shell_wait` can wait with an optional timeout without killing the shell when the timeout expires, and `shell_kill` terminates the shell process tree.
- `patch.py`: patch parse/validation/materialization/commit.
- `_common.py`: capability-local algorithms and shared constants.
- `errors.py`: stable execution error taxonomy.

The former `execution/backend.py` implementation has been removed.

## MCP layer

`app/mcp/schemas.py` contains the canonical core tool definitions. The MCP adapter registers handlers with FastMCP but does not use FastMCP private registries. `ContractFastMCP` exposes the canonical input schema and description to MCP clients.

### Background shell usage

`bash` is synchronous and blocks until the command finishes (or its timeout is reached). Long-running, ordinary background, and resident tasks must use `shell_spawn` instead. The spawn call does not collect command output in memory; the child process writes stdout and stderr directly to a temporary file and the tool returns its path. The AI should use `read` or `grep` against that path to inspect output.

`shell_wait(shellId, timeout)` waits for termination. `timeout` is in milliseconds; if it expires, the tool returns immediately and leaves the shell running. `shell_kill(shellId)` terminates the shell and its process tree. `batch_call` can be used to issue several `shell_spawn` calls first and then several `shell_wait` calls, allowing multiple background tasks to start without waiting between starts.

## Persistence layer

`app/persistence/database.py` owns the SQLite connection and schema. Higher-level repositories isolate specific persistence concerns:

- `settings.py`: persistent application settings.
- `oauth.py`: reserved boundary for OAuth client persistence as that concern is extracted from the authentication service.

Execution services remain stateless and persistence-free.

## Security boundary

ChatCodex intentionally uses OS-level full access rather than a workspace sandbox. The OS account running ChatCodex is the effective execution permission boundary. See `SECURITY.md`.
