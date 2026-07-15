# Tool Name Alias Proposal (BUG-005, BUG-015)

## Background

Two sets of tool names exist:

### Set A: Documented in project overview (user-facing)
- `list_devices`
- `execute_command`
- `configure_device`
- `get_device_status`
- `ping_test`

### Set B: Currently registered (namespaced)
- `h3c_list_devices`
- `h3c_run_display`
- `h3c_plan_change` (v0.2, currently hidden)
- `hcl_get_runtime` / `h3c_get_facts`
- `h3c_ping`

## Options

### Option 1: Register aliases as deprecated wrappers
- Add Set A names as deprecated tools that delegate to Set B
- Mark with `_deprecated: true` and `_canonical_tool: "h3c_*"` in response
- Remove in v1.0
- **Pro**: Backward compatible, no breaking changes
- **Con**: Doubles tool count, confusing for agents

### Option 2: Rename tools to match user-facing names
- Rename `h3c_list_devices` → `list_devices`, etc.
- Remove all `h3c_` prefix from read-only tools
- Keep `h3c_` only for vendor-specific advanced tools
- **Pro**: Clean, matches user expectations
- **Con**: BREAKING CHANGE — all existing MCP client configs break

### Option 3: Keep namespaced names, document mapping
- Current approach (BUG-005 fix)
- README provides migration table
- No code changes needed
- **Pro**: No breaking changes, stable API
- **Con**: Users must learn namespaced names

## Recommendation

**Option 3 for v0.1.0-beta.1** (current state).

Once v0.1 tool contracts are frozen and validated with real HCL,
revisit for v0.2 with Option 1 or Option 2 based on user feedback.

### Migration Table (for README)

| User-Facing Name | Canonical Tool | Status |
|---|---|---|
| `list_devices` | `h3c_list_devices` | ✅ Available |
| `execute_command` | `h3c_run_display` | ✅ Available |
| `get_device_status` | `hcl_get_runtime` / `h3c_get_facts` | ✅ Available |
| `ping_test` | `h3c_ping` | ✅ Available |
| `configure_device` | Not yet available | ⏳ v0.2 |

## Decision Needed

From maintainer: Confirm tool naming strategy for v1.0.
