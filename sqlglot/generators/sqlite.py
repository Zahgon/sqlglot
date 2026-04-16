from __future__ import annotations

import typing as t

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    any_value_to_max_sql,
    arrow_json_extract_sql,
    concat_to_dpipe_sql,
    count_if_to_sum,
    no_ilike_sql,
    no_pivot_sql,
    no_tablesample_sql,
    no_trycast_sql,
    rename_func,
    strposition_sql,
)
from sqlglot.generator import unsupported_args
from sqlglot.tokens import TokenType


def _transform_create(expression: exp.Expr) -> exp.Expr:
    """Move primary key to a column and enforce auto_increment on primary keys."""
    pass


def _generated_to_auto_increment(expression: exp.Expr) -> exp.Expr:
    pass


class SQLiteGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    JOIN_HINTS = False
    TABLE_HINTS = False
    QUERY_HINTS = False
    NVL2_SUPPORTED = False
    JSON_PATH_BRACKETED_KEY_SUPPORTED = False
    SUPPORTS_CREATE_TABLE_LIKE = False
    SUPPORTS_TABLE_ALIAS_COLUMNS = False
    SUPPORTS_TO_NUMBER = False
    SUPPORTS_WINDOW_EXCLUDE = True
    EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE = False
    SUPPORTS_MEDIAN = False
    JSON_KEY_VALUE_PAIR_SEP = ","
    PARSE_JSON_NAME: str | None = None

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
    }

    TYPE_MAPPING = {
        **{k: v for k, v in generator.Generator.TYPE_MAPPING.items() if k != exp.DType.BLOB},
        exp.DType.BOOLEAN: "INTEGER",
        exp.DType.TINYINT: "INTEGER",
        exp.DType.SMALLINT: "INTEGER",
        exp.DType.INT: "INTEGER",
        exp.DType.BIGINT: "INTEGER",
        exp.DType.FLOAT: "REAL",
        exp.DType.DOUBLE: "REAL",
        exp.DType.DECIMAL: "REAL",
        exp.DType.CHAR: "TEXT",
        exp.DType.NCHAR: "TEXT",
        exp.DType.VARCHAR: "TEXT",
        exp.DType.NVARCHAR: "TEXT",
        exp.DType.BINARY: "BLOB",
        exp.DType.VARBINARY: "BLOB",
    }

    TOKEN_MAPPING = {
        TokenType.AUTO_INCREMENT: "AUTOINCREMENT",
    }

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.AnyValue: any_value_to_max_sql,
        exp.Chr: rename_func("CHAR"),
        exp.Concat: concat_to_dpipe_sql,
        exp.CountIf: count_if_to_sum,
        exp.Create: transforms.preprocess([_transform_create]),
        exp.CurrentDate: lambda *_: "CURRENT_DATE",
        exp.CurrentTime: lambda *_: "CURRENT_TIME",
        exp.CurrentTimestamp: lambda *_: "CURRENT_TIMESTAMP",
        exp.CurrentVersion: lambda *_: "SQLITE_VERSION()",
        exp.ColumnDef: transforms.preprocess([_generated_to_auto_increment]),
        exp.DateStrToDate: lambda self, e: self.sql(e, "this"),
        exp.If: rename_func("IIF"),
        exp.ILike: no_ilike_sql,
        exp.JSONArrayAgg: unsupported_args("order", "null_handling", "return_type", "strict")(
            rename_func("JSON_GROUP_ARRAY")
        ),
        exp.JSONExtractScalar: arrow_json_extract_sql,
        exp.JSONObjectAgg: lambda self, e: self._jsonobject_sql(e, name="JSON_GROUP_OBJECT"),
        exp.Levenshtein: unsupported_args("ins_cost", "del_cost", "sub_cost", "max_dist")(
            rename_func("EDITDIST3")
        ),
        exp.LogicalOr: rename_func("MAX"),
        exp.LogicalAnd: rename_func("MIN"),
        exp.Pivot: no_pivot_sql,
        exp.Rand: rename_func("RANDOM"),
        exp.Select: transforms.preprocess(
            [
                transforms.eliminate_distinct_on,
                transforms.eliminate_qualify,
                transforms.eliminate_semi_and_anti_joins,
            ]
        ),
        exp.StrPosition: lambda self, e: strposition_sql(self, e, func_name="INSTR"),
        exp.TableSample: no_tablesample_sql,
        exp.TimeStrToTime: lambda self, e: self.sql(e, "this"),
        exp.TimeToStr: lambda self, e: self.func("STRFTIME", e.args.get("format"), e.this),
        exp.TryCast: no_trycast_sql,
        exp.TsOrDsToTimestamp: lambda self, e: self.sql(e, "this"),
    }

    # SQLite doesn't generally support CREATE TABLE .. properties
    # https://www.sqlite.org/lang_createtable.html
    PROPERTIES_LOCATION = {
        **{
            prop: exp.Properties.Location.UNSUPPORTED
            for prop in generator.Generator.PROPERTIES_LOCATION
        },
        # There are a few exceptions (e.g. temporary tables) which are supported or
        # can be transpiled to SQLite, so we explicitly override them accordingly
        exp.LikeProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ModuleProperty: exp.Properties.Location.POST_SCHEMA,
        exp.TemporaryProperty: exp.Properties.Location.POST_CREATE,
        exp.VirtualProperty: exp.Properties.Location.POST_CREATE,
    }

    LIMIT_FETCH = "LIMIT"

    def bitwiseandagg_sql(self, expression: exp.BitwiseAndAgg) -> str:
        pass

    def bitwiseoragg_sql(self, expression: exp.BitwiseOrAgg) -> str:
        pass

    def bitwisexoragg_sql(self, expression: exp.BitwiseXorAgg) -> str:
        pass

    def jsonextract_sql(self, expression: exp.JSONExtract) -> str:
        pass

    def dateadd_sql(self, expression: exp.DateAdd) -> str:
        pass

    def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
        if expression.is_type("date"):
            return self.func("DATE", expression.this)

        return super().cast_sql(expression)

    # Note: SQLite's TRUNC always returns REAL (e.g., trunc(10.99) -> 10.0), not INTEGER.
    # This creates a transpilation gap affecting division semantics, similar to Presto.
    # Unlike Presto where this only affects decimals=0, SQLite has no decimals parameter
    # so every use of TRUNC is affected. Modeling precisely would require exp.FloatTrunc.
    @unsupported_args("decimals")
    def trunc_sql(self, expression: exp.Trunc) -> str:
        pass

    def generateseries_sql(self, expression: exp.GenerateSeries) -> str:
        pass

    def datediff_sql(self, expression: exp.DateDiff) -> str:
        pass

    # https://www.sqlite.org/lang_aggfunc.html#group_concat
    def groupconcat_sql(self, expression: exp.GroupConcat) -> str:
        this = expression.this
        distinct = expression.find(exp.Distinct)

        if distinct:
            this = distinct.expressions[0]
            distinct_sql = "DISTINCT "
        else:
            distinct_sql = ""

        if isinstance(expression.this, exp.Order):
            self.unsupported("SQLite GROUP_CONCAT doesn't support ORDER BY.")
            if expression.this.this and not distinct:
                this = expression.this.this

        separator = expression.args.get("separator")
        return f"GROUP_CONCAT({distinct_sql}{self.format_args(this, separator)})"

    def least_sql(self, expression: exp.Least) -> str:
        pass

    def greatest_sql(self, expression: exp.Greatest) -> str:
        pass

    def transaction_sql(self, expression: exp.Transaction) -> str:
        pass

    def isascii_sql(self, expression: exp.IsAscii) -> str:
        pass

    @unsupported_args("this")
    def currentschema_sql(self, expression: exp.CurrentSchema) -> str:
        pass

    def ignorenulls_sql(self, expression: exp.IgnoreNulls) -> str:
        pass

    def respectnulls_sql(self, expression: exp.RespectNulls) -> str:
        pass

    def windowspec_sql(self, expression: exp.WindowSpec) -> str:
        pass
