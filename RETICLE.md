# Verifying FlintTrade with Reticle

Reticle checks a running FlintTrade session in the browser. Use it when a change is something an operator can see or do: a component, a form, a route, a request, or state that reaches the screen. Reading a diff or running a unit test does not replace that check.

Skip Reticle when the change cannot show up in the running app: documentation, comments, tests, build config, CI, dependency bumps with no user-facing effect, and backend or command-line work with no UI. Say in one line that verification was skipped and why.

## Procedure

1. Run `reticle_session { action: "list" }`. If no session is listed, check that `.reticle.json` exists (if not, run `npx @reticlehq/server@latest init`), that a dev server started after `init` is serving the app, and open a page with `npx @reticlehq/server open <url>`. `npx @reticlehq/server doctor` compares the daemon port with the port the page dials.
2. Pick one flow an operator would do first, such as signing in, opening Practice or submitting a sandbox order. When the change touches a specific flow, use that one.
3. Read the page with `reticle_look { action: "page" }`, walk the flow one step at a time with `reticle_act_and_wait`, and check each effect with `reticle_assert`. Finish with `reticle_observe` for console and network errors. Only `reticle_act_and_wait` and `reticle_assert` produce a verdict.
4. Report each step and what it produced, any failure with the `file:line` Reticle gave, and any step that could not be verified. Do not weaken an assertion to make a run pass.

The sections below cover the results a run can return.

## The tools are missing

`init` registers the MCP server, but a client reads its server list at startup. Restart the editor's MCP client so it rereads the server list, then continue. `npx @reticlehq/server status` reports whether the daemon is up and whether the app has connected.

## A result carries `verify_next`

The page was driven without a declared consequence, so nothing so far is proven. Follow the field.

## A result carries `version_skew`

Two Reticle pieces are on different wire contracts. A green result is not evidence until they match. The field names the pair and the fix: run `npx @reticlehq/server stop` and retry when the daemon is stale, or install the matching SDK and restart the dev server when the page is stale. Then repeat the check.

## A result carries `update_available`

A newer Reticle version is on npm. Finish the current check first. `npx @reticlehq/server update` restarts the daemon and drops the session, so run it between tasks.

## `reticle_look { action: "state" }` comes back empty

The generated `reticle-dev` file registered no store. `init` leaves a store commented when it needs an argument only the code can supply (Jotai atoms, an XState actor, a TanStack `queryClient`). Uncomment that line, complete it, and drive one flow until the keys come back. An empty state read is not a successful setup. DOM, network, console, and source pointers still work without it.

## Reporting a Reticle defect

Send `reticle_session { action: "feedback" }` when Reticle itself is wrong, missing, ambiguous, or expensive. One call, then continue the FlintTrade task.

- `bug`: a tool returned the wrong result.
- `gap`: Reticle could not observe the thing.
- `ambiguity`: a verdict could not be acted on.
- `feature_request`: something missing.
- `improvement`: it works and costs too many calls.

If the tools are not reachable yet:

```bash
npx @reticlehq/server feedback --agent --kind bug "what happened"
```

For a failure, include what was called, what was expected, what came back, and the call trail in `trace`. For a request, name the goal, the impact, and the current workaround. Set `model` to the model in use. Do not include application source, secrets, or operator data. A defect in FlintTrade belongs in the task report, not in a Reticle feedback call.

## More

`https://docs.reticle.sh/llms.txt` lists the Reticle documentation. Appending `.md` to a page URL returns that page as text.
