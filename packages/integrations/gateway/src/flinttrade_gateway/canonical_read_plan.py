"""Finite capture orchestration owned by the existing broker read owner.

This module holds no accounts, grants, books or workers. The owner still admits,
executes, revalidates and drains every operation; the lifecycle ledger persists
its returned capture in the existing integrity-checked generation manifest.
"""
from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from contextvars import ContextVar
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from flinttrade_core.broker_read_port import (
    BatchQuoteRequest,
    BrokerObservationSnapshot,
    BrokerOrderFamily,
    BrokerReadErrorCode,
    BrokerReadFailure,
    BrokerReadSuccess,
    CapturedReadSurface,
    LedgerRequest,
    LotSizeRequest,
    MarginRequest,
    ObservationCoverage,
    OrderStateRequest,
    TradeHistoryRequest,
)
from flinttrade_core.native_autonomy_contracts_v2 import ReadPlanV2


class _Budget:
    """One capture's finite slots, shared by its actual retained workers."""

    def __init__(self, reads: int, pages: int, deadline: float) -> None:
        self.max_reads, self.max_pages, self.deadline = reads, pages, deadline
        self.reads = self.pages = 0
        self.issues: set[str] = set()
        self.lock = threading.Lock()

    def take(self, *, page: bool = False) -> bool:
        """Reserve one operation slot without recycling failed/late work."""
        with self.lock:
            reason = (
                "read_deadline_exceeded" if time.monotonic() >= self.deadline else
                "read_budget_exceeded" if self.reads >= self.max_reads else
                "page_budget_exceeded" if page and self.pages >= self.max_pages else None
            )
            if reason is not None:
                self.issues.add(reason)
                return False
            self.reads += 1
            self.pages += int(page)
            return True


_BUDGET: ContextVar[_Budget | None] = ContextVar("canonical_read_budget", default=None)


def current_budget() -> _Budget | None:
    """Return this operation's existing capture budget, never authority."""
    return _BUDGET.get()


def _json(value: Any) -> str:
    def default(item: Any) -> str:
        if type(item) is UUID:
            return str(item)
        raise TypeError("noncanonical read projection")
    return json.dumps(value, default=default, sort_keys=True, separators=(",", ":"), allow_nan=False)


async def capture_plan(
    owner: Any, port: Any, plan: object, *, history: Any, lots: Any, margin: Any,
    ledger: Any, quotes: Any, timeout_seconds: float,
) -> BrokerObservationSnapshot | BrokerReadFailure:
    """Collect explicit surfaces using only the actual bound owner's methods.

    Optional selections are never guessed. Unavailable fees/quotes/protection
    remain labelled unavailable, not synthetic empty or complete evidence.
    """
    entered = time.monotonic()
    try:
        if (type(plan) is not ReadPlanV2 or type(plan.surfaces) is not list
                or any(type(item) is not str for item in plan.surfaces)
                or any(type(item) is not int for item in (plan.max_reads, plan.max_pages, plan.deadline_ms))):
            raise ValueError
        plan = ReadPlanV2.model_validate({
            "surfaces": list(plan.surfaces), "max_reads": plan.max_reads,
            "max_pages": plan.max_pages, "deadline_ms": plan.deadline_ms,
        })
        remaining = plan.deadline_ms / 1000 - time.time()
        if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
                or not 0 < timeout_seconds <= 60 or not 0 < remaining <= 60):
            raise ValueError
        # Validation and the initial real authority read spend the original
        # window; neither may restart an elapsed absolute/request deadline.
        deadline = entered + min(remaining, timeout_seconds)
        for value, expected in ((history, TradeHistoryRequest), (ledger, LedgerRequest)):
            if value is not None:
                if type(value) is not expected:
                    raise ValueError
                value.__post_init__()
        if history is not None and "trades" not in plan.surfaces:
            raise ValueError
        if ledger is not None and "fees" not in plan.surfaces:
            raise ValueError
        if quotes is not None:
            if "quotes" not in plan.surfaces:
                raise ValueError
            quotes = owner._copy_request(quotes, BatchQuoteRequest)
            if not 1 <= len(quotes.instruments) <= 64:
                raise ValueError
        if lots is not None:
            lots = owner._copy_request(lots, LotSizeRequest)
            if not 1 <= len(lots.symbols) <= 64:
                raise ValueError
        if margin is not None:
            margin = owner._copy_request(margin, MarginRequest)
    except (TypeError, ValueError):
        return BrokerReadFailure(BrokerReadErrorCode.INVALID_REQUEST)
    binding = owner.observation_binding(port)
    if type(binding) is BrokerReadFailure:
        return binding
    started = datetime.now(UTC)
    budget = _Budget(plan.max_reads, plan.max_pages, deadline)
    surfaces: list[CapturedReadSurface] = []
    trades, contracts, margins, postings = (), (), (), ()
    provenance = _json(asdict(binding[0]))

    async def collect(surface: str, family: str | None, factory: Any, *, paged: bool = False) -> Any:
        before = datetime.now(UTC).isoformat()
        previous_issues = set(budget.issues)
        if factory is None:
            outcome = BrokerReadFailure(BrokerReadErrorCode.UNSUPPORTED)
        else:
            try:
                outcome = await factory() if paged else await owner._bounded_observation(factory, deadline, facade=port)
            except TimeoutError:
                budget.issues.add("read_deadline_exceeded")
                outcome = BrokerReadFailure(BrokerReadErrorCode.PROVIDER_FAILURE)
        value_json, inherited = None, None
        if type(outcome) is BrokerReadSuccess:
            value = outcome.value
            if surface == "trades":
                rows = value.trades
                inherited = getattr(value, "coverage", None)
            elif surface == "fees":
                rows, inherited = value.postings, value.coverage
            else:
                rows = value if type(value) is tuple else (value,)
            value_json = _json([asdict(row) for row in rows])
            count = len(rows)
        else:
            count = 0
        resource = surface + ("." + family if family is not None else "")
        coverage = inherited or ObservationCoverage(
            resource=resource,
            availability="available" if type(outcome) is BrokerReadSuccess else outcome.code.value,
            query_start=None, query_end=None, trading_date=None, timezone=None,
            page_model="unpaged_observation", pages=(), observed_count=count, source_digest=None,
            source_revision="broker_read.plan.v2", completeness="unknown",
            issues=("lifetime_completeness_unverified",),
        )
        provider_coverage = getattr(outcome.value, "provider_coverage_json", None) if type(
            outcome) is BrokerReadSuccess else None
        coverage = replace(
            coverage, source_digest=hashlib.sha256(value_json.encode()).hexdigest() if value_json is not None else None,
            provider_account_id=binding[1], provenance_json=provenance, started_at=before,
            finished_at=datetime.now(UTC).isoformat(), returned_count=count if value_json is not None else None,
            issues=tuple(sorted(set(coverage.issues) | (budget.issues - previous_issues))),
            provider_coverage_json=coverage.provider_coverage_json or provider_coverage,
        )
        surfaces.append(CapturedReadSurface(surface, family, value_json, coverage))
        return outcome

    token = _BUDGET.set(budget)
    try:
        for surface in plan.surfaces:
            if surface == "orders":
                await collect(surface, "regular", lambda: owner._order_states(port, OrderStateRequest(
                    BrokerOrderFamily.REGULAR)))
            elif surface == "positions":
                await collect(surface, None, lambda: owner._positions(port))
            elif surface == "holdings":
                await collect(surface, None, lambda: owner._holdings(port))
            elif surface == "trades":
                result = await collect(surface, "daily", lambda: owner._capture_trade_book(port))
                if type(result) is BrokerReadSuccess:
                    trades += result.value.trades
                if history is not None:
                    result = await collect(surface, "history", lambda: owner._trade_history(port, history,
                        deadline=deadline), paged=True)
                    if type(result) is BrokerReadSuccess:
                        trades += result.value.trades
            elif surface == "fees":
                result = await collect(surface, "account_postings", (lambda: owner._ledger(port, ledger)) 
                    if ledger else None)
                if type(result) is BrokerReadSuccess:
                    postings = result.value.postings
            elif surface == "broker_protection":
                for family in (BrokerOrderFamily.FOREVER, BrokerOrderFamily.SUPER):
                    await collect(surface, family.value, lambda family=family: owner._order_states(port,
                        OrderStateRequest(family)))
            elif surface == "quotes":
                await collect(surface, None, (lambda: owner._batch_quotes(port, quotes)) if quotes else None)
        if lots is not None:
            result = await collect("instruments", "contracts", lambda: owner._lot_sizes(port, lots))
            if type(result) is BrokerReadSuccess:
                contracts = result.value
        if margin is not None:
            result = await collect("margin", "single_estimate", lambda: owner._margin(port, margin))
            if type(result) is BrokerReadSuccess:
                margins = (result.value,)
    finally:
        _BUDGET.reset(token)
    if owner.observation_binding(port) != binding:
        return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
    finished = datetime.now(UTC)
    if finished < started:
        return BrokerReadFailure(BrokerReadErrorCode.TARGET_STALE)
    captured = BrokerObservationSnapshot(
        binding[0], binding[1], started.isoformat(), finished.isoformat(), trades,
        tuple(row.coverage for row in surfaces), contracts=contracts, margins=margins,
        account_postings=postings, surfaces=tuple(surfaces),
    )
    token = _BUDGET.set(budget)
    try:
        captured = await owner._capture_native_scope(port, captured, deadline)
    finally:
        _BUDGET.reset(token)
    if type(captured) is BrokerReadFailure:
        return captured
    return replace(captured, finished_at=datetime.now(UTC).isoformat(),
        read_budget_json=_json({"plan": plan.model_dump(), "reserved_reads": budget.reads,
                               "reserved_pages": budget.pages, "issues": sorted(budget.issues)}))
