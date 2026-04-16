from __future__ import annotations

from functools import reduce

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    any_value_to_max_sql,
    date_delta_sql,
    datestrtodate_sql,
    generatedasidentitycolumnconstraint_sql,
    max_or_greatest,
    min_or_least,
    rename_func,
    strposition_sql,
    timestrtotime_sql,
    trim_sql,
)
from sqlglot.helper import seq_get
from sqlglot.parsers.tsql import OPTIONS_THAT_REQUIRE_EQUAL
from sqlglot.time import format_time
from collections import defaultdict

DATE_PART_UNMAPPING = {
    "WEEKISO": "ISO_WEEK",
    "DAYOFWEEK": "WEEKDAY",
    "TIMEZONE_MINUTE": "TZOFFSET",
}

BIT_TYPES = {exp.EQ, exp.NEQ, exp.Is, exp.In, exp.Select, exp.Alias}


def _format_sql(self: TSQLGenerator, expression: exp.NumberToStr | exp.TimeToStr) -> str:
    pass


def _string_agg_sql(self: TSQLGenerator, expression: exp.GroupConcat) -> str:
    pass


def qualify_derived_table_outputs(expression: exp.Expr) -> exp.Expr:
    """Ensures all (unnamed) output columns are aliased for CTEs and Subqueries."""
    pass


def _json_extract_sql(
    self: TSQLGenerator, expression: exp.JSONExtract | exp.JSONExtractScalar
) -> str:
    json_query = self.func("JSON_QUERY", expression.this, expression.expression)
    json_value = self.func("JSON_VALUE", expression.this, expression.expression)
    return self.func("ISNULL", json_query, json_value)


def _timestrtotime_sql(self: TSQLGenerator, expression: exp.TimeStrToTime):
    pass


class TSQLGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    LIMIT_IS_TOP = True
    QUERY_HINTS = False
    RETURNING_END = False
    NVL2_SUPPORTED = False
    ALTER_TABLE_INCLUDE_COLUMN_KEYWORD = False
    LIMIT_FETCH = "FETCH"
    COMPUTED_COLUMN_WITH_TYPE = False
    CTE_RECURSIVE_KEYWORD_REQUIRED = False
    ENSURE_BOOLS = True
    NULL_ORDERING_SUPPORTED: bool | None = None
    SUPPORTS_SINGLE_ARG_CONCAT = False
    TABLESAMPLE_SEED_KEYWORD = "REPEATABLE"
    SUPPORTS_SELECT_INTO = True
    JSON_PATH_BRACKETED_KEY_SUPPORTED = False
    SUPPORTS_TO_NUMBER = False
    SET_OP_MODIFIERS = False
    COPY_PARAMS_EQ_REQUIRED = True
    PARSE_JSON_NAME: str | None = None
    EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE = False
    ALTER_SET_WRAPPED = True
    ALTER_SET_TYPE = ""

    EXPRESSIONS_WITHOUT_NESTED_CTES = {
        exp.Create,
        exp.Delete,
        exp.Insert,
        exp.Intersect,
        exp.Except,
        exp.Merge,
        exp.Select,
        exp.Subquery,
        exp.Union,
        exp.Update,
    }

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
    }

    TYPE_MAPPING = {
        **{
            k: v
            for k, v in generator.Generator.TYPE_MAPPING.items()
            if k not in (exp.DType.NCHAR, exp.DType.NVARCHAR)
        },
        exp.DType.BOOLEAN: "BIT",
        exp.DType.DATETIME2: "DATETIME2",
        exp.DType.DECIMAL: "NUMERIC",
        exp.DType.DOUBLE: "FLOAT",
        exp.DType.INT: "INTEGER",
        exp.DType.ROWVERSION: "ROWVERSION",
        exp.DType.TEXT: "VARCHAR(MAX)",
        exp.DType.TIMESTAMP: "DATETIME2",
        exp.DType.TIMESTAMPNTZ: "DATETIME2",
        exp.DType.TIMESTAMPTZ: "DATETIMEOFFSET",
        exp.DType.SMALLDATETIME: "SMALLDATETIME",
        exp.DType.UTINYINT: "TINYINT",
        exp.DType.VARIANT: "SQL_VARIANT",
        exp.DType.UUID: "UNIQUEIDENTIFIER",
    }

    TRANSFORMS = {
        **{k: v for k, v in generator.Generator.TRANSFORMS.items() if k != exp.ReturnsProperty},
        exp.AnyValue: any_value_to_max_sql,
        exp.Atan2: rename_func("ATN2"),
        exp.ArrayToString: rename_func("STRING_AGG"),
        exp.AutoIncrementColumnConstraint: lambda *_: "IDENTITY",
        exp.Ceil: rename_func("CEILING"),
        exp.Chr: rename_func("CHAR"),
        exp.DateAdd: date_delta_sql("DATEADD"),
        exp.CTE: transforms.preprocess([qualify_derived_table_outputs]),
        exp.CurrentDate: rename_func("GETDATE"),
        exp.CurrentTimestamp: rename_func("GETDATE"),
        exp.CurrentTimestampLTZ: rename_func("SYSDATETIMEOFFSET"),
        exp.DateStrToDate: datestrtodate_sql,
        exp.GeneratedAsIdentityColumnConstraint: generatedasidentitycolumnconstraint_sql,
        exp.GroupConcat: _string_agg_sql,
        exp.If: rename_func("IIF"),
        exp.JSONExtract: _json_extract_sql,
        exp.JSONExtractScalar: _json_extract_sql,
        exp.LastDay: lambda self, e: self.func("EOMONTH", e.this),
        exp.Ln: rename_func("LOG"),
        exp.Max: max_or_greatest,
        exp.MD5: lambda self, e: self.func("HASHBYTES", exp.Literal.string("MD5"), e.this),
        exp.Min: min_or_least,
        exp.NumberToStr: _format_sql,
        exp.Repeat: rename_func("REPLICATE"),
        exp.CurrentSchema: rename_func("SCHEMA_NAME"),
        exp.Select: transforms.preprocess(
            [
                transforms.eliminate_distinct_on,
                transforms.eliminate_semi_and_anti_joins,
                transforms.eliminate_qualify,
                transforms.unnest_generate_date_array_using_recursive_cte,
            ]
        ),
        exp.Stddev: rename_func("STDEV"),
        exp.StrPosition: lambda self, e: strposition_sql(
            self, e, func_name="CHARINDEX", supports_position=True
        ),
        exp.Subquery: transforms.preprocess([qualify_derived_table_outputs]),
        exp.SHA: lambda self, e: self.func("HASHBYTES", exp.Literal.string("SHA1"), e.this),
        exp.SHA1Digest: lambda self, e: self.func("HASHBYTES", exp.Literal.string("SHA1"), e.this),
        exp.SHA2: lambda self, e: self.func(
            "HASHBYTES", exp.Literal.string(f"SHA2_{e.args.get('length', 256)}"), e.this
        ),
        exp.TemporaryProperty: lambda self, e: "",
        exp.TimeStrToTime: _timestrtotime_sql,
        exp.TimeToStr: _format_sql,
        exp.Trim: trim_sql,
        exp.TsOrDsAdd: date_delta_sql("DATEADD", cast=True),
        exp.TsOrDsDiff: date_delta_sql("DATEDIFF"),
        exp.TimestampTrunc: lambda self, e: self.func("DATETRUNC", e.unit, e.this),
        exp.Trunc: lambda self, e: self.func(
            "ROUND",
            e.this,
            e.args.get("decimals") or exp.Literal.number(0),
            exp.Literal.number(1),
        ),
        exp.Uuid: lambda *_: "NEWID()",
        exp.DateFromParts: rename_func("DATEFROMPARTS"),
    }

    PROPERTIES_LOCATION = {
        **generator.Generator.PROPERTIES_LOCATION,
        exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
    }

    def scope_resolution(self, rhs: str, scope_name: str) -> str:
        pass

    def select_sql(self, expression: exp.Select) -> str:
        pass

    def convert_sql(self, expression: exp.Convert) -> str:
        pass

    def queryoption_sql(self, expression: exp.QueryOption) -> str:
        pass

    def lateral_op(self, expression: exp.Lateral) -> str:
        cross_apply = expression.args.get("cross_apply")
        if cross_apply is True:
            return "CROSS APPLY"
        if cross_apply is False:
            return "OUTER APPLY"

        # TODO: perhaps we can check if the parent is a Join and transpile it appropriately
        self.unsupported("LATERAL clause is not supported.")
        return "LATERAL"

    def splitpart_sql(self, expression: exp.SplitPart) -> str:
        pass

    def extract_sql(self, expression: exp.Extract) -> str:
        pass

    def timefromparts_sql(self, expression: exp.TimeFromParts) -> str:
        pass

    def timestampfromparts_sql(self, expression: exp.TimestampFromParts) -> str:
        pass

    def setitem_sql(self, expression: exp.SetItem) -> str:
        pass

    def boolean_sql(self, expression: exp.Boolean) -> str:
        pass

    def is_sql(self, expression: exp.Is) -> str:
        pass

    def createable_sql(self, expression: exp.Create, locations: defaultdict) -> str:
        pass

    def create_sql(self, expression: exp.Create) -> str:
        pass

    @generator.unsupported_args("unlogged", "expressions")
    def into_sql(self, expression: exp.Into) -> str:
        pass

    def count_sql(self, expression: exp.Count) -> str:
        pass

    def datediff_sql(self, expression: exp.DateDiff) -> str:
        pass

    def offset_sql(self, expression: exp.Offset) -> str:
        pass

    def version_sql(self, expression: exp.Version) -> str:
        pass

    def returnsproperty_sql(self, expression: exp.ReturnsProperty) -> str:
        pass

    def returning_sql(self, expression: exp.Returning) -> str:
        pass

    def transaction_sql(self, expression: exp.Transaction) -> str:
        pass

    def commit_sql(self, expression: exp.Commit) -> str:
        pass

    def rollback_sql(self, expression: exp.Rollback) -> str:
        pass

    def identifier_sql(self, expression: exp.Identifier) -> str:
        pass

    def constraint_sql(self, expression: exp.Constraint) -> str:
        pass

    def length_sql(self, expression: exp.Length) -> str:
        pass

    def right_sql(self, expression: exp.Right) -> str:
        pass

    def left_sql(self, expression: exp.Left) -> str:
        pass

    def _uncast_text(self, expression: exp.Expr, name: str) -> str:
        pass

    def partition_sql(self, expression: exp.Partition) -> str:
        pass

    def alter_sql(self, expression: exp.Alter) -> str:
        pass

    def drop_sql(self, expression: exp.Drop) -> str:
        pass

    def options_modifier(self, expression: exp.Expr) -> str:
        options = self.expressions(expression, key="options")
        return f" OPTION{self.wrap(options)}" if options else ""

    def dpipe_sql(self, expression: exp.DPipe) -> str:
        pass

    def isascii_sql(self, expression: exp.IsAscii) -> str:
        pass

    def columndef_sql(self, expression: exp.ColumnDef, sep: str = " ") -> str:
        pass

    def coalesce_sql(self, expression: exp.Coalesce) -> str:
        pass

    def storedprocedure_sql(self, expression: exp.StoredProcedure) -> str:
        pass

    def ifblock_sql(self, expression: exp.IfBlock) -> str:
        pass

    def whileblock_sql(self, expression: exp.WhileBlock) -> str:
        pass

    def execute_sql(self, expression: exp.Execute) -> str:
        pass

    def executesql_sql(self, expression: exp.ExecuteSql) -> str:
        pass
