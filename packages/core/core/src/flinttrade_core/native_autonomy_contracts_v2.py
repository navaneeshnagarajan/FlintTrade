"""Native autonomy v2 transport only. Validation creates no authority."""
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Representation bounds are not operator risk defaults. No exponent, sign,
# redundant zero or binary floating-point money crosses this transport.
PositiveDecimal = Annotated[
    str, Field(pattern=r"^(?:[1-9][0-9]{0,17}(?:\.[0-9]{0,7}[1-9])?|0\.[0-9]{0,7}[1-9])(?![\s\S])")
]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}(?![\s\S])")]


class ClosedModel(BaseModel):
    """Closed, strict transport object with frozen attribute assignment.

    Nested collections are not an authority or immutable evidence store.
    Trusted owners must resolve and validate references independently."""
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True, regex_engine="python-re")


class PositiveMoneyV2(ClosedModel):
    """Canonical positive decimal text with an explicit currency code.

    The grammar bounds representation, not operator risk. Currency eligibility,
    valuation and exact arithmetic remain the consuming owner's obligations.

    Attributes:
        amount: Positive decimal without exponents or redundant zeroes.
        currency: Three uppercase letters; not proof of a supported currency."""
    amount: PositiveDecimal
    currency: Currency


OpaqueId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}(?![\s\S])")]
# The execution-session registry/client domain is narrower than revision IDs.
RunId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}(?![\s\S])")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}(?![\s\S])")]
BrokerId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}(?![\s\S])")]
AccountId = Annotated[str, Field(pattern=r"^(?=[A-Za-z0-9._:@+\-]*[A-Za-z0-9])[A-Za-z0-9._:@+\-]{1,128}(?![\s\S])")]
UUIDText = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![\s\S])")]
UUID4Text = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}(?![\s\S])")
]
OperatorId = Annotated[str, Field(pattern=r"^operator:[0-9a-f]{64}(?![\s\S])")]
BoundedActor = Annotated[str, Field(pattern=r"^bounded:[A-Za-z0-9][A-Za-z0-9_.:@-]{0,127}(?![\s\S])")]
# JSON numbers are bounded to the exact interoperable integer domain.
PositiveInt = Annotated[int, Field(gt=0, le=9007199254740991)]
NonNegativeInt = Annotated[int, Field(ge=0, le=9007199254740991)]
TimestampMs = PositiveInt


class RevisionRefV2(ClosedModel):
    """Case-sensitive identifier and digest-shaped revision selection.

    A well-formed reference proves neither existence nor integrity. Its owner
    must resolve immutable content and compare the actual revision."""
    id: OpaqueId
    revision: Digest


class RiskPolicyV2(ClosedModel):
    """Operator-valued, single-currency risk policy description.

    Capital commitments are non-replenishing and fee-inclusive. Exposure uses
    the higher of entry cost and fresh mark, including possible fills and exit
    fees. Loss is run-lifetime net realised plus unrealised P&L after incurred
    fees and remaining reserved closing fees for already-filled exposure.
    An incurred charge consumes its corresponding reserve: never count it twice.
    Pending-entry allowances are capital/exposure reservations, not realised
    loss. Unknown fees must remain unknown, not become zero.

    Attributes:
        fee_policy_ref: Immutable policy selection carrying those fee semantics.
            The owner must resolve and verify its dated tariff, allocation and
            reserve basis; a well-formed reference is not fee-policy proof.
        loss_action_threshold: Required operator value, not a guaranteed loss cap.
        threshold_action: Latched entry retirement and custody handling, never
            automatic liquidation or independent post-stop agent authority."""
    policy_ref: RevisionRefV2
    capital_basis: Literal["non_replenishing_fee_inclusive_commitments"]
    exposure_basis: Literal["max_entry_cost_fresh_mark_plus_possible_fills_and_exit_fees"]
    loss_basis: Literal["run_lifetime_net_realised_plus_unrealised_after_fees"]
    threshold_action: Literal["latch_entry_retirement_and_broker_held_or_handback"]
    capital_cap: PositiveMoneyV2
    exposure_cap: PositiveMoneyV2
    loss_action_threshold: PositiveMoneyV2
    max_mark_age_ms: PositiveInt
    fee_policy_ref: RevisionRefV2

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "risk_currency"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if len({self.capital_cap.currency, self.exposure_cap.currency, self.loss_action_threshold.currency}) != 1:
            raise ValueError("risk_currency")
        return self


class OptionsRiskPolicyV2(ClosedModel):
    """Versioned index-options budgeting, separate from the accepted cash policy.

    Long premiums and standalone short margin commitments plus fees consume a
    non-replenishing lifetime budget. Premium receipts/profits are not credits.
    Exposure is gross underlying notional: different contracts never net, even
    when a strategy is hedged. Independent possible writes and fee liabilities
    remain. A finite cap is NOT a maximum realised loss, especially for shorts.
    Numeric values are mandatory operator selections, not broker qualification.
    Paid fees leave only exposure when exact attribution proves full closure;
    lifetime capital/loss retain them. This DTO supplies no trusted evidence.
    """
    profile_version: Literal["index_options_v1"]
    policy_ref: RevisionRefV2
    capital_basis: Literal["non_replenishing_long_premium_short_standalone_margin_plus_fees"]
    exposure_basis: Literal["gross_underlying_notional_no_cross_contract_netting_plus_liabilities"]
    loss_basis: Literal["run_lifetime_net_realised_plus_unrealised_after_fees"]
    threshold_action: Literal["latch_entry_retirement_and_broker_held_or_handback"]
    capital_cap: PositiveMoneyV2
    exposure_cap: PositiveMoneyV2
    loss_action_threshold: PositiveMoneyV2
    max_mark_age_ms: PositiveInt
    fee_policy_ref: RevisionRefV2

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "options_risk_currency"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Require one currency without establishing currency eligibility.

        Returns:
            This structurally coherent policy.

        Raises:
            ValueError: If the supplied money fields use different currencies.
        """
        if len({self.capital_cap.currency, self.exposure_cap.currency, self.loss_action_threshold.currency}) != 1:
            raise ValueError("options_risk_currency")
        return self


class CustodyPolicyV2(ClosedModel):
    """Selected pre-entry acceptance and no-post-stop-write policy.

    Trusted owners must verify broker-held protection or receiving-operator
    acceptance before entry. Parsing cannot establish custody or bypass kill."""
    policy_ref: RevisionRefV2
    fallback: Literal["receiving_operator_acceptance_before_entry"]
    after_entry_retirement: Literal["broker_held_or_operator_handback_no_agent_writes"]
    global_kill: Literal["blocks_all_agent_writes"]


class InstrumentV2(ClosedModel):
    """Exact instrument, exchange and product selection.

    The instrument owner must resolve these case-sensitive IDs and eligibility;
    transport syntax alone does not establish a tradable instrument."""
    instrument_id: OpaqueId
    exchange: OpaqueId
    product: OpaqueId


class EntryLimitsV2(ClosedModel):
    """Explicit finite entry limits with unique instruments and actions.

    Per-order quantity cannot exceed total quantity, and place must be selected.
    Owners enforce cumulative usage and expiry; decoding allocates no budget."""
    instruments: Annotated[list[InstrumentV2], Field(min_length=1, max_length=100)]
    actions: Annotated[list[Literal["place", "cancel_unfilled"]], Field(min_length=1, max_length=2)]
    max_order_quantity: PositiveInt
    max_total_quantity: PositiveInt
    max_commands: PositiveInt
    max_reads: PositiveInt
    max_duration_ms: PositiveInt

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "entry_limits"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        identities = {(i.instrument_id, i.exchange, i.product) for i in self.instruments}
        if (self.max_order_quantity > self.max_total_quantity or len(identities) != len(self.instruments)
                or len(set(self.actions)) != len(self.actions) or "place" not in self.actions):
            raise ValueError("entry_limits")
        return self


class ModelPinV2(ClosedModel):
    """Selected model/connection revisions and explicit request budgets.

    Provider identity, privacy, tariff and readiness require trusted resolution.
    Reading this record must not acquire a model or send a readiness request."""
    connection_ref: RevisionRefV2
    model_ref: RevisionRefV2
    protocol: OpaqueId
    effort: OpaqueId
    max_requests: PositiveInt
    max_tokens: PositiveInt
    cost_cap: PositiveMoneyV2


class ProducerPinV2(ClosedModel):
    """Producer/source/config pins with a model pin only for model runs.

    Registration, availability and runtime identity remain owner checks; the
    discriminator cannot start a worker or establish model qualification."""
    kind: Literal["deterministic", "model"]
    producer_ref: RevisionRefV2
    source_revision: Digest
    config_revision: Digest
    model: ModelPinV2 | None

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "producer_pin"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if (self.kind == "model") != (self.model is not None):
            raise ValueError("producer_pin")
        return self


class NativeRunConfigV2(ClosedModel):
    """Exact run/account/environment and reviewed policy selections.

    Configuration is not qualification, grant or Start. Owners resolve the
    producer/profile/policies and retain the immutable binding independently."""
    run_id: RunId
    broker: BrokerId
    account_id: AccountId
    environment: Literal["production", "synthetic", "demo_broker"]
    operation_profile_ref: RevisionRefV2
    producer: ProducerPinV2
    risk: RiskPolicyV2
    custody: CustodyPolicyV2


class ConfigureRequestV2(ClosedModel):
    """Versioned configuration request without caller-issued authority.

    The receiving owner authenticates the principal and resolves all selections;
    no request field supplies trusted evidence, credentials or readiness."""
    schema_version: Literal["2"]
    config: NativeRunConfigV2


class RunScopeV2(ClosedModel):
    """Exact run/operator/actor/account and generation binding description.

    The bounded actor suffix must equal run_id with case preserved. An owner
    must authenticate the operator and resolve account/generation identity."""
    run_id: RunId
    operator: OperatorId
    actor: BoundedActor
    broker: BrokerId
    account_id: AccountId
    environment: Literal["production", "synthetic", "demo_broker"]
    registry_generation: PositiveInt
    binding_revision: Digest

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "run_scope"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if self.actor != f"bounded:{self.run_id}":
            raise ValueError("run_scope")
        return self


class BrokerReadProvenanceV2(ClosedModel):
    """Flattened successful BrokerReadProvenance, never a read capability.

    Selector is shared by registry and credential versions; workspace incarnation
    is shared by both workspace counters. Generations exceeding JS safe integers
    refuse transport rather than silently lose identity. The read owner must
    resolve the actual versions and permissions; syntax is not provenance proof.
    """
    broker: BrokerId
    account_id: AccountId
    registry_incarnation: UUID4Text
    registry_generation: PositiveInt
    vault_incarnation: UUID4Text
    credential_generation: PositiveInt
    workspace_instance_id: UUIDText
    workspace_generation: PositiveInt
    broker_workspace_generation: PositiveInt
    requested_role: Literal["quote", "historical", "option_chains", "global_indices"] | None


ReadSurface = Literal["orders", "positions", "holdings", "trades", "fees", "broker_protection", "quotes"]
Availability = Literal["complete", "partial", "unavailable", "unsupported", "stale", "conflicting"]


class CoverageV2(ClosedModel):
    """Supplied read-family window and pagination/completeness description.

    Windows are ordered; complete requires completed pages. Only the read owner
    can establish that a real broker surface and required history are complete."""
    surface: ReadSurface
    family: OpaqueId
    availability: Availability
    pages_complete: bool
    window_start_ms: TimestampMs
    window_end_ms: TimestampMs

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "coverage"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if self.window_start_ms > self.window_end_ms or (self.availability == "complete" and not self.pages_complete):
            raise ValueError("coverage")
        return self


class ObservationRefV2(ClosedModel):
    """Versioned observation selection with coherent supplied coverage.

    Surface/family pairs are unique and times cannot exceed collection time.
    Required nullable broker fields retain absence. Freshness, scope, allocation
    and actual completeness must be independently checked by the evidence owner."""
    observation_ref: RevisionRefV2
    provenance: BrokerReadProvenanceV2
    canonical_generation: PositiveInt
    collection_id: OpaqueId
    collected_at_ms: TimestampMs
    availability: Availability
    coverage: Annotated[list[CoverageV2], Field(min_length=1, max_length=100)]
    identity_namespace: OpaqueId
    broker_source_sequence: OpaqueId | None
    broker_as_of_ms: TimestampMs | None

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "observation"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        identities = {(c.surface, c.family) for c in self.coverage}
        if (len(identities) != len(self.coverage)
                or any(c.window_end_ms > self.collected_at_ms for c in self.coverage)
                or (self.availability == "complete" and any(c.availability != "complete" for c in self.coverage))
                or (self.broker_as_of_ms is not None and self.broker_as_of_ms > self.collected_at_ms)):
            raise ValueError("observation")
        return self


class ReadPlanV2(ClosedModel):
    """Explicit finite read plan with unique requested surfaces.

    The read owner authenticates and enforces these bounds. Parsing neither
    performs external I/O nor confers permission to inspect an account."""
    surfaces: Annotated[list[ReadSurface], Field(min_length=1, max_length=7)]
    max_reads: PositiveInt
    max_pages: PositiveInt
    deadline_ms: TimestampMs

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "read_plan"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if len(set(self.surfaces)) != len(self.surfaces):
            raise ValueError("read_plan")
        return self


class InspectRequestV2(ClosedModel):
    """Versioned request for explicit, bounded owner-backed inspection.

    The owner validates the binding and read permission before gathering facts;
    this request cannot upload trusted reports or silently create a grant."""
    schema_version: Literal["2"]
    run_id: RunId
    expected_binding_revision: Digest
    read_plan: ReadPlanV2


FactStatus = Literal["verified", "missing", "stale", "conflicting", "unsupported", "not_required"]
Provenance = Literal[
    "documented_contract",
    "reviewed_software",
    "installed_runtime",
    "operator_policy",
    "broker_read",
    "demonstrated_broker_action",
    "synthetic",
    "demo_broker",
]
ReasonCode = Literal[
    "evidence_missing",
    "evidence_stale",
    "evidence_conflicting",
    "unsupported_profile",
    "synthetic_only",
    "demo_only",
    "custody_required",
    "fees_unknown",
    "producer_unavailable",
    "qualification_required",
    "grant_required",
    "entry_retired",
    "global_kill",
    "loss_threshold_latched",
    "unknown_possible_writes",
    "reconciliation_required",
]
NextAction = Literal[
    "configure",
    "inspect",
    "review_evidence",
    "request_grant",
    "start",
    "stop_entries",
    "reconcile",
    "accept_transfer",
    "wait_for_observation",
]


class EvidenceFactV2(ClosedModel):
    """Status/provenance/time description of one evidence dimension.

    Verified/stale facts require timed references; reviewed exemptions retain
    documented-contract provenance. Owners must verify genuine evidence and
    current freshness rather than trusting these well-formed descriptions."""
    status: FactStatus
    provenance: Provenance
    verifier_ref: RevisionRefV2
    profile_ref: RevisionRefV2
    evidence_ref: RevisionRefV2 | None
    observed_at_ms: TimestampMs | None
    expires_at_ms: TimestampMs | None
    operation: OpaqueId
    coverage: Annotated[list[ReadSurface], Field(min_length=1, max_length=7)]

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "evidence_fact"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        timed = self.observed_at_ms is not None and self.expires_at_ms is not None
        if ((self.observed_at_ms is None) != (self.expires_at_ms is None)
                or (self.observed_at_ms is not None and self.expires_at_ms is not None
                    and self.expires_at_ms <= self.observed_at_ms)
                or (self.status in {"verified", "stale"} and (not timed or self.evidence_ref is None))
                or (self.status == "not_required" and self.provenance != "documented_contract")
                or len(set(self.coverage)) != len(self.coverage)):
            raise ValueError("evidence_fact")
        return self


class QualificationDimensionsV2(ClosedModel):
    """Separate software, account, read, action, custody, fee and producer facts.

    No individual verified dimension establishes whole-run eligibility. The
    qualification owner resolves each fact and the reviewed operation profile."""
    software: EvidenceFactV2
    account_eligibility: EvidenceFactV2
    observations: EvidenceFactV2
    demonstrated_action: EvidenceFactV2
    custody: EvidenceFactV2
    fees: EvidenceFactV2
    producer: EvidenceFactV2


class QualificationReportV2(ClosedModel):
    """Coherent server report description, not trusted qualification.

    Eligible descriptions require matching profiles, covering evidence times
    and environment-appropriate provenance; blocked reports retain reasons.
    Owners independently authenticate, resolve and verify every referenced fact.
    Synthetic examples and arbitrary fee references are never production proof."""
    schema_version: Literal["2"]
    report_ref: RevisionRefV2
    scope: RunScopeV2
    profile_ref: RevisionRefV2
    policy_ref: RevisionRefV2
    generated_at_ms: TimestampMs
    expires_at_ms: TimestampMs
    status: Literal["blocked", "eligible"]
    dimensions: QualificationDimensionsV2
    blocking_reasons: Annotated[list[ReasonCode], Field(max_length=20)]
    next_actions: Annotated[list[NextAction], Field(max_length=10)]

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "qualification_report"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        d = self.dimensions
        facts = (
            d.software, d.account_eligibility, d.observations, d.demonstrated_action,
            d.custody, d.fees, d.producer,
        )
        if (self.expires_at_ms <= self.generated_at_ms
                or any(f.profile_ref != self.profile_ref for f in facts)
                or (self.status == "blocked") != bool(self.blocking_reasons)):
            raise ValueError("qualification_report")
        if self.status == "eligible":
            if any(f.status not in {"verified", "not_required"} for f in facts):
                raise ValueError("qualification_report")
            if any(f.status == "verified" and (f.observed_at_ms is None or f.expires_at_ms is None
                    or f.observed_at_ms > self.generated_at_ms or self.expires_at_ms > f.expires_at_ms) for f in facts):
                raise ValueError("qualification_report")
            if self.scope.environment == "production":
                allowed = ({"reviewed_software", "installed_runtime"}, {"broker_read"}, {"broker_read"},
                           {"demonstrated_broker_action"}, {"demonstrated_broker_action", "operator_policy"},
                           {"documented_contract", "broker_read"}, {"reviewed_software", "installed_runtime"})
                if any(f.status != "not_required" and f.provenance not in kinds for f, kinds in zip(facts, allowed)):
                    raise ValueError("qualification_report")
        return self


class GrantRequestV2(ClosedModel):
    """Explicit grant selection and limits, separate from Start.

    Authentication, report/policy resolution and current qualification belong
    to the grant owner. A caller cannot submit its own trusted grant object."""
    schema_version: Literal["2"]
    run_id: RunId
    expected_binding_revision: Digest
    report_ref: RevisionRefV2
    policy_ref: RevisionRefV2
    limits: EntryLimitsV2
    expires_at_ms: TimestampMs


class EntryGrantV2(ClosedModel):
    """Server grant description, never an execution port.

    Issuer, policy and duration must agree locally. The authenticated grant
    owner must resolve current qualification, usage and expiry independently;
    the string state ``active`` cannot confer execution authority.
    """
    grant_ref: RevisionRefV2
    scope: RunScopeV2
    report_ref: RevisionRefV2
    policy_ref: RevisionRefV2
    risk: RiskPolicyV2
    limits: EntryLimitsV2
    issued_by: OperatorId
    issued_at_ms: TimestampMs
    expires_at_ms: TimestampMs
    state: Literal["active", "retired", "expired", "revoked"]

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "entry_grant"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if (self.issued_by != self.scope.operator or self.policy_ref != self.risk.policy_ref
                or not 0 < self.expires_at_ms - self.issued_at_ms <= self.limits.max_duration_ms):
            raise ValueError("entry_grant")
        return self


class StartRequestV2(ClosedModel):
    """Exact run/binding/grant selection for a separate Start request.

    The existing execution owner must resolve authority, qualification, custody
    and current risk before Start; decoding creates neither a port nor worker."""
    schema_version: Literal["2"]
    run_id: RunId
    expected_binding_revision: Digest
    grant_ref: RevisionRefV2


class ModelAttemptDutyV2(ClosedModel):
    """Exact service-attempt observation; unknown cost is never broker quantity."""
    attempt_id: UUIDText
    receipt_ref: RevisionRefV2
    state: Literal["PREPARED", "INVOKED", "UNKNOWN", "SETTLED", "CANCELLED"]
    tokens_reserved: NonNegativeInt
    cost_micros_reserved: NonNegativeInt
    observed_tokens: NonNegativeInt | None
    observed_cost_micros: NonNegativeInt | None
    currency: Currency
    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "model_attempt_duty"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Require known usage only for evidenced terminal attempt states.

        Returns:
            This unchanged strict observation, never reconciliation authority.

        Raises:
            ValueError: Known/unknown values contradict the supplied state.
        """
        known = self.state in {"SETTLED", "CANCELLED"}
        if ((self.observed_tokens is not None) != known
                or (self.observed_cost_micros is not None) != known
                or (self.state == "CANCELLED" and (self.observed_tokens != 0 or self.observed_cost_micros != 0))):
            raise ValueError("model_attempt_duty")
        return self


class ModelDutyV2(ClosedModel):
    """Outstanding model task responsibility, separate from broker-write duty.

    Reservations remain lifetime budget debits even after this outstanding
    projection resolves. The existing service ledger alone settles attempts.
    """
    request_ref: RevisionRefV2
    task_outcome: Literal["reserved", "pending", "completed", "refused"]
    tokens_reserved: NonNegativeInt
    cost_micros_reserved: NonNegativeInt
    currency: Currency
    attempts: Annotated[list[ModelAttemptDutyV2], Field(max_length=1000)]
    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "model_duty"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Check unresolved status, unique attempts and one monetary domain.

        Returns:
            This supplied outstanding duty without granting any authority.

        Raises:
            ValueError: The supplied census is duplicate, resolved or mixed-currency.
        """
        if (len({a.attempt_id for a in self.attempts}) != len(self.attempts)
                or any(a.currency != self.currency for a in self.attempts)
                or (self.task_outcome not in {"reserved", "pending"}
                    and all(a.state in {"SETTLED", "CANCELLED"} for a in self.attempts))):
            raise ValueError("model_duty")
        return self


class OutstandingObligationV2(ClosedModel):
    """One supplied possible entry, executable exit or unknown write.

    Attributes:
        obligation_id: Unique within a supplied census, not proof of allocation.
        attempt_ref: Owner-resolved dispatch lineage, not proof of non-invocation.
        possible_quantity: Remaining possible quantity; null retains uncertainty.

    The owner must retain all unresolved obligations across Stop and transfer."""
    obligation_id: OpaqueId
    attempt_ref: RevisionRefV2
    kind: Literal["possible_entry", "independently_executable_exit", "unknown_write"]
    possible_quantity: NonNegativeInt | None


class DutyViewV2(ClosedModel):
    """Retained duty/custody description with local census consistency.

    Attributes:
        possible_entry_quantity: Exact sum of the supplied possible_entry
            quantities when known. Null if any entry quantity or write direction
            is unknown. Independently executable exits do not offset entries.
        unknown_possible_writes: Matches unknown_write items, independently of
            whether a known entry's quantity is unknown.
        obligations: Supplied unresolved census with unique obligation IDs.

    Fills need references and exits cannot exceed cumulative entries. Settled
    requires an empty census and matching fills; transfer does not mean flat.
    Owners still prove real census completeness, allocation, protection and
    acceptance. This DTO cannot discover an omitted broker attempt."""
    duty_ref: RevisionRefV2
    scope: RunScopeV2
    obligation_revision: Digest
    possible_entry_quantity: NonNegativeInt | None
    cumulative_entry_fill: NonNegativeInt
    cumulative_exit_fill: NonNegativeInt
    entry_fill_refs: Annotated[list[RevisionRefV2], Field(max_length=1000)]
    exit_fill_refs: Annotated[list[RevisionRefV2], Field(max_length=1000)]
    obligations: Annotated[list[OutstandingObligationV2], Field(max_length=1000)]
    model_obligations: Annotated[list[ModelDutyV2], Field(max_length=1000)]
    unknown_possible_writes: bool
    coverage: Literal["verified_broker_held", "operator_accepted", "absent", "stale", "conflicting", "unknown"]
    custody: Literal["run_retained", "broker_held", "operator"]
    custody_revision: Digest
    receiving_acceptance_ref: RevisionRefV2 | None
    state: Literal["contingent", "open", "handback_required", "transferred", "reconciliation_required", "settled"]
    reasons: Annotated[list[ReasonCode], Field(max_length=20)]

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "duty"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        unknown = any(o.kind == "unknown_write" for o in self.obligations)
        quantities = [o.possible_quantity for o in self.obligations if o.kind == "possible_entry"]
        # This reconciles only the supplied census, never broker completeness.
        # Unknown direction or entry quantity cannot become a finite summary.
        possible = None if unknown or None in quantities else sum(q for q in quantities if q is not None)
        if (self.possible_entry_quantity != possible
                or self.cumulative_exit_fill > self.cumulative_entry_fill
                or (self.cumulative_entry_fill > 0 and not self.entry_fill_refs)
                or (self.cumulative_exit_fill > 0 and not self.exit_fill_refs)
                or self.unknown_possible_writes != unknown
                or len({m.request_ref.id for m in self.model_obligations}) != len(self.model_obligations)
                or len({o.obligation_id for o in self.obligations}) != len(self.obligations)
                or (self.custody == "operator" and self.receiving_acceptance_ref is None)
                or (self.coverage == "operator_accepted" and self.custody != "operator")
                or (self.custody == "broker_held" and self.coverage != "verified_broker_held")
                or (self.state == "transferred" and self.custody != "operator")
                or (self.state == "settled" and (self.obligations or self.model_obligations
                    or self.possible_entry_quantity != 0
                    or self.cumulative_entry_fill != self.cumulative_exit_fill))):
            raise ValueError("duty")
        return self


class TransferAcceptRequestV2(ClosedModel):
    """Exact preview and duty revision selected for acceptance.

    The receiving owner must authenticate the receiver, resolve the preview and
    enforce one-use/current binding. Sender-supplied identity is not acceptance."""
    schema_version: Literal["2"]
    preview_ref: RevisionRefV2
    expected_duty_revision: Digest


class TransferReceiptV2(ClosedModel):
    """Non-flat custody-transfer description retaining unresolved scope.

    Account/generation agree and obligations require reconciliation. Real
    receiver authentication, continuing lineage and durable custody must be
    verified by the owner; this receipt cannot erase unknown writes."""
    transfer_ref: RevisionRefV2
    duty_ref: RevisionRefV2
    scope: RunScopeV2
    account_provenance: BrokerReadProvenanceV2
    obligation_revision: Digest
    accepted_payload_digest: Digest
    receiving_operator: OperatorId
    accepted_at_ms: TimestampMs
    custody_location_ref: RevisionRefV2
    obligations: Annotated[list[OutstandingObligationV2], Field(max_length=1000)]
    model_obligations: Annotated[list[ModelDutyV2], Field(max_length=1000)]
    unknown_possible_writes: bool
    reconciliation_required: bool
    custody: Literal["operator"]
    outcome: Literal["custody_transferred_not_flatness"]

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "transfer"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if (self.scope.broker != self.account_provenance.broker
                or self.scope.account_id != self.account_provenance.account_id
                or self.scope.registry_generation != self.account_provenance.registry_generation
                or self.unknown_possible_writes != any(o.kind == "unknown_write" for o in self.obligations)
                or ((self.obligations or self.model_obligations) and not self.reconciliation_required)
                or len({m.request_ref.id for m in self.model_obligations}) != len(self.model_obligations)
                or len({o.obligation_id for o in self.obligations}) != len(self.obligations)):
            raise ValueError("transfer")
        return self


class HistoricalTransferReceiptV2(ClosedModel):
    """Historical receipt shape before the explicit model-duty census.

    Absence of model duties in this old shape is not proof of their resolution.
    This readback-only nominal variant preserves the exact originally accepted
    payload; it must never qualify a new finite grant.

    Account/generation agree and obligations require reconciliation. Real
    receiver authentication, continuing lineage and durable custody must be
    verified by the owner; this receipt cannot erase unknown writes."""
    transfer_ref: RevisionRefV2
    duty_ref: RevisionRefV2
    scope: RunScopeV2
    account_provenance: BrokerReadProvenanceV2
    obligation_revision: Digest
    accepted_payload_digest: Digest
    receiving_operator: OperatorId
    accepted_at_ms: TimestampMs
    custody_location_ref: RevisionRefV2
    obligations: Annotated[list[OutstandingObligationV2], Field(max_length=1000)]
    unknown_possible_writes: bool
    reconciliation_required: bool
    custody: Literal["operator"]
    outcome: Literal["custody_transferred_not_flatness"]

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "historical_transfer"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        if (self.scope.broker != self.account_provenance.broker
                or self.scope.account_id != self.account_provenance.account_id
                or self.scope.registry_generation != self.account_provenance.registry_generation
                or self.unknown_possible_writes != any(o.kind == "unknown_write" for o in self.obligations)
                or (self.obligations and not self.reconciliation_required)
                or len({o.obligation_id for o in self.obligations}) != len(self.obligations)):
            raise ValueError("historical_transfer")
        return self


class RunViewV2(ClosedModel):
    """Separate authority, entry, producer, freshness and custody descriptions.

    References and scopes must agree. Bounded-entry descriptions require a
    coherent report/grant and finite known possible-entry census with custody;
    kill/loss retirement cannot describe effective entry authority. None of
    these local checks authenticates, qualifies, starts or grants a real run."""
    schema_version: Literal["2"]
    scope: RunScopeV2
    config: NativeRunConfigV2
    requested_authority: Literal["none", "bounded_entry"]
    effective_authority: Literal["none", "bounded_entry"]
    entry_state: Literal["ungranted", "granted", "started", "retired"]
    producer_state: Literal["not_started", "running", "stopping", "stopped", "failed"]
    duty_state: Literal["none", "retained", "broker_held", "operator", "reconciliation_required"]
    observation_freshness: Literal["missing", "fresh", "stale", "conflicting"]
    report: QualificationReportV2 | None
    grant: EntryGrantV2 | None
    duty: DutyViewV2 | None
    transfer_receipts: Annotated[list[TransferReceiptV2 | HistoricalTransferReceiptV2], Field(max_length=1000)]
    global_kill: bool
    loss_threshold_latched: bool
    events: Annotated[list[RevisionRefV2], Field(max_length=1000)]
    next_actions: Annotated[list[NextAction], Field(max_length=10)]

    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "run_view"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Validate this description's local cross-field transport invariants.

        Returns:
            This record unchanged when its supplied fields are coherent.

        Raises:
            ValueError: The supplied description contradicts this DTO's rule.
                Passing does not establish owner-backed authority or evidence.
        """
        s, c, r, g, d = self.scope, self.config, self.report, self.grant, self.duty
        if (s.run_id != c.run_id or s.broker != c.broker
                or s.account_id != c.account_id or s.environment != c.environment
                or (r is not None and (r.scope != s or r.profile_ref != c.operation_profile_ref
                                       or r.policy_ref != c.risk.policy_ref))
                or (g is not None and (g.scope != s or g.risk != c.risk))
                or (d is not None and d.scope != s)
                or any(receipt.scope != s for receipt in self.transfer_receipts)
                or len({receipt.transfer_ref.id for receipt in self.transfer_receipts}) != len(self.transfer_receipts)
                or ((d is None) != (self.duty_state == "none"))
                or (d is not None and self.duty_state != "reconciliation_required"
                    and self.duty_state != ("retained" if d.custody == "run_retained" else d.custody))
                or (self.producer_state == "running" and self.entry_state != "started")
                or (self.entry_state in {"granted", "started"} and (g is None or self.global_kill))
                or (self.loss_threshold_latched and self.entry_state != "retired")
                or ((self.global_kill or self.loss_threshold_latched) and self.effective_authority != "none")):
            raise ValueError("run_view")
        if self.effective_authority == "bounded_entry":
            if (self.requested_authority != "bounded_entry" or self.entry_state != "started"
                    or self.producer_state != "running" or self.observation_freshness != "fresh"
                    or r is None or r.status != "eligible" or g is None or g.state != "active"
                    or g.report_ref != r.report_ref or g.expires_at_ms > r.expires_at_ms
                    or g.issued_at_ms < r.generated_at_ms
                    or d is None or d.unknown_possible_writes or d.possible_entry_quantity is None
                    or d.state not in {"contingent", "open"}
                    or d.coverage not in {"verified_broker_held", "operator_accepted"}
                    or self.duty_state == "reconciliation_required"):
                raise ValueError("run_view")
        return self


class OptionsNativeRunConfigV2(ClosedModel):
    """Options-only configuration; deliberately not a cash-model subclass.

    The owner resolves this version separately. A parsed options instance cannot
    bypass the cash decoder through Pydantic's preconstructed-instance fast path.
    """
    run_id: RunId
    broker: BrokerId
    account_id: AccountId
    environment: Literal["production", "synthetic", "demo_broker"]
    operation_profile_ref: RevisionRefV2
    producer: ProducerPinV2
    risk: OptionsRiskPolicyV2
    custody: CustodyPolicyV2


class OptionsConfigureRequestV2(ClosedModel):
    """Explicit derivative transport version; no uploaded evidence/authority."""
    schema_version: Literal["2-options-1"]
    config: OptionsNativeRunConfigV2


class OptionsEntryGrantV2(ClosedModel):
    """Options grant description ONLY, retaining the original local invariants.

    Parsing this object never issues a grant or enables native execution.
    """
    grant_ref: RevisionRefV2
    scope: RunScopeV2
    report_ref: RevisionRefV2
    policy_ref: RevisionRefV2
    risk: OptionsRiskPolicyV2
    limits: EntryLimitsV2
    issued_by: OperatorId
    issued_at_ms: TimestampMs
    expires_at_ms: TimestampMs
    state: Literal["active", "retired", "expired", "revoked"]
    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "options_entry_grant"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Check supplied issuer/policy/duration, never issue authority.

        Returns:
            This coherent description; parsing never issues a grant.

        Raises:
            ValueError: If issuer, policy or the supplied duration disagrees.
        """
        if (self.issued_by != self.scope.operator or self.policy_ref != self.risk.policy_ref
                or not 0 < self.expires_at_ms - self.issued_at_ms <= self.limits.max_duration_ms):
            raise ValueError("options_entry_grant")
        return self


class OptionsRunViewV2(ClosedModel):
    """Versioned derivative view with unchanged custody/authority separation.

    Shared supplied-census and cross-object invariants still apply; no report,
    reference, boolean or successfully decoded view is owner-issued authority.
    This separate nominal class cannot pass a cash decoder as an instance.
    """
    schema_version: Literal["2-options-1"]
    scope: RunScopeV2
    config: OptionsNativeRunConfigV2
    requested_authority: Literal["none", "bounded_entry"]
    effective_authority: Literal["none", "bounded_entry"]
    entry_state: Literal["ungranted", "granted", "started", "retired"]
    producer_state: Literal["not_started", "running", "stopping", "stopped", "failed"]
    duty_state: Literal["none", "retained", "broker_held", "operator", "reconciliation_required"]
    observation_freshness: Literal["missing", "fresh", "stale", "conflicting"]
    report: QualificationReportV2 | None
    grant: OptionsEntryGrantV2 | None
    duty: DutyViewV2 | None
    transfer_receipts: Annotated[list[TransferReceiptV2 | HistoricalTransferReceiptV2], Field(max_length=1000)]
    global_kill: bool
    loss_threshold_latched: bool
    events: Annotated[list[RevisionRefV2], Field(max_length=1000)]
    next_actions: Annotated[list[NextAction], Field(max_length=10)]
    model_config = ConfigDict(json_schema_extra={"x-v2-refinement": "options_run_view"})

    @model_validator(mode="after")
    def coherent(self) -> Self:
        """Preserve original local scope/permission/custody/census invariants.

        Returns:
            This coherent options view, not owner-issued authority.

        Raises:
            ValueError: If scope, permission, custody or census invariants disagree.
        """
        s, c, r, g, d = self.scope, self.config, self.report, self.grant, self.duty
        if (s.run_id != c.run_id or s.broker != c.broker or s.account_id != c.account_id
                or s.environment != c.environment
                or (r is not None and (r.scope != s or r.profile_ref != c.operation_profile_ref
                                       or r.policy_ref != c.risk.policy_ref))
                or (g is not None and (g.scope != s or g.risk != c.risk))
                or (d is not None and d.scope != s)
                or any(receipt.scope != s for receipt in self.transfer_receipts)
                or len({receipt.transfer_ref.id for receipt in self.transfer_receipts}) != len(self.transfer_receipts)
                or ((d is None) != (self.duty_state == "none"))
                or (d is not None and self.duty_state != "reconciliation_required"
                    and self.duty_state != ("retained" if d.custody == "run_retained" else d.custody))
                or (self.producer_state == "running" and self.entry_state != "started")
                or (self.entry_state in {"granted", "started"} and (g is None or self.global_kill))
                or (self.loss_threshold_latched and self.entry_state != "retired")
                or ((self.global_kill or self.loss_threshold_latched) and self.effective_authority != "none")):
            raise ValueError("options_run_view")
        if self.effective_authority == "bounded_entry":
            if (self.requested_authority != "bounded_entry" or self.entry_state != "started"
                    or self.producer_state != "running" or self.observation_freshness != "fresh"
                    or r is None or r.status != "eligible" or g is None or g.state != "active"
                    or g.report_ref != r.report_ref or g.expires_at_ms > r.expires_at_ms
                    or g.issued_at_ms < r.generated_at_ms
                    or d is None or d.unknown_possible_writes or d.possible_entry_quantity is None
                    or d.state not in {"contingent", "open"}
                    or d.coverage not in {"verified_broker_held", "operator_accepted"}
                    or self.duty_state == "reconciliation_required"):
                raise ValueError("options_run_view")
        return self
