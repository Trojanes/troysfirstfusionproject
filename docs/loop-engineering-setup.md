# Loop engineering setup — CabinetNC

Configured for Cursor on this machine (2026-07-09).

## Installed

| Pack | Location | Status |
|------|----------|--------|
| **gstack** | `~/.cursor/skills/gstack` + `gstack-*` junctions | OK (bun + browse.exe built) |
| **ECC** | `troysfirstfusionproject-main/.cursor/` (skills, hooks, rules, mcp) | OK (`ecc-install-state.json`) |
| **superpowers** | Cursor plugin marketplace | **You must install** (see below) |
| **Cursor `/loop`** | built-in skill | Already available |

## Routing rule

Always-on: `.cursor/rules/loop-engineering-stack.mdc`

Default order matches your diagram:

1. Small / clear work → **superpowers**
2. Fuzzy requirements → **gstack** then superpowers
3. Long batch / harness → **ECC** + `/loop`
4. Pre-ship → **gstack** review/QA → **superpowers** verify

## Your one remaining install

In Cursor Agent chat:

```text
/add-plugin superpowers
```

Or: Plugin marketplace → search **superpowers** → Install.

## Optional cleanup

ECC pulled many language rule packs (angular, cpp, …) into `.cursor/rules/`.  
CabinetNC mainly needs: `common-*`, `python-*`, `typescript-*`, plus existing Connect/ponytail/loop rules.  
You can delete unused `*-coding-style.mdc` packs later if context feels noisy.

## Upgrade / reinstall

```powershell
# gstack
$env:Path = "$env:USERPROFILE\.bun\bin;C:\Program Files\Git\bin;$env:Path"
cd $env:USERPROFILE\.cursor\skills\gstack
git pull
bash ./setup --host cursor -q --no-plan-tune-hooks
# re-junction skills if needed (setup writes under gstack/.cursor/skills/)

# ECC (from project root)
powershell -File $env:USERPROFILE\.cursor\ecc-src\install.ps1 --target cursor python typescript
```
