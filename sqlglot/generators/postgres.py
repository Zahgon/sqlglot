from __future__ import annotations

import typing as t

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    DATE_ADD_OR_SUB,
    JSON_EXTRACT_TYPE,
    any_value_to_max_sql,
    array_append_sql,
    array_concat_sql,
    bool_xor_sql,
    count_if_to_sum,
    datestrtodate_sql,
    filter_array_using_unnest,
    generate_series_sql,
    getbit_sql,
    groupconcat_sql,
    inline_array_sql,
    json_extract_segments,
    json_path_key_only_name,
    max_or_greatest,
    merge_without_target_sql,
    min_or_least,
    no_last_day_sql,
    no_map_from_entries_sql,
    no_paren_current_date_sql,
    no_pivot_sql,
    no_trycast_sql,
    regexp_replace_global_modifier,
    rename_func,
    sha256_sql,
    sha2_digest_sql,
    strposition_sql,
    struct_extract_sql,
    timestamptrunc_sql,
    timestrtotime_sql,
    trim_sql,
    ts_or_ds_add_cast,
)
from sqlglot.generator import unsupported_args
from sqlglot.helper import seq_get


DATE_DIFF_FACTOR = {
    "MICROSECOND": " * 1000000",
    "MILLISECOND": " * 1000",
    "SECOND": "",
    "MINUTE": " / 60",
    "HOUR": " / 3600",
    "DAY": " / 86400",
}


def _date_add_sql(kind: str) -> t.Callable[[PostgresGenerator, DATE_ADD_OR_SUB], str]:
    def func(self: PostgresGenerator, expression: DATE_ADD_OR_SUB) -> str:
        if isinstance(expression, exp.TsOrDsAdd):
            expression = ts_or_ds_add_cast(expression)

        this = self.sql(expression, "this")
        unit = expression.args.get("unit")

        e = self._simplify_unless_literal(expression.expression)
        if isinstance(e, exp.Interval):
            return f"{this} {kind} {self.sql(e)}"
        elif isinstance(e, exp.Literal):
            e.set("is_string", True)
        elif e.is_number:
            e = exp.Literal.string(e.to_py())
        else:
            one = exp.Literal.number(1)
            interval_times_value = exp.Interval(this=one, unit=unit) * e
            return f"{this} {kind} {self.sql(interval_times_value)}"

        return f"{this} {kind} {self.sql(exp.Interval(this=e, unit=unit))}"

    return func


def _date_diff_sql(self: PostgresGenerator, expression: exp.DateDiff | exp.TsOrDsDiff) -> str:
    pass


def _substring_sql(self: PostgresGenerator, expression: exp.Substring) -> str:
    pass


def _auto_increment_to_serial(expression: exp.Expr) -> exp.Expr:
    pass


def _serial_to_generated(expression: exp.Expr) -> exp.Expr:
    pass


def _json_extract_sql(
    name: str, op: str
) -> t.Callable[[PostgresGenerator, JSON_EXTRACT_TYPE], str]:
    def _generate(self: PostgresGenerator, expression: JSON_EXTRACT_TYPE) -> str:
        pass

    return _generate


def _unix_to_time_sql(self: PostgresGenerator, expression: exp.UnixToTime) -> str:
    scale = expression.args.get("scale")
    timestamp = expression.this

    if scale in (None, exp.UnixToTime.SECONDS):
        return self.func("TO_TIMESTAMP", timestamp, self.format_time(expression))

    return self.func(
        "TO_TIMESTAMP",
        exp.Div(this=timestamp, expression=exp.func("POW", 10, scale)),
        self.format_time(expression),
    )


def _levenshtein_sql(self: PostgresGenerator, expression: exp.Levenshtein) -> str:
    pass


def _versioned_anyvalue_sql(self: PostgresGenerator, expression: exp.AnyValue) -> str:
    # https://www.postgresql.org/docs/16/functions-aggregate.html
    # https://www.postgresql.org/about/featurematrix/
    pass


def _round_sql(self: PostgresGenerator, expression: exp.Round) -> str:
    pass


class PostgresGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    SINGLE_STRING_INTERVAL = True
    RENAME_TABLE_WITH_DB = False
    LOCKING_READS_SUPPORTED = True
    JOIN_HINTS = False
    TABLE_HINTS = False
    QUERY_HINTS = False
    NVL2_SUPPORTED = False
    PARAMETER_TOKEN = "$"
    NAMED_PLACEHOLDER_TOKEN = "%"
    TABLESAMPLE_SIZE_IS_ROWS = False
    TABLESAMPLE_SEED_KEYWORD = "REPEATABLE"
    SUPPORTS_SELECT_INTO = True
    JSON_TYPE_REQUIRED_FOR_EXTRACTION = True
    SUPPORTS_UNLOGGED_TABLES = True
    LIKE_PROPERTY_INSIDE_SCHEMA = True
    MULTI_ARG_DISTINCT = False
    CAN_IMPLEMENT_ARRAY_ANY = True
    SUPPORTS_WINDOW_EXCLUDE = True
    COPY_HAS_INTO_KEYWORD = False
    ARRAY_CONCAT_IS_VAR_LEN = False
    SUPPORTS_MEDIAN = False
    ARRAY_SIZE_DIM_REQUIRED: bool | None = True
    SUPPORTS_BETWEEN_FLAGS = True
    INOUT_SEPARATOR = ""  # PostgreSQL uses "INOUT" (no space)

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
    }

    def lateral_sql(self, expression: exp.Lateral) -> str:
        sql = super().lateral_sql(expression)

        if expression.args.get("cross_apply") is not None:
            sql = f"{sql} ON TRUE"

        return sql

    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        exp.DType.TINYINT: "SMALLINT",
        exp.DType.FLOAT: "REAL",
        exp.DType.DOUBLE: "DOUBLE PRECISION",
        exp.DType.BINARY: "BYTEA",
        exp.DType.VARBINARY: "BYTEA",
        exp.DType.ROWVERSION: "BYTEA",
        exp.DType.DATETIME: "TIMESTAMP",
        exp.DType.TIMESTAMPNTZ: "TIMESTAMP",
        exp.DType.BLOB: "BYTEA",
    }

    TRANSFORMS = {
        **{
            k: v
            for k, v in generator.Generator.TRANSFORMS.items()
            if k != exp.CommentColumnConstraint
        },
        exp.AnyValue: _versioned_anyvalue_sql,
        exp.ArrayConcat: array_concat_sql("ARRAY_CAT"),
        exp.ArrayFilter: filter_array_using_unnest,
        exp.ArrayAppend: array_append_sql("ARRAY_APPEND"),
        exp.ArrayPrepend: array_append_sql("ARRAY_PREPEND", swap_params=True),
        exp.BitwiseAndAgg: rename_func("BIT_AND"),
        exp.BitwiseOrAgg: rename_func("BIT_OR"),
        exp.BitwiseXor: lambda self, e: self.binary(e, "#"),
        exp.BitwiseXorAgg: rename_func("BIT_XOR"),
        exp.ColumnDef: transforms.preprocess([_auto_increment_to_serial, _serial_to_generated]),
        exp.CurrentDate: no_paren_current_date_sql,
        exp.CurrentTimestamp: lambda *_: "CURRENT_TIMESTAMP",
        exp.CurrentUser: lambda *_: "CURRENT_USER",
        exp.CurrentVersion: rename_func("VERSION"),
        exp.DateAdd: _date_add_sql("+"),
        exp.DateDiff: _date_diff_sql,
        exp.DateStrToDate: datestrtodate_sql,
        exp.DateSub: _date_add_sql("-"),
        exp.Explode: rename_func("UNNEST"),
        exp.ExplodingGenerateSeries: rename_func("GENERATE_SERIES"),
        exp.GenerateSeries: generate_series_sql("GENERATE_SERIES"),
        exp.Getbit: getbit_sql,
        exp.GroupConcat: lambda self, e: groupconcat_sql(
            self, e, func_name="STRING_AGG", within_group=False
        ),
        exp.IntDiv: rename_func("DIV"),
        exp.JSONArrayAgg: lambda self, e: self.func(
            "JSON_AGG",
            self.sql(e, "this"),
            suffix=f"{self.sql(e, 'order')})",
        ),
        exp.JSONExtract: _json_extract_sql("JSON_EXTRACT_PATH", "->"),
        exp.JSONExtractScalar: _json_extract_sql("JSON_EXTRACT_PATH_TEXT", "->>"),
        exp.JSONBExtract: lambda self, e: self.binary(e, "#>"),
        exp.JSONBExtractScalar: lambda self, e: self.binary(e, "#>>"),
        exp.JSONBContains: lambda self, e: self.binary(e, "?"),
        exp.ParseJSON: lambda self, e: self.sql(exp.cast(e.this, exp.DType.JSON)),
        exp.JSONPathKey: json_path_key_only_name,
        exp.JSONPathRoot: lambda *_: "",
        exp.JSONPathSubscript: lambda self, e: self.json_path_part(e.this),
        exp.LastDay: no_last_day_sql,
        exp.LogicalOr: rename_func("BOOL_OR"),
        exp.LogicalAnd: rename_func("BOOL_AND"),
        exp.Max: max_or_greatest,
        exp.MapFromEntries: no_map_from_entries_sql,
        exp.Min: min_or_least,
        exp.Merge: merge_without_target_sql,
        exp.PartitionedByProperty: lambda self, e: f"PARTITION BY {self.sql(e, 'this')}",
        exp.PercentileCont: transforms.preprocess([transforms.add_within_group_for_percentiles]),
        exp.PercentileDisc: transforms.preprocess([transforms.add_within_group_for_percentiles]),
        exp.Pivot: no_pivot_sql,
        exp.Rand: rename_func("RANDOM"),
        exp.RegexpLike: lambda self, e: self.binary(e, "~"),
        exp.RegexpILike: lambda self, e: self.binary(e, "~*"),
        exp.RegexpReplace: lambda self, e: self.func(
            "REGEXP_REPLACE",
            e.this,
            e.expression,
            e.args.get("replacement"),
            e.args.get("position"),
            e.args.get("occurrence"),
            regexp_replace_global_modifier(e),
        ),
        exp.Round: _round_sql,
        exp.Select: transforms.preprocess(
            [
                transforms.eliminate_semi_and_anti_joins,
                transforms.eliminate_qualify,
            ]
        ),
        exp.SHA2: sha256_sql,
        exp.SHA2Digest: sha2_digest_sql,
        exp.StrPosition: lambda self, e: strposition_sql(self, e, func_name="POSITION"),
        exp.StrToDate: lambda self, e: self.func("TO_DATE", e.this, self.format_time(e)),
        exp.StrToTime: lambda self, e: self.func("TO_TIMESTAMP", e.this, self.format_time(e)),
        exp.StructExtract: struct_extract_sql,
        exp.Substring: _substring_sql,
        exp.TimeFromParts: rename_func("MAKE_TIME"),
        exp.TimestampFromParts: rename_func("MAKE_TIMESTAMP"),
        exp.TimestampTrunc: timestamptrunc_sql(zone=True),
        exp.TimeStrToTime: timestrtotime_sql,
        exp.TimeToStr: lambda self, e: self.func("TO_CHAR", e.this, self.format_time(e)),
        exp.ToChar: lambda self, e: (
            self.function_fallback_sql(e) if e.args.get("format") else self.tochar_sql(e)
        ),
        exp.Trim: trim_sql,
        exp.TryCast: no_trycast_sql,
        exp.TsOrDsAdd: _date_add_sql("+"),
        exp.TsOrDsDiff: _date_diff_sql,
        exp.UnixToTime: lambda self, e: self.func("TO_TIMESTAMP", e.this),
        exp.Uuid: lambda *_: "GEN_RANDOM_UUID()",
        exp.TimeToUnix: lambda self, e: self.func("DATE_PART", exp.Literal.string("epoch"), e.this),
        exp.VariancePop: rename_func("VAR_POP"),
        exp.Variance: rename_func("VAR_SAMP"),
        exp.Xor: bool_xor_sql,
        exp.Unicode: rename_func("ASCII"),
        exp.UnixToTime: _unix_to_time_sql,
        exp.Levenshtein: _levenshtein_sql,
        exp.JSONObjectAgg: rename_func("JSON_OBJECT_AGG"),
        exp.JSONBObjectAgg: rename_func("JSONB_OBJECT_AGG"),
        exp.CountIf: count_if_to_sum,
    }

    PROPERTIES_LOCATION = {
        **generator.Generator.PROPERTIES_LOCATION,
        exp.PartitionedByProperty: exp.Properties.Location.POST_SCHEMA,
        exp.TransientProperty: exp.Properties.Location.UNSUPPORTED,
        exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
    }

    def schemacommentproperty_sql(self, expression: exp.SchemaCommentProperty) -> str:
        pass

    def commentcolumnconstraint_sql(self, expression: exp.CommentColumnConstraint) -> str:
        pass

    def columndef_sql(self, expression: exp.ColumnDef, sep: str = " ") -> str:
        # PostgreSQL places parameter modes BEFORE parameter name
        pass

    def unnest_sql(self, expression: exp.Unnest) -> str:
        pass

    def bracket_sql(self, expression: exp.Bracket) -> str:
        """Forms like ARRAY[1, 2, 3][3] aren't allowed; we need to wrap the ARRAY."""
        pass

    def matchagainst_sql(self, expression: exp.MatchAgainst) -> str:
        this = self.sql(expression, "this")
        expressions = [f"{self.sql(e)} @@ {this}" for e in expression.expressions]
        sql = " OR ".join(expressions)
        return f"({sql})" if len(expressions) > 1 else sql

    def alterset_sql(self, expression: exp.AlterSet) -> str:
        pass

    def datatype_sql(self, expression: exp.DataType) -> str:
        pass

    def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
        this = expression.this

        # Postgres casts DIV() to decimal for transpilation but when roundtripping it's superfluous
        if isinstance(this, exp.IntDiv) and expression.to == exp.DType.DECIMAL.into_expr():
            return self.sql(this)

        return super().cast_sql(expression, safe_prefix=safe_prefix)

    def array_sql(self, expression: exp.Array) -> str:
        pass

    def computedcolumnconstraint_sql(self, expression: exp.ComputedColumnConstraint) -> str:
        pass

    def isascii_sql(self, expression: exp.IsAscii) -> str:
        pass

    def ignorenulls_sql(self, expression: exp.IgnoreNulls) -> str:
        # https://www.postgresql.org/docs/current/functions-window.html
        pass

    def respectnulls_sql(self, expression: exp.RespectNulls) -> str:
        # https://www.postgresql.org/docs/current/functions-window.html
        pass

    @unsupported_args("this")
    def currentschema_sql(self, expression: exp.CurrentSchema) -> str:
        pass

    def interval_sql(self, expression: exp.Interval) -> str:
        pass

    def placeholder_sql(self, expression: exp.Placeholder) -> str:
        pass

    def arraycontains_sql(self, expression: exp.ArrayContains) -> str:
        # Convert DuckDB's LIST_CONTAINS(array, value) to PostgreSQL
        # DuckDB behavior:
        #   - LIST_CONTAINS([1,2,3], 2) -> true
        #   - LIST_CONTAINS([1,2,3], 4) -> false
        #   - LIST_CONTAINS([1,2,NULL], 4) -> false (not NULL)
        #   - LIST_CONTAINS([1,2,3], NULL) -> NULL
        #
        # PostgreSQL equivalent: CASE WHEN value IS NULL THEN NULL
        #                            ELSE COALESCE(value = ANY(array), FALSE) END
        pass
