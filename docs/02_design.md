# Template Design Specification

## Position in AgentCore Architecture

- **Agent Class**: `CustomerContextQAAgent(AgentBaseGraph)` (alias: `Graph`)
- **L1 Base**: AgentBaseGraph (L1-direct — no L2 intermediary)
- **Three-Layer Separation**:
  - State: flat TypedDict composition (no Pydantic — msgpack incompatible)
  - Node: L1 inheritance (Template Method: `execute(self, state: dict) -> dict` override only)
  - Graph: composition (`register_nodes()` for node substitution)

## Architecture Overview

### Node Configuration

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| initialize | Framework lifecycle init | — | — | InitializeNode (default) |
| pre_process | S-1: sanitise `query_text`; validate `customer_id` format (reject email-pattern PII); cap query at 2048 chars; detect injection; emit `pre_process_start/complete` | `raw_input`, `customer_id`, `query_text` | `validated_input`, `customer_id_validated`, `status` | `PreProcessNode(FunctionNode)` — `_extra_security_gate_input()`: email-format customer_id rejection |
| main | GraphNode wrapper hosting inner `ContextWorkflowGraph` | `validated_input`, `customer_id`, `channel_id` | `intent`, `memory_chunks`, `cited_fields`, `answer`, `erasure_confirmed`, `erasure_audit_id`, `erasure_segments_deleted` | `ContextWorkflowGraphNode(GraphNode)` |
| post_process | S-3 PII redaction on `answer`; format final `result` JSON; write S-4 `audit_record`; emit `post_process_delivery` | `intent`, `answer`, `cited_fields`, `erasure_confirmed`, `erasure_audit_id`, `customer_id`, `channel_id` | `result`, `audit_record`, `status` | `PostProcessNode(FunctionNode)` — `_extra_security_gate_output()`: phone/email scan on answer |
| finalize | Framework lifecycle teardown | — | — | FinalizeNode (default) |

**Inner graph nodes** (inside `ContextWorkflowGraph(BaseGraph)`):

| Node | Responsibility | Input State | Output State | Inherits/Overrides |
|------|---------------|-------------|--------------|-------------------|
| `IntentClassifyNode` | LLM intent classification: `"qa"` / `"erasure"` / `"out_of_scope"`; keyword fallback; emit `intent_classify` | `validated_input` | `intent`, `status` | `FunctionNode` |
| `MemoryRetrieveNode` | Vector similarity search over per-`customer_id` Honcho/OpenViking store; top-k chunk retrieval; **per-customer isolation MANDATORY**; emit `memory_retrieve` | `validated_input`, `customer_id` | `memory_chunks`, `status` | `FunctionNode` — `required_trust_level = VERIFIED_EXTERNAL` |
| `RationaleGenerateNode` | LLM citation-only synthesis from `memory_chunks`; extract `cited_fields`; emit `rationale_generate` | `validated_input`, `memory_chunks` | `answer`, `cited_fields`, `status` | `FunctionNode` — `required_trust_level = VERIFIED_EXTERNAL` |
| `ErasureHandlerNode` | Re-validate `customer_id`; call idempotent hard-delete API; write tamper-evident audit record; emit `erasure_process` | `customer_id` | `erasure_confirmed`, `erasure_audit_id`, `erasure_segments_deleted`, `status` | `FunctionNode` — `required_trust_level = VERIFIED_EXTERNAL` |

**Intent classification fallback behaviour:**
When both LLM classification and keyword classification fail to determine
intent, the agent defaults to `"qa"` rather than `"out_of_scope"`.
This is intentional — it minimises false rejections for customers who ask
legitimate questions without using standard keywords. The Q&A branch handles
the empty-result case gracefully by returning
"No AI context is currently stored about you for this topic."

### Data Flow

```
Outer (CustomerContextQAAgent — AgentBaseGraph backbone):
  START → initialize → pre_process(PreProcessNode) → main(ContextWorkflowGraphNode) → post_process(PostProcessNode) → finalize → END
                                                              ↓ RETRY (max 3, backbone)
                                                           pre_process

Inner (ContextWorkflowGraph — BaseGraph with conditional branch):
  START → IntentClassifyNode
              ├─ intent="qa"           → MemoryRetrieveNode → RationaleGenerateNode → END
              ├─ intent="erasure"      → ErasureHandlerNode → END
              └─ intent="out_of_scope" → END (short-circuit; PostProcessNode returns scope notice)
```

### State Definition

| Field | Type | Purpose | Required |
|-------|------|---------|----------|
| `raw_input` | `str` | Raw invocation payload (JSON string or plain query) | ✅ |
| `customer_id` | `str` | Hashed/tokenised customer ID — NEVER raw PII (email, phone, name) | ✅ |
| `query_text` | `str` | Natural language question or erasure command | ✅ |
| `channel_id` | `Optional[str]` | Channel identifier for audit log (`"chat_app"`, `"call_centre"`) | Optional |
| `validated_input` | `str` | Sanitised query (set by PreProcessNode) | ✅ after pre_process |
| `customer_id_validated` | `bool` | Format validation result | ✅ after pre_process |
| `intent` | `str` | `"qa"` \| `"erasure"` \| `"out_of_scope"` | ✅ after IntentClassifyNode |
| `memory_chunks` | `List[dict]` | Retrieved chunks: `[{field, value, score, source, created_at}]`; Q&A branch only | Q&A branch |
| `cited_fields` | `List[str]` | Field names cited in `answer`; Q&A branch only | Q&A branch |
| `answer` | `str` | Plain-language explanation of stored context; Q&A branch only | Q&A branch |
| `erasure_confirmed` | `bool` | True if hard-delete API confirmed deletion | Erasure branch |
| `erasure_audit_id` | `Optional[str]` | Tamper-evident audit record ID from erasure API | Erasure branch |
| `erasure_segments_deleted` | `int` | Number of memory store segments deleted | Erasure branch |
| `result` | `str` | Final formatted JSON response string (set by PostProcessNode) | ✅ output |
| `status` | `str` | `"ok"` \| `"error"` \| `"blocked"` \| `"out_of_scope"` | ✅ |
| `audit_record` | `dict` | S-4 record: `{interaction_id, customer_id_hash, intent, timestamp, channel_id}` | ✅ S-4 |

**State Constraints (mandatory):**
- Flat TypedDict only (primitives + JSON-serializable types)
- No JWT, API keys, credentials in State (checkpoint DB leakage)
- InvocationContext via `InvocationContext.from_state(state)` only (not in State)
- No Pydantic models, dataclass, arbitrary Python objects (msgpack incompatible)
- `customer_id` MUST be hashed/tokenised — `PreProcessNode` raises `SecurityViolationError` on email-format input
- `memory_chunks` defaults to `[]` on Erasure/out_of_scope path; never populated cross-customer

## Framework Utilization

### Shared Components Used
- [x] InvocationContext (correlation_id, session_id, permissions, credential handle)
- [x] SecurityViolationError — raised by `PreProcessNode._extra_security_gate_input()` (email-format customer_id, injection, length) and `PostProcessNode._extra_security_gate_output()` (phone/email in answer)
- [x] S-2: `_extra_security_gate_input()` — `PreProcessNode`: reject `customer_id` matching email pattern; block injection strings; enforce 2048-char cap on `query_text`
- [x] S-3: `_extra_security_gate_output()` — `PostProcessNode` (**MANDATORY**): scan `answer` for phone numbers and email addresses; block delivery if PII detected
- [x] S-4: `emit_trace_event()` — domain events in every `execute()` body: `pre_process_start/complete`, `intent_classify`, `memory_retrieve`, `rationale_generate`, `erasure_process`, `post_process_delivery`; **do NOT emit** `node_start/complete/error` (framework emits automatically)

> **S-2/S-3 gate behaviour by node type (ADR-017):**
> - `FunctionNode` subclass → framework `@final` gate always runs automatically;
>   extend via `_extra_security_gate_input()` / `_extra_security_gate_output()` only
> - `GraphNode` / `RemoteAgentNode` → deliberate no-op (upstream or remote node's gate already applied)
> - Custom `BaseNode` subclass → must implement `_security_gate_input()` and
>   `_security_gate_output()` directly (`@abstractmethod` — omission raises `TypeError` at instantiation)

### Composition Pattern

- **Pattern**: GraphNode (subgraph)
- **Composition target**: `ContextWorkflowGraph(BaseGraph)` — inner 4-node conditional-branch topology
- **Error propagation strategy**: propagate — inner errors re-raised as SubgraphError to outer backbone

### LLM Construction and Injection

The standalone adapter keeps process-global LLM state unset. `IntentClassifyNode`
and `RationaleGenerateNode` resolve Azure OpenAI from invocation-scoped secrets.
Provider failures use deterministic safe fallbacks.

Customer scope crosses the `GraphNode` boundary through `input_context` while the
framework-required subgraph input remains a string. This preserves the hashed
`customer_id` without replacing the standard `BaseGraph.invoke()` contract.

## EU AI Act Art.13 Design-Time Evidence

Not applicable: `docs/01_proposal.md` declares this template outside Annex III.

## Import Isolation Confirmation
- [x] Template does not import agenticstar-platform SDK (Level 0)
- [x] Import targets: `framework/` and `shared/` only (no `agents/base/` required)

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| L1 base type | AgentBaseGraph | AutonomousBaseGraph | AgentBaseGraph | Deterministic intent-branch pipeline — no autonomous loop needed |
| Composition pattern | Standalone (FunctionNode only) | GraphNode (subgraph) | GraphNode | 4-node inner topology with conditional branch (qa/erasure/out_of_scope) requires BaseGraph encapsulation |
| Error propagation | handle (graceful degradation) | propagate (fail fast) | propagate | APPI erasure must never silently return partial confirmation; hard-delete errors must surface to caller |
| Memory store abstraction | Direct Honcho SDK calls in nodes | `MemoryStoreService` adapter | `MemoryStoreService` adapter | Decouples from the erasure-API delivery timeline; switch `"mock"` → `"honcho"` in config; enables isolated unit tests |
| customer_id isolation | Enforced by node logic | Enforced at `MemoryStoreService.search()` | Both layers | Defense-in-depth: `MemoryRetrieveNode` passes `customer_id` as mandatory arg; `MemoryStoreService` enforces partition |
| Trust level | ANONYMOUS | VERIFIED_EXTERNAL | VERIFIED_EXTERNAL | Customer personal preference data; anonymous callers not permitted on `MemoryRetrieveNode`, `RationaleGenerateNode`, `ErasureHandlerNode` |
