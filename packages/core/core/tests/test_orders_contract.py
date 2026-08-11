"""Contract test — `packages/apps/terminal/src/services/api.ts` ↔ Flask order routes.

This file does NOT test runtime behaviour. It is a static parity check that
catches the exact kind of bug the 2026-05-19 Codex stop-gate review surfaced:

- `dcebc35` flipped the backend ``orders_bp`` prefix from ``/v1/orders`` to
  ``/api/v1/orders`` to match the frontend.
- `3f80518` aligned half the frontend leaf names (``cancelorder`` → ``cancel``,
  etc.) — but the safety-proxy was still wide open for accidental drift.
- `f754cff` added ``/options`` + ``/options-multi`` to close a mode-gate
  bypass that was discovered when `optionsOrder` had been temporarily
  routed through OpenAlgo direct.
- `9fe4dd3` retro-fitted regression coverage for the new routes.

Each of those incidents stemmed from the same root cause: the frontend's
literal ``postOrder("leaf", body)`` / ``postOrderMutation("leaf", body, authority)``
strings and the backend's ``@orders_bp.route("/leaf")`` declarations are two
halves of an undeclared contract. If either side silently drifts, the bug only
shows up in production.

This test asserts that the SET of order-leaf names declared by the frontend
matches the SET of order-leaf names registered by the backend, for both:

- the core safety-proxy blueprint (``orders_bp``, place / cancel / etc.)
- the engine advanced-order blueprint (``order_bp``, basket / split / etc.)

If a frontend dev adds a new literal call through either order helper without
a matching backend handler, this test fails. Symmetrically, if a backend route
is added without a frontend caller, the test surfaces the orphan so the dev
decides whether to wire it up or remove it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers — locate the frontend service file and parse literal order-helper leaves
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_API_TS = _REPO_ROOT / "packages" / "apps" / "terminal" / "src" / "services" / "api.ts"

_ORDER_HELPERS = frozenset({"postOrder", "postOrderMutation"})
_EXPECTED_FRONTEND_ORDER_LEAVES = {
    "basket",
    "cancel",
    "cancel-all",
    "close-position",
    "modify",
    "open-position",
    "options",
    "options-multi",
    "place",
    "place-smart",
    "split",
}
_LOWER_KEBAB_RE = re.compile(r"[a-z][a-z0-9-]*\Z")
_REGEX_PREFIXES = frozenset({"(", "[", "{", ",", ";", ":", "=", "=>", "!", "?", "return", "throw"})
_TWO_CHARACTER_TOKENS = frozenset({"?.", "=>", "&&", "||", "??", "==", "!=", "<=", ">="})


@dataclass(frozen=True, slots=True)
class _TypeScriptToken:
    """A deliberately small token used by the order-contract scanner."""

    kind: str
    value: str
    brace_depth: int


def _skip_delimited(
    source: str,
    start: int,
    delimiter: str,
    *,
    stop_at_newline: bool = False,
    character_classes: bool = False,
) -> int | None:
    """Skip one opaque string, template, or regex body."""
    index = start + 1
    in_character_class = False
    while index < len(source):
        if stop_at_newline and source[index] in "\r\n":
            return None
        if source[index] == "\\":
            index += 2
            continue
        if character_classes and source[index] == "[":
            in_character_class = True
        elif character_classes and source[index] == "]":
            in_character_class = False
        elif source[index] == delimiter and not in_character_class:
            return index + 1
        index += 1
    return None if stop_at_newline else len(source)


def _skip_template(source: str, start: int) -> int:
    """Skip a template plus nested interpolation and template bodies."""
    index = start + 1
    interpolation_depth = 0
    while index < len(source):
        if source[index] == "\\":
            index += 2
        elif not interpolation_depth and source[index] == "`":
            return index + 1
        elif source.startswith("${", index):
            interpolation_depth += 1
            index += 2
        elif interpolation_depth and source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline == -1 else newline + 1
        elif interpolation_depth and source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            index = len(source) if closing == -1 else closing + 2
        elif interpolation_depth and source[index] in {'"', "'"}:
            index = _skip_delimited(source, index, source[index]) or len(source)
        elif interpolation_depth and source[index] == "`":
            index = _skip_template(source, index)
        elif interpolation_depth and source[index] == "{":
            interpolation_depth += 1
            index += 1
        elif interpolation_depth and source[index] == "}":
            interpolation_depth -= 1
            index += 1
        else:
            index += 1
    return len(source)


def _typescript_tokens(source: str) -> list[_TypeScriptToken]:
    """Lex only the TypeScript forms needed for static helper-call discovery."""
    tokens: list[_TypeScriptToken] = []
    index = 0
    brace_depth = 0
    while index < len(source):
        character = source[index]
        if character.isspace():
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            index = len(source) if newline == -1 else newline + 1
            continue
        if source.startswith("/*", index):
            closing = source.find("*/", index + 2)
            index = len(source) if closing == -1 else closing + 2
            continue
        if character in {'"', "'"}:
            end = _skip_delimited(source, index, character) or len(source)
            raw = source[index:end]
            closed = len(raw) >= 2 and raw[-1] == character
            interior = raw[1:-1] if closed else raw[1:]
            kind = "double_string" if character == '"' and closed and "\\" not in interior else "string"
            tokens.append(_TypeScriptToken(kind, interior, brace_depth))
            index = end
            continue
        if character == "`":
            index = _skip_template(source, index)
            tokens.append(_TypeScriptToken("opaque", "template", brace_depth))
            continue
        if character == "/" and (not tokens or tokens[-1].value in _REGEX_PREFIXES):
            end = _skip_delimited(source, index, "/", stop_at_newline=True, character_classes=True)
            if end is not None:
                tokens.append(_TypeScriptToken("opaque", "regex", brace_depth))
                index = end
                continue
        if character.isalpha() or character in "_$":
            end = index + 1
            while end < len(source) and (source[end].isalnum() or source[end] in "_$"):
                end += 1
            tokens.append(_TypeScriptToken("identifier", source[index:end], brace_depth))
            index = end
            continue
        pair = source[index : index + 2]
        if pair in _TWO_CHARACTER_TOKENS:
            tokens.append(_TypeScriptToken("punctuation", pair, brace_depth))
            index += 2
            continue
        if character == "}":
            brace_depth = max(0, brace_depth - 1)
        tokens.append(_TypeScriptToken("punctuation", character, brace_depth))
        if character == "{":
            brace_depth += 1
        index += 1
    return tokens


def _after_type_arguments(tokens: list[_TypeScriptToken], start: int) -> int | None:
    """Return the token after one balanced optional TypeScript generic."""
    if start >= len(tokens) or tokens[start].value != "<":
        return start
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index].value == "<":
            depth += 1
        elif tokens[index].value == ">":
            depth -= 1
            if depth == 0:
                return index + 1
    return None


def _export_arrow_parameters(tokens: list[_TypeScriptToken], call_index: int) -> set[str] | None:
    """Return parameters for the module ``export const`` arrow owning a call."""
    arrow_index: int | None = None
    for index in range(call_index - 1, -1, -1):
        if tokens[index].brace_depth:
            continue
        if tokens[index].value == ";":
            return None
        if tokens[index].value == "=>":
            arrow_index = index
            break
    if arrow_index is None or arrow_index == 0 or tokens[arrow_index - 1].value != ")":
        return None

    depth = 0
    open_paren: int | None = None
    for index in range(arrow_index - 1, -1, -1):
        if tokens[index].value == ")":
            depth += 1
        elif tokens[index].value == "(":
            depth -= 1
            if depth == 0:
                open_paren = index
                break
    if open_paren is None or open_paren < 4:
        return None
    prefix = tokens[open_paren - 4 : open_paren]
    if (
        prefix[0].value != "export"
        or prefix[1].value != "const"
        or prefix[2].kind != "identifier"
        or prefix[3].value != "="
    ):
        return None
    return {
        token.value
        for token in tokens[open_paren + 1 : arrow_index - 1]
        if token.kind == "identifier" and token.value in _ORDER_HELPERS
    }


def _extract_order_helper_leaves(source: str) -> set[str]:
    """Extract literal leaves from module export-arrow helper calls.

    ``api.ts`` owns the canonical helper declarations inside function bodies,
    while every real literal call is an expression-bodied module-scope
    ``export const`` initialiser. Requiring that shape makes nested/local
    shadowing fail closed without pretending to parse all TypeScript scopes.
    """
    tokens = _typescript_tokens(source)
    leaves: set[str] = set()
    for index, token in enumerate(tokens):
        if token.kind != "identifier" or token.value not in _ORDER_HELPERS or token.brace_depth != 0:
            continue
        if index and tokens[index - 1].value in {".", "?."}:
            continue
        if index + 1 < len(tokens) and tokens[index + 1].value in {".", "?."}:
            continue
        arrow_parameters = _export_arrow_parameters(tokens, index)
        if arrow_parameters is None or token.value in arrow_parameters:
            continue
        cursor = _after_type_arguments(tokens, index + 1)
        if cursor is None or cursor >= len(tokens) or tokens[cursor].value != "(":
            continue
        first_argument = cursor + 1
        if first_argument >= len(tokens) or tokens[first_argument].kind != "double_string":
            continue
        leaf = tokens[first_argument].value
        after_argument = first_argument + 1
        if (
            not _LOWER_KEBAB_RE.fullmatch(leaf)
            or after_argument >= len(tokens)
            or tokens[after_argument].value not in {",", ")"}
        ):
            continue
        leaves.add(leaf)
    return leaves


def _frontend_order_leaves() -> set[str]:
    """Return literal ``postOrder*`` helper leaf names from ``api.ts``.

    Reads the source file as text rather than executing TypeScript so the
    test can run without a Node toolchain. The lexer is intentionally narrow:
    only module-scope bare helpers with literal lower-kebab leaves count.
    """
    if not _API_TS.exists():
        pytest.skip(f"Frontend service file not found at {_API_TS}")
    source = _API_TS.read_text(encoding="utf-8")
    return _extract_order_helper_leaves(source)


def _backend_order_route_leaves() -> set[str]:
    """Return the set of leaf names registered under ``/api/v1/orders/*``.

    Boots the Flask app via ``create_flask_app()`` and walks ``url_map`` so
    the result reflects whichever blueprints are currently wired in
    ``app.py`` — exactly what a real request would hit.
    """
    from flinttrade_core.app import create_flask_app  # noqa: PLC0415

    app = create_flask_app()
    leaves: set[str] = set()
    for rule in app.url_map.iter_rules():
        path = str(rule.rule)
        if path.startswith("/api/v1/orders/"):
            leaf = path[len("/api/v1/orders/") :]
            # Skip routes with URL parameters (e.g. /bracket/<id>) — those
            # are not the kind of static leaf the frontend addresses via
            # a literal order-helper call.
            if "<" in leaf or not leaf:
                continue
            leaves.add(leaf)
    return leaves


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestOrderHelperExtraction:
    """The static scanner recognises only executable canonical helper calls."""

    @pytest.mark.parametrize(
        "source",
        [
            '// postOrder("line-comment", {});',
            '/* postOrderMutation("block-comment", {}, authority); */',
            "const text = 'postOrder(\"single-prose\", {})';",
            'const text = "postOrderMutation(\\"double-prose\\", {}, authority)";',
            'const text = `postOrder("template-prose", {})`;',
            'const text = `outer ${`postOrder("nested-template", {})`} tail`;',
            'client.postOrder("member-qualified", {});',
            'client?.postOrderMutation("optional-qualified", {}, authority);',
            'postOrder?.("optional-call", {});',
            """
                function wrapper() {
                    const postOrder = fakePostOrder;
                    return postOrder("shadow-variable", {});
                }
            """,
            """
                function wrapper() {
                    function postOrderMutation(endpoint: string, body: object, authority: unknown) {}
                    return postOrderMutation("shadow-function", {}, authority);
                }
            """,
            """
                function wrapper(postOrder: OrderHelper) {
                    return postOrder("shadow-parameter", {});
                }
            """,
            """
                const wrapper = (postOrderMutation: OrderHelper) => {
                    return postOrderMutation("shadow-arrow-parameter", {}, authority);
                };
            """,
            """
                const wrapper = (postOrderMutation: OrderHelper) =>
                    postOrderMutation("shadow-arrow-expression", {}, authority);
            """,
            """
                export const wrapper = (postOrderMutation: OrderHelper) =>
                    postOrderMutation("shadow-exported-arrow-parameter", {}, authority);
            """,
            'const postOrderMutation = fake; postOrderMutation("shadow-top-level", {}, authority);',
            "postOrder(endpoint, {});",
            "postOrder('single-quoted', {});",
            "postOrder(`template-argument`, {});",
            'postOrder("escaped\\x2dleaf", {});',
            'postOrder("concatenated-" + leaf, {});',
            'postOrder("invalid_leaf", {});',
        ],
        ids=[
            "line-comment",
            "block-comment",
            "single-quoted-prose",
            "double-quoted-prose",
            "template-prose",
            "nested-template-prose",
            "member-qualified",
            "optional-member-qualified",
            "optional-call",
            "shadowed-variable",
            "shadowed-function",
            "shadowed-function-parameter",
            "shadowed-arrow-parameter",
            "shadowed-expression-arrow-parameter",
            "shadowed-exported-arrow-parameter",
            "shadowed-top-level-variable",
            "variable-first-argument",
            "single-quoted-argument",
            "template-argument",
            "escaped-argument",
            "concatenated-argument",
            "non-kebab-argument",
        ],
    )
    def test_rejects_noncanonical_or_nonliteral_calls(
        self,
        source: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Non-calls and shadowed helpers cannot satisfy route parity."""
        api_ts = tmp_path / "api.ts"
        api_ts.write_text(source, encoding="utf-8")
        monkeypatch.setitem(globals(), "_API_TS", api_ts)

        assert _frontend_order_leaves() == set()

    @pytest.mark.parametrize(
        ("source", "expected"),
        [
            ('export const placeOrder = (body: object) => postOrder("place", body);', {"place"}),
            (
                """
                    export const placeSmartOrder = (body: object) =>
                        postOrder<{ orderId: string; meta: { ok: boolean } }>("place-smart", body);
                """,
                {"place-smart"},
            ),
            (
                """
                    export const modifyOrder = (
                        params: object,
                        authority: OrderAuthorityPin,
                    ) =>
                        postOrderMutation<
                            { orderId: string }
                        >(
                            "modify",
                            params,
                            authority,
                        );
                """,
                {"modify"},
            ),
            (
                'export const optionsMultiOrder = (body: object) => postOrder("options-multi", body);',
                {"options-multi"},
            ),
        ],
        ids=["bare", "object-generic", "multiline-mutation", "lower-kebab"],
    )
    def test_accepts_literal_bare_canonical_calls(
        self,
        source: str,
        expected: set[str],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Real bare helpers retain generic, multiline, and kebab support."""
        api_ts = tmp_path / "api.ts"
        api_ts.write_text(source, encoding="utf-8")
        monkeypatch.setitem(globals(), "_API_TS", api_ts)

        assert _frontend_order_leaves() == expected


class TestOrderContract:
    """Bidirectional parity between frontend order helpers and backend routes."""

    def test_every_frontend_call_has_a_backend_route(self):
        """A literal order-helper call without its backend route would 404."""
        frontend = _frontend_order_leaves()
        backend = _backend_order_route_leaves()
        missing = frontend - backend
        assert not missing, (
            # Plain string (not f-string) — the {leaf} placeholder is filled in by
            # the .replace() chained below. Previously this was an f-string which
            # caused F821 (undefined `leaf`) under ruff because Python evaluates
            # f-strings eagerly even inside the assert-message expression.
            'Frontend calls an order helper for "{leaf}" with no '
            f"matching backend route under /api/v1/orders/: {sorted(missing)}.\n"
            "Either add the backend handler (mirror an existing route in "
            "packages/core/core/src/order_routes.py or packages/services/engine/src/order_routes.py) "
            "or rename the frontend call to a leaf that exists."
        ).replace("{leaf}", next(iter(missing), ""))

    def test_every_backend_route_has_a_frontend_caller(self):
        """A `/api/v1/orders/foo` handler with no frontend caller is either
        dead or undocumented — flag it. To intentionally keep a backend-only
        endpoint, add it to `_BACKEND_ONLY_LEAVES` below with a justification."""
        frontend = _frontend_order_leaves()
        backend = _backend_order_route_leaves()
        unused = backend - frontend - _BACKEND_ONLY_LEAVES
        assert not unused, (
            f"Backend registers /api/v1/orders/{{leaf}} for leaves with no "
            f"frontend caller: {sorted(unused)}.\n"
            "Either wire the frontend through an order helper, remove "
            "the dead routes, or add the leaf to _BACKEND_ONLY_LEAVES in this "
            "test with a justification comment."
        )

    def test_frontend_extraction_finds_known_calls(self):
        """Sanity check on the lexer — at minimum, the canonical
        `place`, `cancel`, `modify`, and `options` calls must be detected. If
        this breaks, the lexer needs adjusting before the other two tests
        become meaningful."""
        frontend = _frontend_order_leaves()
        for required in ("place", "cancel", "modify", "options"):
            assert required in frontend, (
                f'Lexer failed to find an order-helper call for "{required}" in '
                f"{_API_TS} — adjust the bounded lexer before trusting "
                "the contract assertions."
            )
        assert frontend == _EXPECTED_FRONTEND_ORDER_LEAVES


# ---------------------------------------------------------------------------
# Allowlist — backend routes we intentionally keep without a frontend caller
# ---------------------------------------------------------------------------

# Order endpoints that exist on the backend for internal / direct-API use
# (curl, webhook relays, automation scripts, paper-trading harness tests) but are
# not called from the React terminal. If a leaf is here, the absence of a
# frontend caller is by design.
_BACKEND_ONLY_LEAVES: set[str] = {
    # `options-strategy` — engine helper for named multi-leg strategies
    # (iron_condor, etc.). The terminal builds its own multi-leg payloads
    # via `optionsMultiOrder` (which calls `/options-multi`) and does not
    # consume the named-strategy endpoint directly today.
    "options-strategy",
    # `bracket` and `brackets` — bracket order endpoints (engine
    # `bracket_routes.py`). Frontend clients exist
    # (`ftApi.trading.ts::placeBracketOrder` / `getActiveBrackets` /
    # `cancelBracketOrder`) but are NOT YET consumed by any terminal
    # component — there is no bracket-order entry/management UI today, so
    # these endpoints currently have no frontend caller. Kept here as a
    # known, intentional gap (the bracket UI is a planned follow-up); the
    # backend + its gated path are fully tested in `test_bracket_routes.py`.
    "bracket",
    "brackets",
    # `smart-route` — liquidity-aware order slicing. This is NOT backend-only:
    # the terminal calls it via `ftApi.trading.ts::startSmartRoute` /
    # `getSmartRouteJob` / `listSmartRouteJobs` (consumed by the SmartOrder
    # widget). It lives here only because this scanner reads api.ts's
    # postOrder(...) family, not the ftApi helper modules. The end-to-end
    # contract is covered by `test_smart_order_routes.py` + the widget test.
    "smart-route",
    # `forever`, `super`, `triggers`, `multi` — the extended gated broker
    # verbs (Dhan forever/GTT + super orders + conditional triggers, Upstox
    # multi-order) shipped backend-first in the §8.1 execute_gated wave. The
    # terminal will consume them via ftApi helpers (not postOrder), so the
    # api.ts scanner will never see them; covered end-to-end by
    # `test_gated_verb_routes.py`.
    "forever",
    "super",
    "triggers",
    "multi",
    # Legacy OpenAlgo-style GTT leaves. The terminal compatibility exports
    # (`placeGtt` / `modifyGtt` / `cancelGtt` / `getGttOrderbook`) now call the
    # canonical gated `/orders/forever` client instead of `postOrder("gtt-*")`.
    # Keep these backend leaves documented as legacy/fail-closed compatibility
    # routes rather than reintroducing a second frontend write path.
    "gtt-place",
    "gtt-modify",
    "gtt-cancel",
}
