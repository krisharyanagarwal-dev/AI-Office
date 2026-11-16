# MCP Servers Setup Guide

## Overview
You have successfully installed three Model Context Protocol (MCP) servers:
1. **Filesystem Server** - For file operations (read/write/create/edit/search)
2. **Git Server** - For Git repository operations (status, diff, commit, branch, etc.)
3. **Everything Server** - Reference server that exercises all MCP features (mainly for testing)

## Installation Verification
All servers are installed globally and ready to use:
- `mcp-server-filesystem` (Node.js based)
- `mcp-server-git` (Python based)  
- `mcp-server-everything` (Node.js based)

## Usage Instructions

### 1. Manual Server Startup
You can start each server manually in separate terminal windows:

**Filesystem Server** (provides file operations for your test project):
```bash
mcp-server-filesystem /Users/aryanagarwal/test-mcp-project
```

**Git Server** (provides git operations for your test repository):
```bash
mcp-server-git --repository /Users/aryanagarwal/test-mcp-project
```

**Everything Server** (for testing MCP features):
```bash
mcp-server-everything
```

### 2. Configuration File Approach (Recommended)
A configuration file has been created at: `/Users/aryanagarwal/.mcp/servers.json`

To use this configuration with MCP-compatible clients:

**For Claude Desktop:**
Copy the configuration to: `~/Library/Application Support/Claude/claude_desktop_config.json`

**For VS Code with MCP Extension:**
Use the configuration directly in your VS Code settings or workspace `.vscode/mcp.json`

**For NeMo Gym or Custom Agents:**
Point your agent to the configuration file or start the servers manually as needed.

### 3. Testing the Servers

#### Fileserver Test:
Once the filesystem server is running, you should be able to:
- Read files: `read_text_file` with path like `/README.md`
- List directory: `list_directory` with path `/`
- Create/edit files: `write_file`, `edit_file`

#### Git Server Test:
Once the git server is running, you should be able to:
- Check status: `git_status`
- See diff: `git_diff_unstaged` or `git_diff_staged`
- View log: `git_log`
- Commit changes: `git_commit` with message
- Create branches: `git_create_branch`

### 4. Integration with NeMo Gym (Zero API Cost Setup)
As discussed previously, you can integrate these MCP servers with NeMo Gym for coding agents:

1. **Use NeMo Gym's infrastructure** for code generation/verification
2. **Call MCP servers as external tools** from your NeMo Gym agent
3. **Leverage NVIDIA's free tiers** or self-hosted Nemotron models for zero API cost
4. **Use the `nv-route` skill** to offload LLM tasks to NVIDIA's free worker fleet

Example integration approach:
- Your NeMo Gym agent generates code changes
- Agent uses filesystem MCP server to write/edit files
- Agent uses git MCP server to commit changes
- NeMo Gym's built-in validators check code correctness
- All LLM processing uses free/self-hosted Nemotron models

### 5. Security Notes
- Servers only access directories you explicitly specify
- Filesystem server prevents directory traversal attacks
- Git server operates only on the specified repository
- Always review MCP server permissions before granting access

### 6. Finding More MCP Servers
Explore additional servers at:
- Official Registry: https://registry.modelcontextprotocol.io/
- Awesome List: https://github.com/wong2/awesome-mcp-servers
- GitHub Search: "mcp-server-" or "model context protocol"

## Next Steps
1. Start the servers you need for your workflow
2. Configure your preferred AI agent (Claude Code, NeMo Gym agent, etc.) to use them
3. Begin enhancing your coding agent with file and git operations
4. Explore other MCP servers for databases, APIs, and more

Happy coding with enhanced MCP-powered agents! 🚀
