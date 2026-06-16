---
name: google-sheets-advanced
description: "Pivot tables, charts and any Sheets API batchUpdate op in Google Sheets via the Apps Script helper (covers what the Google MCP has no native tool for)."
version: 1.0.0
author: AiManager
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Google, Sheets, Pivot, Charts, AppsScript, MCP]
prerequisites:
  mcp_servers: [google_workspace]
---

# Google Sheets — advanced ops (pivot, charts, batchUpdate)

Use this when the user wants something in a Google Sheet that the
`google_workspace` MCP has **no native tool** for: a **pivot table**, a
**chart/graph**, structural formatting (merges, frozen rows, banding),
data validation, or any other Sheets API `batchUpdate` request.

The MCP's Sheets tools only read/write values and do simple range
formatting. There is **no** `create_pivot`, `add_chart` or generic
`batchUpdate` tool. The bridge is a pre-installed **Apps Script helper**
that forwards a raw Sheets API `requests[]` array to
`Sheets.Spreadsheets.batchUpdate`. You drive it through the MCP's
`run_script_function` tool — no new script, no manual steps.

## The helper

- **Script ID:** `187nav-q_nVb4btVcaZVEAO2q4cBQpF5T9p0Yf-yf6vmm-SfPm-GJRv40`
- **Function:** `batchUpdate(spreadsheetId, requestsJson)` — `requestsJson`
  is a JSON **string** of a Sheets API `requests` array; returns the API
  reply JSON.
- Already bound to the OAuth GCP project, Apps Script + Sheets APIs are
  enabled. Just call it.

## Call pattern

```
run_script_function(
  script_id="187nav-q_nVb4btVcaZVEAO2q4cBQpF5T9p0Yf-yf6vmm-SfPm-GJRv40",
  function_name="batchUpdate",
  parameters=[<spreadsheetId>, <requests-as-JSON-string>],
  dev_mode=true
)
```

`dev_mode=true` runs the latest helper code without a deployment.

### First get numeric sheet IDs (gid)

`source`/`start` in requests use the **numeric** `sheetId` (gid), not the
sheet name. Fetch them once with `get_spreadsheet_info(spreadsheet_id=...)`
and reuse. Create extra sheets (e.g. a `Pivot` tab) with `create_sheet`
if you want the result off the data sheet.

## Example — pivot table

Data in `Sheet1` (gid 0), columns A=Region, B=Product, C=Amount, rows
1..N. Place a pivot (sum of Amount by Region) at column F of the same
sheet. `requests` array:

```json
[{"updateCells":{
  "rows":[{"values":[{"pivotTable":{
    "source":{"sheetId":0,"startRowIndex":0,"startColumnIndex":0,"endRowIndex":N,"endColumnIndex":3},
    "rows":[{"sourceColumnOffset":0,"showTotals":true,"sortOrder":"ASCENDING"}],
    "values":[{"summarizeFunction":"SUM","sourceColumnOffset":2}]
  }}]}],
  "start":{"sheetId":0,"rowIndex":0,"columnIndex":5},
  "fields":"pivotTable"
}}]
```

JSON-stringify that array and pass it as the second parameter.

## Example — column chart

```json
[{"addChart":{"chart":{"spec":{
  "title":"Amount by Region",
  "basicChart":{
    "chartType":"COLUMN","legendPosition":"BOTTOM_LEGEND",
    "domains":[{"domain":{"sourceRange":{"sources":[{"sheetId":0,"startRowIndex":0,"endRowIndex":N,"startColumnIndex":0,"endColumnIndex":1}]}}}],
    "series":[{"series":{"sourceRange":{"sources":[{"sheetId":0,"startRowIndex":0,"endRowIndex":N,"startColumnIndex":2,"endColumnIndex":3}]}}}]
  }},
  "position":{"newSheet":true}
}}}]
```

## Other ops

Anything Sheets `batchUpdate` supports goes through the same helper:
`mergeCells`, `updateSheetProperties` (frozen rows/cols), `addBanding`,
`setDataValidation`, `repeatCell` (formatting), `deleteDimension`, etc.
Build the `requests` array per the Sheets API and pass it through.

## Flow summary

1. Have the `spreadsheetId` (from `create_spreadsheet` / the user's URL).
2. `get_spreadsheet_info` → note the numeric `sheetId`(s).
3. Build the Sheets API `requests[]` for the op (pivot / chart / format).
4. `run_script_function(helper, "batchUpdate", [spreadsheetId, json], dev_mode=true)`.
5. Check the returned reply JSON; report the sheet URL to the user.

Do NOT tell the user to run a script themselves — you do it via the
helper. Only fall back to instructions if the helper call errors with an
auth/permission problem you cannot resolve.
