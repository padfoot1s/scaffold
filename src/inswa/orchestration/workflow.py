"""The orchestrator's steps as an Agent Framework workflow graph.

intent -> scope --(out_of_scope | not_enabled)--> reject
                --(proceed)--> slots --(missing)--> follow_up
                                     --(complete)--> delegate -> compose
"""

from agent_framework import Case, Default, Workflow, WorkflowBuilder

from inswa.orchestration.executors import (
    ComposeExecutor,
    DelegateExecutor,
    FollowUpExecutor,
    IntentExecutor,
    RejectExecutor,
    ScopeExecutor,
    SlotExecutor,
)
from inswa.runtime import Runtime


def build_workflow(runtime: Runtime) -> Workflow:
    """Build a fresh workflow graph (executors hold per-run state; build one per request)."""
    intent = IntentExecutor(runtime)
    scope = ScopeExecutor(runtime)
    slots = SlotExecutor(runtime)
    follow_up = FollowUpExecutor(runtime)
    reject = RejectExecutor(runtime)
    delegate = DelegateExecutor(runtime)
    compose = ComposeExecutor(runtime)

    return (
        WorkflowBuilder(
            name="inswa-orchestrator",
            description="Intent, scope, slot check, delegation and grounded composition.",
            start_executor=intent,
        )
        .add_edge(intent, scope)
        .add_switch_case_edge_group(
            scope,
            [Case(condition=lambda s: s.route == "proceed", target=slots), Default(target=reject)],
        )
        .add_switch_case_edge_group(
            slots,
            [Case(condition=lambda s: s.route == "follow_up", target=follow_up), Default(target=delegate)],
        )
        .add_edge(delegate, compose)
        .build()
    )
