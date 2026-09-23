# Test Specification

## Test Strategy
- Coverage target: 80%+ (100% of S-3 security-critical paths and APPI erasure path)
- Test types: Unit / Integration / Proof-of-Boundary

## Framework Compliance Tests (Mandatory)

| TC-ID | Test | Expected Result | Result |
|-------|------|----------------|--------|
| TC-01 | State contract: flat TypedDict | `State` has `__annotations__`; no `__fields__`; no `__dataclass_fields__` | |
| TC-02 | SecurityViolationError fires on invalid input | `customer_id="user@example.com"` → `SecurityViolationError`; query >2048 chars → `SecurityViolationError`; injection pattern → `SecurityViolationError` | |
| TC-03 | No JWT/Credential in State | CI `gate-credential-scan`: 0 violations (S-5 enforcement is performed in CI) | |
| TC-04 | InvocationContext reconstructed at graph boundary | `InvocationContext.from_state(state)` used by `ContextWorkflowGraphNode`; no context object stored in State | Pass |
| TC-05 | S-4: no duplicate lifecycle events in `execute()` | `node_start` / `node_complete` / `node_error` absent from `execute()` body across all 6 nodes | 0 duplicates |
| TC-06 | S-2: `_security_gate_input()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-07 | S-3: `_security_gate_output()` not overridden (`FunctionNode` subclass) | `TypeError` raised at class definition if overridden (`@final` enforced by framework) | 0 overrides |
| TC-08 | `required_trust_level` enforced | `VERIFIED_EXTERNAL` on `MemoryRetrieveNode`, `RationaleGenerateNode`, `ErasureHandlerNode`; insufficient trust → refused | |
| TC-09 | S-2: `_extra_security_gate_input()` non-trivial (`PreProcessNode`) | Email-format `customer_id` rejection + injection detection + 2048-char cap all execute correctly | Hook body non-trivial |
| TC-10 | S-3: `_extra_security_gate_output()` non-trivial (`PostProcessNode`) | Phone number and email scan on `answer` executes correctly; PII in output → blocked | Hook body non-trivial |
| TC-11 | S-4: at least one domain `emit_trace_event()` inside each `execute()` | Domain event emitted on every invocation path across all 6 nodes | ≥1 per node |

## Proof-of-Boundary Tests (Mandatory)

| PB-ID | Boundary | Test | Expected Result | Result |
|-------|----------|------|----------------|--------|
| PB-1 | BaseNode → EventEmitter | `emit_trace_event()` fires on all 6 nodes on all invocation paths (monkeypatch capture) | ≥1 `emit_trace_event` call per node | |
| PB-2 | State serialization | Post-invoke State — `json.dumps(sample_state)` does not raise | All values are str/bool/int/list/dict of primitives | |
| PB-3 | Level 2 → External service | `MemoryRetrieveNode` + `ErasureHandlerNode` with mock services (inject via constructor) | Data retrieved / deletion confirmed with no live dependency | |
| PB-4 | Import isolation | AST scan of `src/` — no `agenticstar-platform` imports | AST scan: 0 violations | |
| PB-5 | Checkpoint safety | `memory_chunks` and `erasure_audit_id` contain only primitives; no credentials in checkpoint | Inspection pass | |
| PB-6 | Invoke execution order | `__call__()`: S-1 trust gate → S-4 `node_start` → S-2 `_security_gate_input` → `execute()` → S-3 `_security_gate_output` → S-4 `node_complete` | Order verified | |
| PB-7 | HITL interrupt propagation | Conditional on `config/config.yaml hitl.enabled`; currently auto-waived because HITL is disabled | 2 skipped | |
| PB-8 | Azure LLM runtime | Verify invocation secrets reach both LLM nodes and provider failure falls back safely | Invocation isolation and fallback preserved | |

## Business Logic Tests

| TC-ID | Test | Input | Expected Result | Result |
|-------|------|-------|----------------|--------|
| BL-01 | Q&A intent correctly classified | `"Does your system know I am lactose intolerant?"` | `intent == "qa"` | |
| BL-02 | Erasure intent correctly classified (English) | `"Delete all my stored preferences"` | `intent == "erasure"` | |
| BL-03 | Erasure intent correctly classified (Japanese) | `"個人情報を削除してください"` | `intent == "erasure"` | |
| BL-04 | Out-of-scope intent — short-circuit | `"What is my loyalty point balance?"` | `intent == "out_of_scope"`, `result` contains scope notice, `MemoryRetrieveNode` NOT called | |
| BL-05 | Memory retrieval scoped to `customer_id` | Two mock invocations: `customer_id="cust_AAAA"` and `"cust_BBBB"` | Customer A chunks have `customer_id="cust_AAAA"`; zero chunk crossover to Customer B | |
| BL-06 | Citation-only answer — no hallucination | `memory_chunks=[{field: "dietary_restrictions", value: "lactose intolerant", ...}]` | All `cited_fields` appear in `memory_chunks`; no invented field names | |
| BL-07 | Erasure handler confirms deletion | Mock erasure API returns `{status: "deleted", segments_deleted: 5, erasure_id: "era_abc"}` | `erasure_confirmed=True`, `erasure_audit_id` present, `erasure_segments_deleted == 5` | |
| BL-08 | Erasure handler graceful API failure | Mock erasure API raises `RuntimeError` | `erasure_confirmed=False`, `status == "error"`, no unhandled exception | |
| BL-09 | S-3 gate — PII in answer → PostProcessNode blocks | `answer` containing `"user@example.com"` | `SecurityViolationError` raised; `result` NOT delivered | |
| BL-10 | execute() contract — all 6 nodes | Inspect each node class | `execute` defined; `state` is 2nd param; `_invoke_impl` not in `__dict__` | |

## Test Execution Summary
- Execution date: 2026-08-18
- Total tests: 74
- Pass: 70 / Fail: 0 / Skip: 4 (PB-5/PB-7 and optional provider conditions)
- Coverage: Not measured by the requested local run
