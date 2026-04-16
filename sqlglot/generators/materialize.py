from __future__ import annotations

from sqlglot import exp
from sqlglot.helper import seq_get
from sqlglot.generators.postgres import PostgresGenerator

from sqlglot.transforms import (
    remove_unique_constraints,
    ctas_with_tmp_tables_to_create_tmp_view,
    preprocess,
)


class MaterializeGenerator(PostgresGenerator):
    SUPPORTS_CREATE_TABLE_LIKE = False
    SUPPORTS_BETWEEN_FLAGS = False

    TRANSFORMS = {
        **{k: v for k, v in PostgresGenerator.TRANSFORMS.items() if k != exp.ToMap},
        exp.AutoIncrementColumnConstraint: lambda self, e: "",
        exp.Create: preprocess(
            [
                remove_unique_constraints,
                ctas_with_tmp_tables_to_create_tmp_view,
            ]
        ),
        exp.GeneratedAsIdentityColumnConstraint: lambda self, e: "",
        exp.OnConflict: lambda self, e: "",
        exp.PrimaryKeyColumnConstraint: lambda self, e: "",
    }

    def propertyeq_sql(self, expression: exp.PropertyEQ) -> str:
        pass

    def datatype_sql(self, expression: exp.DataType) -> str:
        pass

    def list_sql(self, expression: exp.List) -> str:
        pass

    def tomap_sql(self, expression: exp.ToMap) -> str:
        pass
