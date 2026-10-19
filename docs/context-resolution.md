# Context Management / Context Resolution

## Scope and compatibility

The current project has no Material execution object or Sub-Flow call graph. A Step has exactly one OperationGroup; its **direct parent Flow** is `step.group.flow_id`. Resolution derives this from the database. Names are display labels, never identities. Reusing a logical operation in different flows currently means distinct Step rows. This change does not introduce a Material execution engine or modify Step bindings automatically.

Recipe Context and Inspection Plan Context are separate tables, APIs and menu pages. Rules map optional conditions to an existing target; they do not copy target parameters into rules. No demonstration rules are seeded or hardcoded.

`InspectionPlan` previously combined a plan identity with a single inline measurement definition. It is retained as the plan container to preserve existing IDs, foreign keys and API fields. `inspection_items` adds multiple measurement definitions per plan, each with its own type, sampling rule, target, USL/LSL, unit and frequency. No duplicate plan entity is introduced. Existing inline fields remain unchanged and represent the legacy single-item definition when `items` is empty. Once explicit items are configured, consumers should use that list; legacy inline fields remain for old clients and are not automatically copied or kept in sync. Detection result uploads are not implemented by this change.

Released/Obsolete card-linked plans and their items are read-only. Card-version cloning copies explicit items to the new Draft. Standalone plans/items and standalone recipes remain editable master data, with no new approval lifecycle.

## Installation and migration

No new dependencies are required. Stop old backend processes, back up the configured database using a database-consistent backup, then from `backend` run:

```bash
python migrate_context_resolution.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Use your activated virtualenv (or `../.venv/bin/python` in the cloud checkout). The script uses the same `DATABASE_URL` as the application and defaults to root `mes.db`. It only creates `inspection_items`, `recipe_contexts`, `inspection_plan_contexts` and their indexes if absent; it never rewrites existing rows or drops old tables. Repeated execution is safe. New application startup also registers these models and creates missing tables via the existing lifespan `create_all`. Existing deployments missing the older card-field migration must apply that migration separately; this migration does not repair unrelated schema differences. SQL and runtime verification here target SQLite, the repository's default database.

For rollback, restore the previous code **and** your backup. Do not delete new tables after users have entered context rules or items. A database already containing incompatible tables with these names needs manual investigation; `checkfirst` is not a schema repair mechanism.

Frontend: from `frontend` run `npm run dev`, or rebuild with `npm run build` and deploy the resulting assets. Old frontend pages/APIs remain available. New context rules start empty, so resolution intentionally returns `unresolved` until an administrator configures a rule.

## API

All routes use `/api`.

| Path | Methods / purpose |
| --- | --- |
| `/recipe-contexts` | GET list, POST create |
| `/recipe-contexts/{id}` | GET detail, PUT full replacement, DELETE |
| `/recipe-contexts/{id}/enabled` | PATCH enabled state |
| `/recipe-contexts/resolve` | POST real database-backed resolution |
| `/inspection-plan-contexts` | GET list, POST create |
| `/inspection-plan-contexts/{id}` | GET detail, PUT full replacement, DELETE |
| `/inspection-plan-contexts/{id}/enabled` | PATCH enabled state |
| `/inspection-plan-contexts/resolve` | POST real database-backed resolution |
| `/inspection-plans/{plan_id}/items` | GET definitions, POST add definition |
| `/inspection-plans/{plan_id}/items/{id}` | PUT definition, DELETE definition |

Rule fields shared by both collections: `name`, nullable `flow_id`, `step_id`, `card_version_id`, integer `priority` (default 0), boolean `is_enabled` (default true), `description`. IDs, revision, created_at and updated_at are server managed. Timestamps follow the existing project's UTC-naive convention.

Recipe rules additionally accept required `recipe_id`, nullable `equipment_id`, `chamber`, `substrate_type`. Inspection rules accept required `inspection_plan_id` and nullable `inspection_type` (a business condition, e.g. after-etch; not an alias for an individual measurement's type).

A null condition means **unrestricted**, never “must be null”. Blank optional textual conditions are normalized to null. Omitted optional fields in PUT clear those fields; PUT is a full replacement, not PATCH. The Smart Table sends explicit nulls for cleared selectors. Target IDs, references, Step/Flow/card consistency, recipe/equipment consistency and configured chamber membership are checked. Chamber rules require an equipment ID. Target objects linked to card versions must reference Released versions; standalone targets are allowed.

GET supports exact filters `flow_id`, `step_id`, `is_enabled` and the collection's target ID; Recipe also supports `equipment_id`. Lists are ordered by ID. The UI provides filtering and client-side pagination; API pagination is not implemented.

PUT requires the current `revision` in the body. PATCH `/enabled` requires `{is_enabled, revision}`. DELETE requires `?revision=N`. Each modification increments revision atomically; stale operations return 409 and must reload the record before retrying. Missing records return 404. Invalid references or incompatible input return 404/422. Database reference conflicts return 409. Context references use RESTRICT, including disabled rules: remove/reassign the rule before deleting a referenced Flow, Step, card version, equipment or target. Rules themselves currently have no downstream FK dependents. There is no authentication layer in the existing sandbox; use within a trusted development boundary.

### Resolution input

Recipe:

```json
{"step_id": 12, "equipment_id": 3, "chamber": "Main"}
```

Inspection:

```json
{"step_id": 12, "inspection_type": "After Etch"}
```

IDs above are placeholders, not seeded data. Step and equipment are mandatory for Recipe; chamber is optional, but if supplied must belong to that equipment. A recipe with a fixed chamber cannot resolve when chamber is omitted. Step and a nonblank inspection condition are mandatory for Inspection. Both accept optional `flow_id` and `card_version_id` assertions: they must equal the actual Step's direct parent and bound version. A caller cannot override the Step binding. Substrate is derived only from the bound card version; no fabricated Material/substrate input is accepted. Unbound Steps are allowed, but card-constrained rules/targets cannot match them. Unknown request fields (including target IDs) are rejected.

### Ranking and target validity

1. Read enabled rules from the appropriate database table on each request.
2. Every non-null rule condition must equal the effective input; unknown input cannot satisfy a specific condition.
3. Reject nonexistent targets and card-linked targets whose version is not Released or differs from the Step binding. Recipe targets with equipment/chamber restrictions must agree with input. Standalone objects have no approval state in the current model.
4. Rank by **number of non-null rule conditions descending**, then **priority descending**. Explicit redundant conditions still count: Flow+Step outranks Step. Priority cannot override a more specific rule.
5. No candidates: `unresolved`, no target. There is no implicit fallback; configure an all-null generic rule explicitly when needed. Target intrinsic restrictions still apply to generic rules.
6. Highest rank points to multiple target IDs: `ambiguous`, no target, all conflict rule IDs returned.
7. Highest rank points to one target: `resolved`. Equivalent same-target rules are coalesced; smallest rule ID is used only as the representative and all tied rules appear in details. Database ordering never decides between different targets.

All three business outcomes use HTTP 200 with `resolution_status`, `target_id`, `target_name`, `matched_context_id`, `matched_context_name`, `match_details`, `message`, `conflicting_context_ids`. Resolved results additionally include `target`, including a plan's explicit items and legacy fields. Validation errors use HTTP 404/422 and concurrency/reference errors HTTP 409.

`match_details.input` records effective context; `matched_rules` records every highest-ranking rule's actual conditions. No target or match ID is claimed on ambiguity. Rules are not cached, so a committed edit/disable is reflected on the next Resolve.

## UI workflow

Open **Context Management → Recipe Context / Inspection Plan Context**. Each page loads its own real rule collection and target objects. Add/edit rules using business-object selectors; blank conditions mean unrestricted. Step options include Flow, Group, sequence and ID so repeated names remain distinguishable. Save errors keep the form open. Toggling/deleting uses optimistic revision checks and reloads on conflicts.

The Inspection page also provides standalone plan creation and multi-item maintenance. Existing card-linked plan identity is maintained through Operation Card APIs; released plan items cannot be edited. Both pages have a real Resolve panel. Select Step; its Flow and bound card version are prefilled from loaded data. You may select a card-version assertion, but the server rejects any version that differs from the actual binding; this does not rebind the Step. Select equipment/chamber or enter the detection condition. Results show status, target, representative rule, effective fields and conflict IDs. Editing a rule clears stale displayed results; press Resolve again to test current database configuration.

## Validation

From `backend`: `python -m pytest -q`. Tests exercise ranking, explicit generic rules, ambiguity, disabled rules, same-target ties, stale modifications, direct-flow validation, duplicate Step names, invalid chambers, target validity, multi-item plans, freezing/cloning, legacy fields and repeated migration.

From `frontend`: `node --test src/cardRows.test.js` and `npm run build`. Browser checks use an isolated SQLite database and test real HTTP APIs rather than mocked resolution. Production authentication, full Material/Sub-Flow execution and detection-result uploads remain outside this feature.
