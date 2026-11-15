# choson-mcp

An MCP server for the Chosŏn conjoint API: upload survey data, fit, read results and run the simulators from Claude
(Claude Code, Claude Desktop) or any MCP client. It runs on your machine and calls `https://quantecarlo.com/api/v1`
with your API key. Paid Chosŏn plans.

## Set up

1. Create an API key: sign in at https://quantecarlo.com/app/, click API, Create key.
2. Add the server.

Claude Code:

```bash
claude mcp add choson -e CHOSON_API_KEY=chs_... -- uvx choson-mcp
```

Claude Desktop (`claude_desktop_config.json`):

```json
{"mcpServers": {"choson": {"command": "uvx", "args": ["choson-mcp"], "env": {"CHOSON_API_KEY": "chs_..."}}}}
```

Until the package is on PyPI, install from GitHub instead: replace `uvx choson-mcp` with
`uvx --from git+https://github.com/sign-of-fourier/choson-mcp choson-mcp` (in the Desktop config, args
`["--from", "git+https://github.com/sign-of-fourier/choson-mcp", "choson-mcp"]`).

The API itself is documented at https://quantecarlo.com/api.md.

## Tools

whoami, list_projects, create_project, get_project, upload_data (a local file), get_dataset, set_design,
quote_fit (hardware, estimate and the 2-hour maximum, nothing queued), start_fit, fit_status, wait_for_fit,
cancel_fit, get_result (whole or one section), download (per-respondent CSV, workbook, Excel simulator),
simulate_shares, simulate_removal (diversion), price_sweep, elasticities, forecast, api_reference (the full API
reference) and call_api (any other /v1 route: range, recommend, test-next, optimize, segments, the menu, MaxDiff,
volumetric and claims tools, survey design).

The server asks the assistant to show you the hardware, estimate and maximum from quote_fit and get your go-ahead
before starting a fit. Every fit is stopped at 2 hours by the platform.

## Environment

| variable | default |
|---|---|
| `CHOSON_API_KEY` | required |
| `CHOSON_API_URL` | `https://quantecarlo.com/api/v1` |
