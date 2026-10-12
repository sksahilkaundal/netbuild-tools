# BUA GLA/GSA area audit (Common GLA/GSA areas vs their full Revit parameters): prompt template

Scripts:
- Step 1 (inside Revit, read-only): `C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_dump.py`, run through `execute_revit_code`. Dumps every Area of the schedule's area scheme whose `Studio_Area_Department` contains GLA or GSA, from the host model and every open linked model, with all parameter values, to JSON.
- Step 2 (`py -3.14`): `C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_audit.py`. Matches the dump to a dated Option 1 workbook using `projecta_calculations_build.py`'s own rules, so "common" means exactly what the ProjectA Calculations sheet counts. It reports and writes `_bua_common_gla_areas.csv` next to the dump.
- Context: [`BUA_DatedExport_PromptTemplate.md`](BUA_DatedExport_PromptTemplate.md) builds the Option 1 / ProjectA Calculations workbooks this audit checks.

## Prompt (fill in the date folder)

```
Using bua_gla_area_dump.py (C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_dump.py) inside Revit, then
bua_gla_area_audit.py (C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_audit.py):

Option 1 workbook: "C:\SK\Projects\ProjectA\Excel\<YYMMDD>\<YYMMDD>_ProjectB_Overall BUA_Space_Room Split_with All Levels_Option 1.xlsx"

Do NOT launch Revit. If no Revit session has ProjectC-Studio-BIM-SW00-ZZZ-AR-970002 (the host of the schedule
"Excel - Area - Overall With Assets For MEP Team", with 970001 linked) open and active, tell me and stop.

STEP 1 - read-only dump in Revit:
    SCHEDULE_NAME = "Excel - Area - Overall With Assets For MEP Team"
    OUT_JSON = r"C:\SK\Projects\ProjectA\Exports\<YYYY-MM-DD>\_bua_gla_area_dump.json"
    exec(compile(open(r"C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_dump.py").read(), "bua_gla_area_dump.py", "exec"))

STEP 2 - audit:
    py -3.14 C:\SK\OneDrive\Netbuild\scripts\bua_gla_area_audit.py "<OUT_JSON>" "<Option 1 workbook>" [--find shared] [--id <element id> ...]

Report:
- Common GLA/GSA to Tenants per tenant (GLA Office / Hotel Apartment / Hotel / Retail) x Studio_Is GLA
  (Yes / No / blank), with m2, and list every area flagged Studio_Is GLA = No (building, level, name, id, model).
- Whether "<find text>" appears in any parameter of those areas, and where it appears in the export.
- Rare Sub-Function x Area Calc. Type pairs (likely mis-set Calc. Type / name) with ids and levels.
- Any UNMATCHED or loosely matched rows.
- Attach the common-areas CSV.
This is a query: change nothing in Revit, the workbooks or the scripts, and commit nothing, unless I ask.
```

## What it means
- **Common GLA/GSA to Tenants**: an area counts when all three hold:
  - `Studio_Area_Department` contains GLA or GSA. The tag picks the tenant row.
  - Its Function-Sub-function is a service-type space: Services, Storage, Kitchen, Pool, Circulation or F&B Kitchen.
  - Usable Area (A) > 0. That column is the schedule's formula, driven by `Area Calc. Type`.
  A GLA-tagged area whose Calc. Type puts its m² in B / C / D (Lift Lobby (Non-GFA), Circulation, BOH (Non-GFA) ...) stays non-lettable (report section 3).
- **`Studio_Is GLA`** is NOT in the export and NOT used by the ProjectA sheet. The audit only shows where it disagrees with the department tag. The user decides what wins.
- **Area Type** is "Building Common Area" on all tagged areas, including residential units. It is a model default, not a sharing signal.
- **"Shared"** in this model lives in `Studio_Area_Department` = Shared Services and `Studio_Function Code` = Shared. All of those areas have 0 usable area.

## History
- 2026-10-01: 261001 data. 119 common areas, 9,733.91 m², all matched. Flags: Studio_Is GLA Yes 4,171.58 / blank 5,459.46 / No 102.87 (6 areas in 970001: B3 office toilets 02/03/05, B5 office BOH 02/03, B5 retail BOH GF). No "shared" on any of them. The rare pair "Hotel - King Suite" on Hotel-Storage (Tower B 51st, area 2447) was corrected by the user to Store / Store (Over Ground).
