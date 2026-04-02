"""Staged SMT2 backend module."""

from z3adapter.backends.smt2.backend import StagedSMT2Backend
from z3adapter.backends.smt2.emitter import ExpressionEmitter, emit_smt2_expr
from z3adapter.backends.smt2.generator import (
    GenerationResult,
    GenerationStage,
    STAGE_ORDER,
    SimpleLLMClient,
    StagedGenerator,
)
from z3adapter.backends.smt2.ir import (
    ConversionContext,
    SMTAssertion,
    SMTConstant,
    SMTFunction,
    SMTQuery,
    SMTSort,
    SMTSortKind,
)
from z3adapter.backends.smt2.parser import (
    ExecutionResult,
    ModelValue,
    SMTQueryResult,
    Z3OutputParser,
)
from z3adapter.backends.smt2.prompts import (
    format_constants_prompt,
    format_full_context,
    format_functions_prompt,
    format_kb_prompt,
    format_query_prompt,
    format_scenario_prompt,
    format_sorts_prompt,
    format_world_model_smt,
)
from z3adapter.backends.smt2.stages import (
    ConstantsStage,
    FunctionsStage,
    KnowledgeBaseStage,
    LogicStage,
    Pipeline,
    PipelineStage,
    RulesStage,
    SortsStage,
    VariablesStage,
    VerificationsStage,
)

__all__ = [
    # Backend
    "StagedSMT2Backend",
    # Generator (LLM integration)
    "StagedGenerator",
    "GenerationResult",
    "GenerationStage",
    "STAGE_ORDER",
    "SimpleLLMClient",
    # Prompts
    "format_sorts_prompt",
    "format_functions_prompt",
    "format_constants_prompt",
    "format_kb_prompt",
    "format_scenario_prompt",
    "format_query_prompt",
    "format_full_context",
    "format_world_model_smt",
    # IR
    "ConversionContext",
    "SMTSort",
    "SMTSortKind",
    "SMTFunction",
    "SMTConstant",
    "SMTAssertion",
    "SMTQuery",
    # Stages
    "Pipeline",
    "PipelineStage",
    "LogicStage",
    "SortsStage",
    "FunctionsStage",
    "ConstantsStage",
    "VariablesStage",
    "KnowledgeBaseStage",
    "RulesStage",
    "VerificationsStage",
    # Emitter
    "ExpressionEmitter",
    "emit_smt2_expr",
    # Parser
    "Z3OutputParser",
    "ExecutionResult",
    "SMTQueryResult",
    "ModelValue",
]
