"""Structured output schema for Z3 DSL generation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SortDefinition(BaseModel):
    """Definition of a sort in the DSL."""

    name: str
    type: str
    values: Optional[List[str]] = None
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class FunctionDefinition(BaseModel):
    """Definition of a function in the DSL."""

    name: str
    domain: List[str]
    range: str
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class VariableDefinition(BaseModel):
    """Definition of a variable available to the DSL program."""

    name: str
    sort: str
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class KnowledgeAssertion(BaseModel):
    """Knowledge base entry with an explicit truth value."""

    assertion: str
    value: bool = True
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


KnowledgeEntry = Union[str, KnowledgeAssertion]


class QuantifiedVariable(BaseModel):
    """Variable definition used in quantifiers."""

    name: str
    sort: str

    model_config = ConfigDict(extra="forbid")


class RuleImplication(BaseModel):
    """Implication used inside rules."""

    antecedent: str
    consequent: str

    model_config = ConfigDict(extra="forbid")


class RuleDefinition(BaseModel):
    """Logical rule definition."""

    name: Optional[str] = None
    forall: Optional[List[QuantifiedVariable]] = None
    implies: Optional[RuleImplication] = None
    constraint: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class VerificationImplication(BaseModel):
    """Implication used for universal verifications."""

    antecedent: str
    consequent: str

    model_config = ConfigDict(extra="forbid")


class VerificationDefinition(BaseModel):
    """Definition of a verification condition."""

    name: Optional[str] = None
    constraint: Optional[str] = None
    exists: Optional[List[QuantifiedVariable]] = None
    forall: Optional[List[QuantifiedVariable]] = None
    implies: Optional[VerificationImplication] = None
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class ObjectiveDefinition(BaseModel):
    """Optimization objective."""

    type: Literal["maximize", "minimize"]
    expression: str

    model_config = ConfigDict(extra="forbid")


class OptimizationConfig(BaseModel):
    """Optimization configuration."""

    variables: List[VariableDefinition] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    objectives: List[ObjectiveDefinition] = Field(default_factory=list)
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class ConstantDefinition(BaseModel):
    """Definition of a named constant group."""

    sort: str
    members: Union[List[str], Dict[str, str]]
    description: Optional[str] = None

    model_config = ConfigDict(extra="forbid")


class StructuredProgram(BaseModel):
    """Structured representation of a Z3 DSL program."""

    sorts: List[SortDefinition] = Field(default_factory=list)
    functions: List[FunctionDefinition] = Field(default_factory=list)
    constants: Dict[str, ConstantDefinition] = Field(default_factory=dict)
    variables: List[VariableDefinition] = Field(default_factory=list)
    knowledge_base: List[KnowledgeEntry] = Field(default_factory=list)
    rules: List[RuleDefinition] = Field(default_factory=list)
    verifications: List[VerificationDefinition] = Field(default_factory=list)
    optimization: Optional[OptimizationConfig] = None
    actions: List[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")

    def to_dsl_dict(self) -> Dict[str, Any]:
        """Convert structured program into the interpreter JSON format."""

        def dump_model(obj: BaseModel) -> Dict[str, Any]:
            return obj.model_dump(mode="python", exclude_none=True)

        sorts_data = [dump_model(sort) for sort in self.sorts]
        functions_data = [dump_model(func) for func in self.functions]
        variables_data = [dump_model(var) for var in self.variables]

        knowledge_entries: List[Any] = []
        for entry in self.knowledge_base:
            if isinstance(entry, BaseModel):
                knowledge_entries.append(dump_model(entry))
            else:
                knowledge_entries.append(entry)

        rules_data = [dump_model(rule) for rule in self.rules]
        verifications_data = [dump_model(verification) for verification in self.verifications]

        actions = list(self.actions) if self.actions else ["verify_conditions"]

        program: Dict[str, Any] = {
            "sorts": sorts_data,
            "functions": functions_data,
            "constants": {
                name: dump_model(constant)
                for name, constant in self.constants.items()
            },
            "variables": variables_data,
            "knowledge_base": knowledge_entries,
            "rules": rules_data,
            "verifications": verifications_data,
            "actions": actions,
        }

        if self.optimization:
            program["optimization"] = dump_model(self.optimization)

        return program


__all__ = [
    "ConstantDefinition",
    "FunctionDefinition",
    "KnowledgeAssertion",
    "KnowledgeEntry",
    "OptimizationConfig",
    "ObjectiveDefinition",
    "QuantifiedVariable",
    "RuleDefinition",
    "RuleImplication",
    "SortDefinition",
    "StructuredProgram",
    "VariableDefinition",
    "VerificationDefinition",
    "VerificationImplication",
]
