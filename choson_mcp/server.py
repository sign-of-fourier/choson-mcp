"""Chosŏn MCP server (stdio): the public /v1 API as tools for Claude or any MCP client.

Configure with CHOSON_API_KEY (required) and CHOSON_API_URL (default https://quantecarlo.com/api/v1). The full API
reference is the resource choson://docs and the tool api_reference.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

BASE = os.environ.get("CHOSON_API_URL", "https://quantecarlo.com/api/v1").rstrip("/")
DOCS_URL = os.environ.get("CHOSON_DOCS_URL", "https://quantecarlo.com/api.md")
logging.getLogger("httpx").setLevel(logging.WARNING)      # request lines would flood the client's log
MAX_WAIT = 600                                    # longest a single wait_for_fit call blocks, seconds
FIT_CAP_HOURS = 2                                 # every fit is stopped at 2 hours by the platform

mcp = FastMCP("choson", instructions=(
    "Chosŏn runs conjoint studies (CBC, menu-based, MaxDiff, pricing, claims tests, volumetric). Flow: create_project "
    "-> upload_data -> check the report and design (set_design if the inferred design is wrong) -> start_fit -> "
    "quote_fit -> start_fit -> wait_for_fit -> get_result -> simulators. Before start_fit, call quote_fit with the "
    "same settings, tell the user the hardware, the estimated time and the maximum (every fit stops at 2 hours), "
    "and get their go-ahead. Report estimates with their 95% "
    "ranges; read fit warnings before drawing conclusions. For anything not covered by a tool, read api_reference "
    "and use call_api."))


class ApiError(Exception):
    pass


def _client() -> httpx.Client:
    key = os.environ.get("CHOSON_API_KEY", "").strip()
    if not key:
        raise ApiError("CHOSON_API_KEY is not set. Create a key at https://quantecarlo.com/app/#/keys (paid plans) "
                       "and set it in this server's environment.")
    return httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {key}",
                                                "User-Agent": "choson-mcp/0.1"}, timeout=120)


def _req(method: str, path: str, *, json_body: Any = None, files=None, data=None, raw: bool = False):
    with _client() as c:
        r = c.request(method, path if path.startswith("/") else "/" + path, json=json_body, files=files, data=data)
    if r.status_code >= 400:
        try:
            d = r.json().get("detail")
        except ValueError:
            d = r.text
        if isinstance(d, dict):
            d = "; ".join(str(x) for x in [d.get("message")] + list(d.get("problems") or []) + list(d.get("errors") or []) if x)
        elif isinstance(d, list):
            d = "; ".join(e.get("msg", str(e)) for e in d)
        raise ApiError(f"{r.status_code}: {d}")
    if raw:
        return r.content
    return r.json() if r.content else None


# ---------------------------------------------------------------------------------------------------------- reference
@mcp.resource("choson://docs")
def docs() -> str:
    """The Chosŏn API reference (v1)."""
    return httpx.get(DOCS_URL, timeout=30).text


@mcp.tool()
def api_reference() -> str:
    """The full Chosŏn API reference: data formats for every module, fit settings, the results JSON, every
    simulator and search with its fields, errors. Read it before call_api or when a format is unclear."""
    return docs()


@mcp.tool()
def whoami() -> dict:
    """The account's plan and its limits (respondents, products, tasks, queued jobs) and GPU minutes this month."""
    return _req("GET", "/me")


# ----------------------------------------------------------------------------------------------------- projects, data
@mcp.tool()
def list_projects() -> list:
    """All projects on the account (id, name, kind)."""
    return _req("GET", "/projects")


@mcp.tool()
def create_project(name: str, kind: str = "cbc") -> dict:
    """Create a project. kind: cbc, mbc, maxdiff, pricing, concept or volumetric."""
    return _req("POST", "/projects", json_body={"name": name, "kind": kind})


@mcp.tool()
def get_project(project_id: str) -> dict:
    """A project with its datasets and fits."""
    return _req("GET", f"/projects/{project_id}")


@mcp.tool()
def upload_data(project_id: str, responses_path: str, design_path: str | None = None) -> dict:
    """Upload a responses file from the local disk (CSV in the module's long format, or a Sawtooth .CHO for CBC;
    see api_reference for formats). Optional design JSON for CBC. Returns the dataset: its id, the validation report
    (errors must be fixed before fitting; read warnings) and, for CBC, the design (check design_inferred)."""
    p = Path(responses_path).expanduser()
    files = {"responses": (p.name, p.read_bytes())}
    if design_path:
        d = Path(design_path).expanduser()
        files["design"] = (d.name, d.read_bytes(), "application/json")
    return _req("POST", f"/projects/{project_id}/data", files=files)


@mcp.tool()
def get_dataset(dataset_id: str) -> dict:
    """A dataset: validation report, summary, design."""
    return _req("GET", f"/datasets/{dataset_id}")


@mcp.tool()
def set_design(dataset_id: str, design: dict) -> dict:
    """CBC: replace the dataset's design (attributes with name, levels, kind categorical / linear; none; price) and
    re-run the checks. Start from the design get_dataset returns and edit it."""
    return _req("PUT", f"/datasets/{dataset_id}/design", json_body=design)


# --------------------------------------------------------------------------------------------------------------- fits
@mcp.tool()
def quote_fit(dataset_id: str, settings: dict | None = None) -> dict:
    """What a fit with these settings would run on, without queuing it: compute (cpu, modal_cpu, t4, h100),
    estimated_seconds, max_seconds (every fit is stopped at 7,200 s = 2 hours) and any notes. Same settings as
    start_fit. Show the user this before starting a fit."""
    return _req("POST", f"/datasets/{dataset_id}/fits", json_body={**(settings or {}), "dry_run": True})


@mcp.tool()
def start_fit(dataset_id: str, settings: dict | None = None) -> dict:
    """Queue a fit. settings (all optional, see api_reference): taste (none / diagonal / full), error_shares (list of
    attributes), holdout (last / none), hb_baseline, constraints, covariates, classes, compute (auto / cpu / t4 /
    h100). Returns the fit with compute (the hardware chosen) and progress.estimated_seconds. Every fit stops at 2
    hours. Call quote_fit first, show the user the hardware, the estimate and the 2-hour maximum, and get their
    go-ahead."""
    return _req("POST", f"/datasets/{dataset_id}/fits", json_body={**(settings or {}), "dry_run": False})


@mcp.tool()
def fit_status(fit_id: str) -> dict:
    """A fit's status (queued, running, done, failed, cancelled), progress stage, error and timestamps."""
    return _req("GET", f"/fits/{fit_id}")


@mcp.tool()
def wait_for_fit(fit_id: str, max_seconds: int = 300) -> dict:
    """Poll a fit until it is done, failed or cancelled, or max_seconds pass (at most 600; call again to keep
    waiting). Returns the last status."""
    end = time.time() + min(max(5, max_seconds), MAX_WAIT)
    while True:
        f = _req("GET", f"/fits/{fit_id}")
        if f["status"] in ("done", "failed", "cancelled") or time.time() >= end:
            return f
        time.sleep(5)


@mcp.tool()
def cancel_fit(fit_id: str) -> dict:
    """Cancel a queued fit at once or a running one within seconds."""
    return _req("POST", f"/fits/{fit_id}/cancel")


@mcp.tool()
def get_result(fit_id: str, section: str | None = None) -> Any:
    """The results JSON of a finished fit. Large; pass section to get one part: derived (part-worths, importances,
    WTP), params (mean tastes, taste spread, error shares), fit (log-likelihood, holdout hit rate, warnings),
    baselines (comparison models), meta (settings, design). Every estimate is {est, se, lo, hi} with a 95% range."""
    r = _req("GET", f"/fits/{fit_id}/result")
    if section:
        if section not in r:
            raise ApiError(f"no section {section!r}; sections: {', '.join(r)}")
        return r[section]
    return r


@mcp.tool()
def download(fit_id: str, what: str, save_to: str) -> str:
    """Save a fit's file to the local disk. what: respondents.csv (per-respondent estimates), workbook.xlsx (the
    study workbook) or excel-simulator.xlsx (CBC, needs the Chosŏn Excel add-in)."""
    if what not in ("respondents.csv", "workbook.xlsx", "excel-simulator.xlsx"):
        raise ApiError("what must be respondents.csv, workbook.xlsx or excel-simulator.xlsx")
    out = Path(save_to).expanduser()
    if out.is_dir():
        out = out / f"{fit_id}-{what}"
    out.write_bytes(_req("GET", f"/fits/{fit_id}/{what}", raw=True))
    return str(out)


# --------------------------------------------------------------------------------------------------- CBC simulators
@mcp.tool()
def simulate_shares(fit_id: str, products: list[dict], group: str | None = None) -> dict:
    """Share of preference for a shelf, with 95% ranges. products: up to 60, each {attribute: level} with levels
    exactly as in the design (price any number in the tested range). group: a covariate group, if the fit has them."""
    return _req("POST", f"/fits/{fit_id}/simulate", json_body={"products": products, "group": group})


@mcp.tool()
def simulate_removal(fit_id: str, products: list[dict], remove: int, group: str | None = None) -> dict:
    """Remove one product (0-based index into products): the shares after, and where its buyers go (diversion to
    each remaining product and to none), with 95% ranges. The substitution question."""
    return _req("POST", f"/fits/{fit_id}/simulate/remove", json_body={"products": products, "remove": remove, "group": group})


@mcp.tool()
def price_sweep(fit_id: str, products: list[dict], product: int, prices: list[float] | None = None) -> dict:
    """Shares as one product's (0-based index) price moves across the tested range (or the given prices)."""
    return _req("POST", f"/fits/{fit_id}/simulate/price-sweep", json_body={"products": products, "product": product, "prices": prices})


@mcp.tool()
def elasticities(fit_id: str, products: list[dict]) -> dict:
    """Own- and cross-price elasticities for a shelf, with 95% ranges."""
    return _req("POST", f"/fits/{fit_id}/simulate/elasticities", json_body={"products": products})


@mcp.tool()
def forecast(fit_id: str, request: dict) -> dict:
    """Units, revenue and profit with 95% ranges, the change against a base shelf and the chance of clearing a
    hurdle. request: products, occasions, prices, unit_costs, own (indexes), optional base and hurdle (see
    api_reference)."""
    return _req("POST", f"/fits/{fit_id}/simulate/forecast", json_body=request)


# ------------------------------------------------------------------------------------------------------- everything
@mcp.tool()
def call_api(method: str, path: str, body: dict | None = None) -> Any:
    """Any other /v1 route (see api_reference): searches (range, recommend, test-next; queued, poll with GET on the
    same path), optimize, segments, MBC / MaxDiff / volumetric / concept tools, survey design. path is relative to
    /v1, e.g. "/fits/abc123/range". JSON only; use upload_data and download for files."""
    method = method.upper()
    if method not in ("GET", "POST", "PUT", "DELETE"):
        raise ApiError("method must be GET, POST, PUT or DELETE")
    return _req(method, path, json_body=body if method != "GET" else None)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
