from __future__ import annotations

import logging
import re
import typing as t

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    arg_max_or_min_no_count,
    date_add_interval_sql,
    datestrtodate_sql,
    filter_array_using_unnest,
    generate_series_sql,
    if_sql,
    inline_array_unless_query,
    max_or_greatest,
    min_or_least,
    no_ilike_sql,
    regexp_replace_sql,
    rename_func,
    sha256_sql,
    timestrtotime_sql,
    ts_or_ds_add_cast,
    unit_to_var,
    strposition_sql,
    groupconcat_sql,
    sha2_digest_sql,
)
from sqlglot.generator import unsupported_args
from sqlglot.helper import seq_get

logger = logging.getLogger("sqlglot")

JSON_EXTRACT_TYPE = t.Union[exp.JSONExtract, exp.JSONExtractScalar, exp.JSONExtractArray]

DQUOTES_ESCAPING_JSON_FUNCTIONS = ("JSON_QUERY", "JSON_VALUE", "JSON_QUERY_ARRAY")


def _derived_table_values_to_unnest(self: BigQueryGenerator, expression: exp.Values) -> str:
    pass


def _returnsproperty_sql(self: BigQueryGenerator, expression: exp.ReturnsProperty) -> str:
    pass


def _create_sql(self: BigQueryGenerator, expression: exp.Create) -> str:
    pass


# https://issuetracker.google.com/issues/162294746
# workaround for bigquery bug when grouping by an expression and then ordering
# WITH x AS (SELECT 1 y)
# SELECT y + 1 z
# FROM x
# GROUP BY x + 1
# ORDER by z
def _alias_ordered_group(expression: exp.Expr) -> exp.Expr:
    pass


def _pushdown_cte_column_names(expression: exp.Expr) -> exp.Expr:
    """BigQuery doesn't allow column names when defining a CTE, so we try to push them down."""
    pass


def _array_contains_sql(self: BigQueryGenerator, expression: exp.ArrayContains) -> str:
    pass


def _ts_or_ds_add_sql(self: BigQueryGenerator, expression: exp.TsOrDsAdd) -> str:
    pass


def _ts_or_ds_diff_sql(self: BigQueryGenerator, expression: exp.TsOrDsDiff) -> str:
    pass


def _unix_to_time_sql(self: BigQueryGenerator, expression: exp.UnixToTime) -> str:
    scale = expression.args.get("scale")
    timestamp = expression.this

    if scale in (None, exp.UnixToTime.SECONDS):
        return self.func("TIMESTAMP_SECONDS", timestamp)
    if scale == exp.UnixToTime.MILLIS:
        return self.func("TIMESTAMP_MILLIS", timestamp)
    if scale == exp.UnixToTime.MICROS:
        return self.func("TIMESTAMP_MICROS", timestamp)

    unix_seconds = exp.cast(
        exp.Div(this=timestamp, expression=exp.func("POW", 10, scale)), exp.DType.BIGINT
    )
    return self.func("TIMESTAMP_SECONDS", unix_seconds)


def _str_to_datetime_sql(self: BigQueryGenerator, expression: exp.StrToDate | exp.StrToTime) -> str:
    pass


@unsupported_args("ins_cost", "del_cost", "sub_cost")
def _levenshtein_sql(self: BigQueryGenerator, expression: exp.Levenshtein) -> str:
    pass


def _json_extract_sql(self: BigQueryGenerator, expression: JSON_EXTRACT_TYPE) -> str:
    name = (expression._meta and expression.meta.get("name")) or expression.sql_name()
    upper = name.upper()

    dquote_escaping = upper in DQUOTES_ESCAPING_JSON_FUNCTIONS

    if dquote_escaping:
        self._quote_json_path_key_using_brackets = False

    sql = rename_func(upper)(self, expression)

    if dquote_escaping:
        self._quote_json_path_key_using_brackets = True

    return sql


class BigQueryGenerator(generator.Generator):
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False
    INTERVAL_ALLOWS_PLURAL_FORM = False
    JOIN_HINTS = False
    QUERY_HINTS = False
    TABLE_HINTS = False
    LIMIT_FETCH = "LIMIT"
    RENAME_TABLE_WITH_DB = False
    NVL2_SUPPORTED = False
    UNNEST_WITH_ORDINALITY = False
    COLLATE_IS_FUNC = True
    LIMIT_ONLY_LITERALS = True
    SUPPORTS_TABLE_ALIAS_COLUMNS = False
    UNPIVOT_ALIASES_ARE_IDENTIFIERS = False
    JSON_KEY_VALUE_PAIR_SEP = ","
    NULL_ORDERING_SUPPORTED: bool | None = False
    IGNORE_NULLS_IN_FUNC = True
    JSON_PATH_SINGLE_QUOTE_ESCAPE = True
    CAN_IMPLEMENT_ARRAY_ANY = True
    SUPPORTS_TO_NUMBER = False
    NAMED_PLACEHOLDER_TOKEN = "@"
    HEX_FUNC = "TO_HEX"
    WITH_PROPERTIES_PREFIX = "OPTIONS"
    SUPPORTS_EXPLODING_PROJECTIONS = False
    EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE = False
    SUPPORTS_UNIX_SECONDS = True
    DECLARE_DEFAULT_ASSIGNMENT = "DEFAULT"

    SAFE_JSON_PATH_KEY_RE = re.compile(r"^[\-\w]*$")

    WINDOW_FUNCS_WITH_NULL_ORDERING = (
        exp.CumeDist,
        exp.DenseRank,
        exp.FirstValue,
        exp.Lag,
        exp.LastValue,
        exp.Lead,
        exp.NthValue,
        exp.Ntile,
        exp.PercentRank,
        exp.Rank,
        exp.RowNumber,
    )

    TS_OR_DS_TYPES = (
        exp.TsOrDsToDatetime,
        exp.TsOrDsToTimestamp,
        exp.TsOrDsToTime,
        exp.TsOrDsToDate,
    )

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.AIEmbed: rename_func("EMBED"),
        exp.AIGenerate: rename_func("GENERATE"),
        exp.AISimilarity: rename_func("SIMILARITY"),
        exp.ApproxTopK: rename_func("APPROX_TOP_COUNT"),
        exp.ApproxDistinct: rename_func("APPROX_COUNT_DISTINCT"),
        exp.ArgMax: arg_max_or_min_no_count("MAX_BY"),
        exp.ArgMin: arg_max_or_min_no_count("MIN_BY"),
        exp.Array: inline_array_unless_query,
        exp.ArrayContains: _array_contains_sql,
        exp.ArrayFilter: filter_array_using_unnest,
        exp.ArrayRemove: filter_array_using_unnest,
        exp.BitwiseAndAgg: rename_func("BIT_AND"),
        exp.BitwiseOrAgg: rename_func("BIT_OR"),
        exp.BitwiseXorAgg: rename_func("BIT_XOR"),
        exp.BitwiseCount: rename_func("BIT_COUNT"),
        exp.ByteLength: rename_func("BYTE_LENGTH"),
        exp.Cast: transforms.preprocess([transforms.remove_precision_parameterized_types]),
        exp.CollateProperty: lambda self, e: (
            f"DEFAULT COLLATE {self.sql(e, 'this')}"
            if e.args.get("default")
            else f"COLLATE {self.sql(e, 'this')}"
        ),
        exp.Commit: lambda *_: "COMMIT TRANSACTION",
        exp.CountIf: rename_func("COUNTIF"),
        exp.Create: _create_sql,
        exp.CTE: transforms.preprocess([_pushdown_cte_column_names]),
        exp.DateAdd: date_add_interval_sql("DATE", "ADD"),
        exp.DateDiff: lambda self, e: self.func("DATE_DIFF", e.this, e.expression, unit_to_var(e)),
        exp.DateFromParts: rename_func("DATE"),
        exp.DateStrToDate: datestrtodate_sql,
        exp.DateSub: date_add_interval_sql("DATE", "SUB"),
        exp.DatetimeAdd: date_add_interval_sql("DATETIME", "ADD"),
        exp.DatetimeSub: date_add_interval_sql("DATETIME", "SUB"),
        exp.DateFromUnixDate: rename_func("DATE_FROM_UNIX_DATE"),
        exp.FromTimeZone: lambda self, e: self.func(
            "DATETIME", self.func("TIMESTAMP", e.this, e.args.get("zone")), "'UTC'"
        ),
        exp.GenerateSeries: generate_series_sql("GENERATE_ARRAY"),
        exp.GroupConcat: lambda self, e: groupconcat_sql(
            self, e, func_name="STRING_AGG", within_group=False, sep=None
        ),
        exp.Hex: lambda self, e: self.func("UPPER", self.func("TO_HEX", self.sql(e, "this"))),
        exp.HexString: lambda self, e: self.hexstring_sql(e, binary_function_repr="FROM_HEX"),
        exp.If: if_sql(false_value="NULL"),
        exp.ILike: no_ilike_sql,
        exp.IntDiv: rename_func("DIV"),
        exp.Int64: rename_func("INT64"),
        exp.JSONBool: rename_func("BOOL"),
        exp.JSONExtract: _json_extract_sql,
        exp.JSONExtractArray: _json_extract_sql,
        exp.JSONExtractScalar: _json_extract_sql,
        exp.JSONFormat: lambda self, e: self.func(
            "TO_JSON" if e.args.get("to_json") else "TO_JSON_STRING",
            e.this,
            e.args.get("options"),
        ),
        exp.JSONKeysAtDepth: rename_func("JSON_KEYS"),
        exp.JSONValueArray: rename_func("JSON_VALUE_ARRAY"),
        exp.Levenshtein: _levenshtein_sql,
        exp.Max: max_or_greatest,
        exp.MD5: lambda self, e: self.func("TO_HEX", self.func("MD5", e.this)),
        exp.MD5Digest: rename_func("MD5"),
        exp.Min: min_or_least,
        exp.Normalize: lambda self, e: self.func(
            "NORMALIZE_AND_CASEFOLD" if e.args.get("is_casefold") else "NORMALIZE",
            e.this,
            e.args.get("form"),
        ),
        exp.PartitionedByProperty: lambda self, e: f"PARTITION BY {self.sql(e, 'this')}",
        exp.RegexpExtract: lambda self, e: self.func(
            "REGEXP_EXTRACT",
            e.this,
            e.expression,
            e.args.get("position"),
            e.args.get("occurrence"),
        ),
        exp.RegexpExtractAll: lambda self, e: self.func("REGEXP_EXTRACT_ALL", e.this, e.expression),
        exp.RegexpReplace: regexp_replace_sql,
        exp.RegexpLike: rename_func("REGEXP_CONTAINS"),
        exp.ReturnsProperty: _returnsproperty_sql,
        exp.Rollback: lambda *_: "ROLLBACK TRANSACTION",
        exp.ParseTime: lambda self, e: self.func("PARSE_TIME", self.format_time(e), e.this),
        exp.ParseDatetime: lambda self, e: self.func("PARSE_DATETIME", self.format_time(e), e.this),
        exp.Select: transforms.preprocess(
            [
                transforms.explode_projection_to_unnest(),
                transforms.unqualify_unnest,
                transforms.eliminate_distinct_on,
                _alias_ordered_group,
                transforms.eliminate_semi_and_anti_joins,
            ]
        ),
        exp.SHA: rename_func("SHA1"),
        exp.SHA2: sha256_sql,
        exp.SHA1Digest: rename_func("SHA1"),
        exp.SHA2Digest: sha2_digest_sql,
        exp.StabilityProperty: lambda self, e: (
            "DETERMINISTIC" if e.name == "IMMUTABLE" else "NOT DETERMINISTIC"
        ),
        exp.String: rename_func("STRING"),
        exp.StrPosition: lambda self, e: strposition_sql(
            self, e, func_name="INSTR", supports_position=True, supports_occurrence=True
        ),
        exp.StrToDate: _str_to_datetime_sql,
        exp.StrToTime: _str_to_datetime_sql,
        exp.SessionUser: lambda *_: "SESSION_USER()",
        exp.TimeAdd: date_add_interval_sql("TIME", "ADD"),
        exp.TimeFromParts: rename_func("TIME"),
        exp.TimestampFromParts: rename_func("DATETIME"),
        exp.TimeSub: date_add_interval_sql("TIME", "SUB"),
        exp.TimestampAdd: date_add_interval_sql("TIMESTAMP", "ADD"),
        exp.TimestampDiff: rename_func("TIMESTAMP_DIFF"),
        exp.TimestampSub: date_add_interval_sql("TIMESTAMP", "SUB"),
        exp.TimeStrToTime: timestrtotime_sql,
        exp.Transaction: lambda *_: "BEGIN TRANSACTION",
        exp.TsOrDsAdd: _ts_or_ds_add_sql,
        exp.TsOrDsDiff: _ts_or_ds_diff_sql,
        exp.TsOrDsToTime: rename_func("TIME"),
        exp.TsOrDsToDatetime: rename_func("DATETIME"),
        exp.TsOrDsToTimestamp: rename_func("TIMESTAMP"),
        exp.Unhex: rename_func("FROM_HEX"),
        exp.UnixDate: rename_func("UNIX_DATE"),
        exp.UnixToTime: _unix_to_time_sql,
        exp.Uuid: lambda *_: "GENERATE_UUID()",
        exp.Values: _derived_table_values_to_unnest,
        exp.VariancePop: rename_func("VAR_POP"),
        exp.SafeDivide: rename_func("SAFE_DIVIDE"),
    }

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
    }

    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        exp.DType.BIGDECIMAL: "BIGNUMERIC",
        exp.DType.BIGINT: "INT64",
        exp.DType.BINARY: "BYTES",
        exp.DType.BLOB: "BYTES",
        exp.DType.BOOLEAN: "BOOL",
        exp.DType.CHAR: "STRING",
        exp.DType.DECIMAL: "NUMERIC",
        exp.DType.DOUBLE: "FLOAT64",
        exp.DType.FLOAT: "FLOAT64",
        exp.DType.INT: "INT64",
        exp.DType.NCHAR: "STRING",
        exp.DType.NVARCHAR: "STRING",
        exp.DType.SMALLINT: "INT64",
        exp.DType.TEXT: "STRING",
        exp.DType.TIMESTAMP: "DATETIME",
        exp.DType.TIMESTAMPNTZ: "DATETIME",
        exp.DType.TIMESTAMPTZ: "TIMESTAMP",
        exp.DType.TIMESTAMPLTZ: "TIMESTAMP",
        exp.DType.TINYINT: "INT64",
        exp.DType.ROWVERSION: "BYTES",
        exp.DType.UUID: "STRING",
        exp.DType.VARBINARY: "BYTES",
        exp.DType.VARCHAR: "STRING",
        exp.DType.VARIANT: "ANY TYPE",
    }

    PROPERTIES_LOCATION = {
        **generator.Generator.PROPERTIES_LOCATION,
        exp.PartitionedByProperty: exp.Properties.Location.POST_SCHEMA,
        exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
    }

    # WINDOW comes after QUALIFY
    # https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#window_clause
    # BigQuery requires QUALIFY before WINDOW
    AFTER_HAVING_MODIFIER_TRANSFORMS = {
        "qualify": generator.AFTER_HAVING_MODIFIER_TRANSFORMS["qualify"],
        "windows": generator.AFTER_HAVING_MODIFIER_TRANSFORMS["windows"],
    }

    # from: https://cloud.google.com/bigquery/docs/reference/standard-sql/lexical#reserved_keywords
    RESERVED_KEYWORDS = {
        "all",
        "and",
        "any",
        "array",
        "as",
        "asc",
        "assert_rows_modified",
        "at",
        "between",
        "by",
        "case",
        "cast",
        "collate",
        "contains",
        "create",
        "cross",
        "cube",
        "current",
        "default",
        "define",
        "desc",
        "distinct",
        "else",
        "end",
        "enum",
        "escape",
        "except",
        "exclude",
        "exists",
        "extract",
        "false",
        "fetch",
        "following",
        "for",
        "from",
        "full",
        "group",
        "grouping",
        "groups",
        "hash",
        "having",
        "if",
        "ignore",
        "in",
        "inner",
        "intersect",
        "interval",
        "into",
        "is",
        "join",
        "lateral",
        "left",
        "like",
        "limit",
        "lookup",
        "merge",
        "natural",
        "new",
        "no",
        "not",
        "null",
        "nulls",
        "of",
        "on",
        "or",
        "order",
        "outer",
        "over",
        "partition",
        "preceding",
        "proto",
        "qualify",
        "range",
        "recursive",
        "respect",
        "right",
        "rollup",
        "rows",
        "select",
        "set",
        "some",
        "struct",
        "tablesample",
        "then",
        "to",
        "treat",
        "true",
        "unbounded",
        "union",
        "unnest",
        "using",
        "when",
        "where",
        "window",
        "with",
        "within",
    }

    def datetrunc_sql(self, expression: exp.DateTrunc) -> str:
        pass

    def mod_sql(self, expression: exp.Mod) -> str:
        pass

    def column_parts(self, expression: exp.Column) -> str:
        pass

    def table_parts(self, expression: exp.Table) -> str:
        # Depending on the context, `x.y` may not resolve to the same data source as `x`.`y`, so
        # we need to make sure the correct quoting is used in each case.
        #
        # For example, if there is a CTE x that clashes with a schema name, then the former will
        # return the table y in that schema, whereas the latter will return the CTE's y column:
        #
        # - WITH x AS (SELECT [1, 2] AS y) SELECT * FROM x, `x.y`   -> cross join
        # - WITH x AS (SELECT [1, 2] AS y) SELECT * FROM x, `x`.`y` -> implicit unnest
        if expression.meta.get("quoted_table"):
            table_parts = ".".join(p.name for p in expression.parts)
            return self.sql(exp.Identifier(this=table_parts, quoted=True))

        return super().table_parts(expression)

    def timetostr_sql(self, expression: exp.TimeToStr) -> str:
        pass

    def eq_sql(self, expression: exp.EQ) -> str:
        # Operands of = cannot be NULL in BigQuery
        pass

    def attimezone_sql(self, expression: exp.AtTimeZone) -> str:
        pass

    def trycast_sql(self, expression: exp.TryCast) -> str:
        return self.cast_sql(expression, safe_prefix="SAFE_")

    def bracket_sql(self, expression: exp.Bracket) -> str:
        pass

    def in_unnest_op(self, expression: exp.Unnest) -> str:
        pass

    def version_sql(self, expression: exp.Version) -> str:
        pass

    def contains_sql(self, expression: exp.Contains) -> str:
        pass

    def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
        this = expression.this

        # This ensures that inline type-annotated ARRAY literals like ARRAY<INT64>[1, 2, 3]
        # are roundtripped unaffected. The inner check excludes ARRAY(SELECT ...) expressions,
        # because they aren't literals and so the above syntax is invalid BigQuery.
        if isinstance(this, exp.Array):
            elem = seq_get(this.expressions, 0)
            if not (elem and elem.find(exp.Query)):
                return f"{self.sql(expression, 'to')}{self.sql(this)}"

        return super().cast_sql(expression, safe_prefix=safe_prefix)
