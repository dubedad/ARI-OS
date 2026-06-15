# Registering The Cortex MCP Server In Any Client

The server runs locally over stdio:

`python -m ari_os.tools.cortex.mcp_server stdio`

## Generic `.mcp.json` (Claude Code, And Most JSON MCP Clients)

```json
{
  "mcpServers": {
    "ari-os-cortex": {
      "command": "python",
      "args": ["-m", "ari_os.tools.cortex.mcp_server", "stdio"]
    }
  }
}
```

## Claude Code One-Liner

```sh
claude mcp add ari-os-cortex -- python -m ari_os.tools.cortex.mcp_server stdio
```

## Codex (`~/.codex/config.toml`)

```toml
[mcp_servers.ari-os-cortex]
command = "python"
args = ["-m", "ari_os.tools.cortex.mcp_server", "stdio"]
```

## Generic Stdio JSON-RPC Note

Any MCP client that can launch a stdio server can register `ari-os-cortex` by
running the command above and speaking MCP JSON-RPC over the child process's
stdin and stdout.
