"""PB-6: verify the framework-controlled node invocation order."""

import importlib
import inspect
import pkgutil
from typing import ClassVar

from framework.nodes.base_node import BaseNode
from framework.schemas.trust_level import TrustLevel


class _PrivilegedTrustGateFixture(BaseNode):
    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def _security_gate_input(self, state):
        return state

    def execute(self, state):
        return {"status": "success"}

    def _security_gate_output(self, result):
        return result


def _discover_node_classes() -> list[type]:
    pkg = importlib.import_module("src.nodes")
    discovered: list[type] = []
    for _, modname, _ in pkgutil.walk_packages(pkg.__path__, prefix="src.nodes."):
        module = importlib.import_module(modname)
        for attr in vars(module).values():
            if (
                isinstance(attr, type)
                and issubclass(attr, BaseNode)
                and attr is not BaseNode
                and attr.__module__ == modname
                and not inspect.isabstract(attr)
            ):
                discovered.append(attr)
    return discovered


def _valid_state(trust: TrustLevel) -> dict:
    return {
        "caller_trust_level": trust.value,
        "correlation_id": "pb6-invoke-order-test",
        "user_input": "What preferences are stored about me?",
        "raw_input": "What preferences are stored about me?",
        "validated_input": "What preferences are stored about me?",
        "input_context": {"customer_id": "cust_hash_pb6", "channel_id": "test"},
        "customer_id": "cust_hash_pb6",
        "channel_id": "test",
        "intent": "qa",
        "memory_chunks": [],
        "cited_fields": [],
        "answer": "No AI context is currently stored about you for this topic.",
        "erasure_confirmed": False,
        "erasure_segments_deleted": 0,
        "status": "success",
        "node_history": [],
        "error_log": [],
    }


class TestInvokeOrder:
    def test_s1_denial_refuses_execution_before_execute(self, monkeypatch):
        import framework.nodes.base_node as base_node_module

        events: list[str] = []
        execute_calls: list[object] = []
        monkeypatch.setattr(
            base_node_module,
            "emit_trace_event",
            lambda event_type, _payload, _state: events.append(event_type),
        )
        original_execute = _PrivilegedTrustGateFixture.execute

        def spy_execute(self, state):
            execute_calls.append(state)
            return original_execute(self, state)

        monkeypatch.setattr(_PrivilegedTrustGateFixture, "execute", spy_execute)
        result = _PrivilegedTrustGateFixture()(
            {"caller_trust_level": TrustLevel.ANONYMOUS.value, "correlation_id": "tc08-s1-denial"}
        )

        assert result["status"] == "error"
        assert "S-1 trust gate denied" in result["error_log"][0]
        assert events == ["s1_denied"]
        assert not execute_calls

    def test_call_order_for_every_node(self, monkeypatch):
        import framework.nodes.base_node as base_node_module

        failures: list[str] = []
        for node_cls in _discover_node_classes():
            order: list[str] = []
            monkeypatch.setattr(
                base_node_module,
                "emit_trace_event",
                lambda event_type, _payload, _state, _o=order: _o.append(f"event:{event_type}"),
            )
            for method_name, label in (
                ("_security_gate_input", "security_gate_input"),
                ("execute", "execute"),
                ("_security_gate_output", "security_gate_output"),
            ):
                original = getattr(node_cls, method_name)

                def spy(self, arg, _o=order, _label=label, _orig=original):
                    _o.append(_label)
                    return _orig(self, arg)

                monkeypatch.setattr(node_cls, method_name, spy)

            node_cls()(_valid_state(node_cls.required_trust_level))
            expected = [
                "event:node_start",
                "security_gate_input",
                "execute",
                "security_gate_output",
                "event:node_complete",
            ]
            if order != expected:
                failures.append(f"{node_cls.__name__}: expected {expected}, actual {order}")

        assert not failures, "\n".join(failures)
