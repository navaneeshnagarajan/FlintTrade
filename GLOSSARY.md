# FlintTrade

FlintTrade brings trading, testing and learning into one product. These terms distinguish the tools people use from the ways they arrange them.

## Language

**App**:
A purpose-specific area within FlintTrade, such as Learn. Apps share the product but offer tools relevant to their purpose.
_Avoid_: Mode, persona

**Widget**:
A reusable trading, analysis or learning tool placed within a compatible app's layout.
_Avoid_: Layout, workspace

**Layout**:
A saved arrangement of widgets and their view settings. A layout does not grant trading permissions.
_Avoid_: Workspace, desk, persona

**Preset**:
A supplied layout that a person can use as-is or customise. A preset is a starting point, not a restriction on available features.
_Avoid_: Persona, feature tier

**Execution session**:
A scoped period of Live or paper trading, associated with a specific account or simulation ledger. Concurrent sessions do not share trading authority merely because they share an app.

**Trading permission**:
The user's time-limited authorisation for specified automated actions on specified accounts, within stated risk limits. Permission to open trades is distinct from a pre-authorised duty to close existing exposure.
_Avoid_: Always allow, unrestricted access

**Skill**:
A reusable procedure supplied to the AI, adapted from an existing procedure, or learned from checked experience. A skill is not a human experience level, a model weight update, or trading permission.
_Avoid_: Persona, feature tier

**Exit**:
An action that reduces or closes an existing position. Cancelling an unfilled order is a separate action and does not by itself close a position.

**Connection**:
An individually configured relationship with a broker, data source or model provider. Permissions belong to the individual connection; separate connections do not imply independent provider quota.
_Avoid_: Provider brand, trading account

**Model role**:
The purpose for which a model is used, such as request routing, reasoning, forecasting or admission classification. Suitability for one role does not establish suitability for another.

**Model routing**:
Selecting an eligible connection, model and supported effort setting for an AI task. It does not select a trading account or grant permission to execute a proposal.
_Avoid_: Order routing, failover

**Stock skill**:
A supplied baseline procedure with an identifiable version.

**Adapted skill**:
A procedure derived from a known stock or learned skill while retaining its source and changes.

**Retrieval**:
Finding relevant, permitted existing information for a task. Retrieval supplies context; it does not train model weights or establish trading authority.

**Model candidate**:
A proposed model version awaiting the evidence and authorisation required for its intended use. Training completion does not make it active.

**Run-pinned version**:
The specific procedure, strategy or model version assigned to a running activity. A change to the default version does not silently replace it.
