from __future__ import annotations

from sqlglot import exp
from sqlglot.generator import Generator
from sqlglot.generators.postgres import PostgresGenerator


class RisingWaveGenerator(PostgresGenerator):
    LOCKING_READS_SUPPORTED = False
    SUPPORTS_BETWEEN_FLAGS = False

    TRANSFORMS = {
        **PostgresGenerator.TRANSFORMS,
        exp.FileFormatProperty: lambda self, e: f"FORMAT {self.sql(e, 'this')}",
    }

    PROPERTIES_LOCATION = {
        **PostgresGenerator.PROPERTIES_LOCATION,
        exp.FileFormatProperty: exp.Properties.Location.POST_EXPRESSION,
    }

    EXPRESSION_PRECEDES_PROPERTIES_CREATABLES = {"SINK"}

    def computedcolumnconstraint_sql(self, expression: exp.ComputedColumnConstraint) -> str:
        pass

    def datatype_sql(self, expression: exp.DataType) -> str:
        pass
