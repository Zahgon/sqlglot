from __future__ import annotations


from sqlglot import exp
from sqlglot import generator
from sqlglot.dialects.dialect import (
    array_append_sql,
    rename_func,
    unit_to_var,
    timestampdiff_sql,
    date_delta_to_binary_interval_op,
    groupconcat_sql,
)
from sqlglot.generators.spark2 import Spark2Generator, temporary_storage_provider
from sqlglot.helper import seq_get
from sqlglot.transforms import (
    ctas_with_tmp_tables_to_create_tmp_view,
    remove_unique_constraints,
    preprocess,
    move_partitioned_by_to_schema_columns,
)


def _normalize_partition(e: exp.Expr) -> exp.Expr:
    """Normalize the expressions in PARTITION BY (<expression>, <expression>, ...)"""
    if isinstance(e, str):
        return exp.to_identifier(e)
    if isinstance(e, exp.Literal):
        return exp.to_identifier(e.name)
    return e


def _dateadd_sql(self: SparkGenerator, expression: exp.TsOrDsAdd | exp.TimestampAdd) -> str:
    pass


def _groupconcat_sql(self: SparkGenerator, expression: exp.GroupConcat) -> str:
    pass


class SparkGenerator(Spark2Generator):
    SUPPORTS_TO_NUMBER = True
    PAD_FILL_PATTERN_IS_REQUIRED = False
    SUPPORTS_CONVERT_TIMEZONE = True
    SUPPORTS_MEDIAN = True
    SUPPORTS_UNIX_SECONDS = True
    SUPPORTS_DECODE_CASE = True
    SET_ASSIGNMENT_REQUIRES_VARIABLE_KEYWORD = True

    TYPE_MAPPING = {
        **Spark2Generator.TYPE_MAPPING,
        exp.DType.MONEY: "DECIMAL(15, 4)",
        exp.DType.SMALLMONEY: "DECIMAL(6, 4)",
        exp.DType.UUID: "STRING",
        exp.DType.TIMESTAMPLTZ: "TIMESTAMP_LTZ",
        exp.DType.TIMESTAMPNTZ: "TIMESTAMP_NTZ",
    }

    TRANSFORMS = {
        k: v
        for k, v in {
            **Spark2Generator.TRANSFORMS,
            exp.ArrayConstructCompact: lambda self, e: self.func(
                "ARRAY_COMPACT", self.func("ARRAY", *e.expressions)
            ),
            exp.ArrayInsert: lambda self, e: self.func(
                "ARRAY_INSERT", e.this, e.args.get("position"), e.expression
            ),
            exp.ArrayAppend: array_append_sql("ARRAY_APPEND"),
            exp.ArrayPrepend: array_append_sql("ARRAY_PREPEND"),
            exp.BitwiseAndAgg: rename_func("BIT_AND"),
            exp.BitwiseOrAgg: rename_func("BIT_OR"),
            exp.BitwiseXorAgg: rename_func("BIT_XOR"),
            exp.BitwiseCount: rename_func("BIT_COUNT"),
            exp.Create: preprocess(
                [
                    remove_unique_constraints,
                    lambda e: ctas_with_tmp_tables_to_create_tmp_view(
                        e, temporary_storage_provider
                    ),
                    move_partitioned_by_to_schema_columns,
                ]
            ),
            exp.CurrentVersion: rename_func("VERSION"),
            exp.DateFromUnixDate: rename_func("DATE_FROM_UNIX_DATE"),
            exp.DatetimeAdd: date_delta_to_binary_interval_op(cast=False),
            exp.DatetimeSub: date_delta_to_binary_interval_op(cast=False),
            exp.GroupConcat: _groupconcat_sql,
            exp.EndsWith: rename_func("ENDSWITH"),
            exp.JSONKeys: rename_func("JSON_OBJECT_KEYS"),
            exp.PartitionedByProperty: lambda self, e: (
                f"PARTITIONED BY {self.wrap(self.expressions(sqls=[_normalize_partition(e) for e in e.this.expressions], skip_first=True))}"
            ),
            exp.SafeAdd: rename_func("TRY_ADD"),
            exp.SafeDivide: rename_func("TRY_DIVIDE"),
            exp.SafeMultiply: rename_func("TRY_MULTIPLY"),
            exp.SafeSubtract: rename_func("TRY_SUBTRACT"),
            exp.StartsWith: rename_func("STARTSWITH"),
            exp.TimeAdd: date_delta_to_binary_interval_op(cast=False),
            exp.TimeSub: date_delta_to_binary_interval_op(cast=False),
            exp.TsOrDsAdd: _dateadd_sql,
            exp.TimestampAdd: _dateadd_sql,
            exp.TimestampFromParts: rename_func("MAKE_TIMESTAMP"),
            exp.TimestampSub: date_delta_to_binary_interval_op(cast=False),
            exp.DatetimeDiff: timestampdiff_sql,
            exp.TimestampDiff: timestampdiff_sql,
            exp.TryCast: lambda self, e: (
                self.trycast_sql(e) if e.args.get("safe") else self.cast_sql(e)
            ),
            exp.AnyValue: None,
            exp.DateDiff: None,
            exp.With: None,
        }.items()
        if v is not None
    }

    def ignorenulls_sql(self, expression: exp.IgnoreNulls) -> str:
        pass

    def bracket_sql(self, expression: exp.Bracket) -> str:
        pass

    def computedcolumnconstraint_sql(self, expression: exp.ComputedColumnConstraint) -> str:
        pass

    def anyvalue_sql(self, expression: exp.AnyValue) -> str:
        pass

    def datediff_sql(self, expression: exp.DateDiff) -> str:
        pass

    def placeholder_sql(self, expression: exp.Placeholder) -> str:
        pass

    def readparquet_sql(self, expression: exp.ReadParquet) -> str:
        pass

    def ifblock_sql(self, expression: exp.IfBlock) -> str:
        pass
