from __future__ import annotations

import math
import typing as t

from sqlglot import alias, exp
from sqlglot.helper import name_sequence
from sqlglot.optimizer.eliminate_joins import join_condition
from collections.abc import Iterator, Sequence, Iterable


class Plan:
    def __init__(self, expression: exp.Expr) -> None:
        self.expression = expression.copy()
        self.root = Step.from_expression(self.expression)
        self._dag: dict[Step, set[Step]] = {}

    @property
    def dag(self) -> dict[Step, set[Step]]:
        pass

    @property
    def leaves(self) -> Iterator[Step]:
        pass

    def __repr__(self) -> str:
        return f"Plan\n----\n{repr(self.root)}"


class Step:
    @classmethod
    def from_expression(cls, expression: exp.Expr, ctes: dict[str, Step] | None = None) -> Step:
        """
        Builds a DAG of Steps from a SQL expression so that it's easier to execute in an engine.
        Note: the expression's tables and subqueries must be aliased for this method to work. For
        example, given the following expression:

        SELECT
          x.a,
          SUM(x.b)
        FROM x AS x
        JOIN y AS y
          ON x.a = y.a
        GROUP BY x.a

        the following DAG is produced (the expression IDs might differ per execution):

        - Aggregate: x (4347984624)
            Context:
              Aggregations:
                - SUM(x.b)
              Group:
                - x.a
            Projections:
              - x.a
              - "x".""
            Dependencies:
            - Join: x (4347985296)
              Context:
                y:
                On: x.a = y.a
              Projections:
              Dependencies:
              - Scan: x (4347983136)
                Context:
                  Source: x AS x
                Projections:
              - Scan: y (4343416624)
                Context:
                  Source: y AS y
                Projections:

        Args:
            expression: the expression to build the DAG from.
            ctes: a dictionary that maps CTEs to their corresponding Step DAG by name.

        Returns:
            A Step DAG corresponding to `expression`.
        """
        pass

    def __init__(self) -> None:
        self.name: str | None = None
        self.dependencies: set[Step] = set()
        self.dependents: set[Step] = set()
        self.projections: Sequence[exp.Expr] = []
        self.limit: float = math.inf
        self.condition: exp.Expr | None = None

    def add_dependency(self, dependency: Step) -> None:
        pass

    def __repr__(self) -> str:
        return self.to_s()

    def to_s(self, level: int = 0) -> str:
        pass

    @property
    def type_name(self) -> str:
        pass

    @property
    def id(self) -> str:
        pass

    def _to_s(self, _indent: str) -> list[str]:
        return []


class Scan(Step):
    @classmethod
    def from_expression(cls, expression: exp.Expr, ctes: dict[str, Step] | None = None) -> Step:
        pass

    def __init__(self) -> None:
        super().__init__()
        self.source: exp.Expr | None = None

    def _to_s(self, indent: str) -> list[str]:
        return [f"{indent}Source: {self.source.sql() if self.source else '-static-'}"]  # type: ignore


class Join(Step):
    @classmethod
    def from_joins(cls, joins: Iterable[exp.Join], ctes: dict[str, Step] | None = None) -> Join:
        pass

    def __init__(self) -> None:
        super().__init__()
        self.source_name: str | None = None
        self.joins: dict[str, dict[str, list[str] | exp.Expr]] = {}

    def _to_s(self, indent: str) -> list[str]:
        lines = [f"{indent}Source: {self.source_name or self.name}"]
        for name, join in self.joins.items():
            lines.append(f"{indent}{name}: {join['side'] or 'INNER'}")
            join_key = ", ".join(str(key) for key in t.cast(list, join.get("join_key") or []))
            if join_key:
                lines.append(f"{indent}Key: {join_key}")
            if join.get("condition"):
                lines.append(f"{indent}On: {join['condition'].sql()}")  # type: ignore
        return lines


class Aggregate(Step):
    def __init__(self) -> None:
        super().__init__()
        self.aggregations: list[exp.Expr] = []
        self.operands: tuple[exp.Expr, ...] = ()
        self.group: dict[str, exp.Expr] = {}
        self.source: str | None = None

    def _to_s(self, indent: str) -> list[str]:
        lines = [f"{indent}Aggregations:"]

        for expression in self.aggregations:
            lines.append(f"{indent}  - {expression.sql()}")

        if self.group:
            lines.append(f"{indent}Group:")
            for expression in self.group.values():
                lines.append(f"{indent}  - {expression.sql()}")
        if self.condition:
            lines.append(f"{indent}Having:")
            lines.append(f"{indent}  - {self.condition.sql()}")
        if self.operands:
            lines.append(f"{indent}Operands:")
            for expression in self.operands:
                lines.append(f"{indent}  - {expression.sql()}")

        return lines


class Sort(Step):
    def __init__(self) -> None:
        super().__init__()
        self.key = None

    def _to_s(self, indent: str) -> list[str]:
        lines = [f"{indent}Key:"]

        for expression in self.key:  # type: ignore
            lines.append(f"{indent}  - {expression.sql()}")

        return lines


class SetOperation(Step):
    def __init__(
        self,
        op: type[exp.Expr],
        left: str | None,
        right: str | None,
        distinct: bool = False,
    ) -> None:
        super().__init__()
        self.op = op
        self.left = left
        self.right = right
        self.distinct = distinct

    @classmethod
    def from_expression(
        cls, expression: exp.Expr, ctes: dict[str, Step] | None = None
    ) -> SetOperation:
        pass

    def _to_s(self, indent: str) -> list[str]:
        lines = []
        if self.distinct:
            lines.append(f"{indent}Distinct: {self.distinct}")
        return lines

    @property
    def type_name(self) -> str:
        pass
