# Issue tracker: GitHub

Issues, tickets and publishable specs live in GitHub Issues for `navaneeshnagarajan/FlintTrade`. Use the `gh` CLI for tracker operations; it infers this repository from the Git remote when run inside the checkout. Outside it, pass `--repo navaneeshnagarajan/FlintTrade`.

## Conventions

- Create: `gh issue create --title "..." --body-file <file>`.
- Read the full issue and comments: `gh issue view <number> --comments`. For structured output including labels, add `--json number,title,body,labels,comments`; use `--jq` to filter when needed.
- List: `gh issue list --state open --json number,title,body,labels,comments`, with appropriate `--label` and `--state` filters.
- Comment: `gh issue comment <number> --body-file <file>`.
- Apply or remove labels: `gh issue edit <number> --add-label "..."` or `gh issue edit <number> --remove-label "..."`.
- Close: `gh issue close <number> --comment "..."`.

Write multi-line issue bodies and comments to a temporary UTF-8 file and pass it with `--body-file`. Put one shell command per line; do not chain commands with `&&`.

## Publishing and fetching tickets

When a skill says "publish to the issue tracker", create a GitHub issue. When it says "fetch the relevant ticket", read the full issue and comments with `gh issue view <number> --comments`.

Working designs and design logs follow the spec-first workflow in `AGENTS.md`. GitHub holds publishable specs and actionable tickets; preserve the working design record. `PLAN.md` remains the curated public roadmap; follow `AGENTS.md` for the detailed working plan, and use `changelog.md` for shipped code only.

## Pull requests as a triage surface

**PRs as a request surface: no.**

GitHub shares issue and PR numbers. Resolve a bare `#<number>` with `gh pr view <number>` and fall back to `gh issue view <number>`. Use `gh pr diff <number>` when reading a PR's attached code.

## Wayfinding operations

The `/wayfinder` map is one issue with child tickets.

- Map: label it `wayfinder:map`; its body holds Notes, Decisions-so-far and Fog.
- Children: link tickets as GitHub sub-issues using `gh api`. If unavailable, list them in the map's task list and put `Part of #<map>` at the top of each child. Use `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling` or `wayfinder:task` as appropriate.
- Blocking: use GitHub's native issue dependencies through `gh api`, identifying blockers by their numeric database ID, not their issue number or `node_id`. If unavailable, put `Blocked by: #<number>, ...` at the top of the child body.
- Frontier: consider the map's open children in map order; choose the first unassigned ticket with no open blockers.
- Claim: `gh issue edit <number> --add-assignee "@me"`.
- Resolve: comment with the answer, close the child, then append a context pointer (gist and link) to the map's Decisions-so-far.
