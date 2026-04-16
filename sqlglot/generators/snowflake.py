from __future__ import annotations

import typing as t

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    array_append_sql,
    array_concat_sql,
    date_delta_sql,
    datestrtodate_sql,
    groupconcat_sql,
    if_sql,
    inline_array_sql,
    map_date_part,
    max_or_greatest,
    min_or_least,
    no_make_interval_sql,
    no_timestamp_sql,
    rename_func,
    strposition_sql,
    timestampdiff_sql,
    timestamptrunc_sql,
    timestrtotime_sql,
    unit_to_str,
    var_map_sql,
)
from sqlglot.generator import unsupported_args
from sqlglot.helper import find_new_name, flatten, seq_get
from sqlglot.optimizer.scope import build_scope, find_all_in_scope
from sqlglot.parsers.snowflake import (
    RANKING_WINDOW_FUNCTIONS_WITH_FRAME,
    TIMESTAMP_TYPES,
    SnowflakeParser,
    build_object_construct,
)
from sqlglot.tokens import TokenType
from collections import defaultdict

if t.TYPE_CHECKING:
    from sqlglot._typing import E


def _build_datediff(args: list) -> exp.DateDiff:
    pass


def _build_date_time_add(expr_type: type[E]) -> t.Callable[[list], E]:
    pass


def _regexpilike_sql(self: SnowflakeGenerator, expression: exp.RegexpILike) -> str:
    pass


def _unqualify_pivot_columns(expression: exp.Expr) -> exp.Expr:
    """
    Snowflake doesn't allow columns referenced in UNPIVOT to be qualified,
    so we need to unqualify them. Same goes for ANY ORDER BY <column>.

    Example:
        >>> from sqlglot import parse_one
        >>> expr = parse_one("SELECT * FROM m_sales UNPIVOT(sales FOR month IN (m_sales.jan, feb, mar, april))")
        >>> print(_unqualify_pivot_columns(expr).sql(dialect="snowflake"))
        SELECT * FROM m_sales UNPIVOT(sales FOR month IN (jan, feb, mar, april))
    """
    pass


def _flatten_structured_types_unless_iceberg(expression: exp.Expr) -> exp.Expr:
    pass


def _unnest_generate_date_array(unnest: exp.Unnest) -> None:
    pass


def _transform_generate_date_array(expression: exp.Expr) -> exp.Expr:
    pass


def _regexpextract_sql(
    self: SnowflakeGenerator, expression: exp.RegexpExtract | exp.RegexpExtractAll
) -> str:
    # Other dialects don't support all of the following parameters, so we need to
    # generate default values as necessary to ensure the transpilation is correct
    pass


def _json_extract_value_array_sql(
    self: SnowflakeGenerator, expression: exp.JSONValueArray | exp.JSONExtractArray
) -> str:
    pass


def _qualify_unnested_columns(expression: exp.Expr) -> exp.Expr:
    pass


def _eliminate_dot_variant_lookup(expression: exp.Expr) -> exp.Expr:
    pass


class SnowflakeGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    PARAMETER_TOKEN = "$"
    MATCHED_BY_SOURCE = False
    SINGLE_STRING_INTERVAL = True
    JOIN_HINTS = False
    TABLE_HINTS = False
    QUERY_HINTS = False
    AGGREGATE_FILTER_SUPPORTED = False
    SUPPORTS_TABLE_COPY = False
    COLLATE_IS_FUNC = True
    LIMIT_ONLY_LITERALS = True
    JSON_KEY_VALUE_PAIR_SEP = ","
    INSERT_OVERWRITE = " OVERWRITE INTO"
    STRUCT_DELIMITER = ("(", ")")
    COPY_PARAMS_ARE_WRAPPED = False
    COPY_PARAMS_EQ_REQUIRED = True
    STAR_EXCEPT = "EXCLUDE"
    SUPPORTS_EXPLODING_PROJECTIONS = False
    ARRAY_CONCAT_IS_VAR_LEN = False
    SUPPORTS_CONVERT_TIMEZONE = True
    EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE = False
    SUPPORTS_MEDIAN = True
    ARRAY_SIZE_NAME = "ARRAY_SIZE"
    SUPPORTS_DECODE_CASE = True

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    IS_BOOL_ALLOWED = False
    DIRECTED_JOINS = True
    SUPPORTS_UESCAPE = False
    TRY_SUPPORTED = False

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.ApproxDistinct: rename_func("APPROX_COUNT_DISTINCT"),
        exp.ArgMax: rename_func("MAX_BY"),
        exp.ArgMin: rename_func("MIN_BY"),
        exp.Array: transforms.preprocess([transforms.inherit_struct_field_names]),
        exp.ArrayConcat: array_concat_sql("ARRAY_CAT"),
        exp.ArrayAppend: array_append_sql("ARRAY_APPEND"),
        exp.ArrayPrepend: array_append_sql("ARRAY_PREPEND"),
        exp.ArrayContains: lambda self, e: self.func(
            "ARRAY_CONTAINS",
            e.expression
            if e.args.get("ensure_variant") is False
            else exp.cast(e.expression, exp.DType.VARIANT, copy=False),
            e.this,
        ),
        exp.ArrayPosition: lambda self, e: self.func(
            "ARRAY_POSITION",
            e.expression,
            e.this,
        ),
        exp.ArrayIntersect: rename_func("ARRAY_INTERSECTION"),
        exp.ArrayOverlaps: rename_func("ARRAYS_OVERLAP"),
        exp.AtTimeZone: lambda self, e: self.func("CONVERT_TIMEZONE", e.args.get("zone"), e.this),
        exp.BitwiseOr: rename_func("BITOR"),
        exp.BitwiseXor: rename_func("BITXOR"),
        exp.BitwiseAnd: rename_func("BITAND"),
        exp.BitwiseAndAgg: rename_func("BITANDAGG"),
        exp.BitwiseOrAgg: rename_func("BITORAGG"),
        exp.BitwiseXorAgg: rename_func("BITXORAGG"),
        exp.BitwiseNot: rename_func("BITNOT"),
        exp.BitwiseLeftShift: rename_func("BITSHIFTLEFT"),
        exp.BitwiseRightShift: rename_func("BITSHIFTRIGHT"),
        exp.Create: transforms.preprocess([_flatten_structured_types_unless_iceberg]),
        exp.CurrentTimestamp: lambda self, e: (
            self.func("SYSDATE") if e.args.get("sysdate") else self.function_fallback_sql(e)
        ),
        exp.CurrentSchemas: lambda self, e: self.func("CURRENT_SCHEMAS"),
        exp.Localtime: lambda self, e: (
            self.func("CURRENT_TIME", e.this) if e.this else "CURRENT_TIME"
        ),
        exp.Localtimestamp: lambda self, e: (
            self.func("CURRENT_TIMESTAMP", e.this) if e.this else "CURRENT_TIMESTAMP"
        ),
        exp.DateAdd: date_delta_sql("DATEADD"),
        exp.DateDiff: date_delta_sql("DATEDIFF"),
        exp.DatetimeAdd: date_delta_sql("TIMESTAMPADD"),
        exp.DatetimeDiff: timestampdiff_sql,
        exp.DateStrToDate: datestrtodate_sql,
        exp.Decrypt: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}DECRYPT",
            e.this,
            e.args.get("passphrase"),
            e.args.get("aad"),
            e.args.get("encryption_method"),
        ),
        exp.DecryptRaw: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}DECRYPT_RAW",
            e.this,
            e.args.get("key"),
            e.args.get("iv"),
            e.args.get("aad"),
            e.args.get("encryption_method"),
            e.args.get("aead"),
        ),
        exp.DayOfMonth: rename_func("DAYOFMONTH"),
        exp.DayOfWeek: rename_func("DAYOFWEEK"),
        exp.DayOfWeekIso: rename_func("DAYOFWEEKISO"),
        exp.DayOfYear: rename_func("DAYOFYEAR"),
        exp.DotProduct: rename_func("VECTOR_INNER_PRODUCT"),
        exp.Explode: rename_func("FLATTEN"),
        exp.Extract: lambda self, e: self.func(
            "DATE_PART", map_date_part(e.this, self.dialect), e.expression
        ),
        exp.CosineDistance: rename_func("VECTOR_COSINE_SIMILARITY"),
        exp.EuclideanDistance: rename_func("VECTOR_L2_DISTANCE"),
        exp.HandlerProperty: lambda self, e: f"HANDLER = {self.sql(e, 'this')}",
        exp.FileFormatProperty: lambda self, e: (
            f"FILE_FORMAT=({self.expressions(e, 'expressions', sep=' ')})"
        ),
        exp.FromTimeZone: lambda self, e: self.func(
            "CONVERT_TIMEZONE", e.args.get("zone"), "'UTC'", e.this
        ),
        exp.GenerateSeries: lambda self, e: self.func(
            "ARRAY_GENERATE_RANGE",
            e.args["start"],
            e.args["end"] if e.args.get("is_end_exclusive") else e.args["end"] + 1,
            e.args.get("step"),
        ),
        exp.GetExtract: rename_func("GET"),
        exp.GroupConcat: lambda self, e: groupconcat_sql(self, e, sep=""),
        exp.If: if_sql(name="IFF", false_value="NULL"),
        exp.JSONExtractArray: _json_extract_value_array_sql,
        exp.JSONExtractScalar: lambda self, e: self.func(
            "JSON_EXTRACT_PATH_TEXT", e.this, e.expression
        ),
        exp.JSONKeys: rename_func("OBJECT_KEYS"),
        exp.JSONObject: lambda self, e: self.func("OBJECT_CONSTRUCT_KEEP_NULL", *e.expressions),
        exp.JSONPathRoot: lambda *_: "",
        exp.JSONValueArray: _json_extract_value_array_sql,
        exp.Levenshtein: unsupported_args("ins_cost", "del_cost", "sub_cost")(
            rename_func("EDITDISTANCE")
        ),
        exp.LocationProperty: lambda self, e: f"LOCATION={self.sql(e, 'this')}",
        exp.LogicalAnd: rename_func("BOOLAND_AGG"),
        exp.LogicalOr: rename_func("BOOLOR_AGG"),
        exp.Map: lambda self, e: var_map_sql(self, e, "OBJECT_CONSTRUCT"),
        exp.ManhattanDistance: rename_func("VECTOR_L1_DISTANCE"),
        exp.MakeInterval: no_make_interval_sql,
        exp.Max: max_or_greatest,
        exp.Min: min_or_least,
        exp.ParseJSON: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}PARSE_JSON", e.this
        ),
        exp.ToBinary: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}TO_BINARY", e.this, e.args.get("format")
        ),
        exp.ToBoolean: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}TO_BOOLEAN", e.this
        ),
        exp.ToDouble: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}TO_DOUBLE", e.this, e.args.get("format")
        ),
        exp.ToFile: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}TO_FILE", e.this, e.args.get("path")
        ),
        exp.JSONFormat: rename_func("TO_JSON"),
        exp.PartitionedByProperty: lambda self, e: f"PARTITION BY {self.sql(e, 'this')}",
        exp.PercentileCont: transforms.preprocess([transforms.add_within_group_for_percentiles]),
        exp.PercentileDisc: transforms.preprocess([transforms.add_within_group_for_percentiles]),
        exp.Pivot: transforms.preprocess([_unqualify_pivot_columns]),
        exp.RegexpExtract: _regexpextract_sql,
        exp.RegexpExtractAll: _regexpextract_sql,
        exp.RegexpILike: _regexpilike_sql,
        exp.RowAccessProperty: lambda self, e: self.rowaccessproperty_sql(e),
        exp.Select: transforms.preprocess(
            [
                transforms.eliminate_window_clause,
                transforms.eliminate_distinct_on,
                transforms.explode_projection_to_unnest(),
                transforms.eliminate_semi_and_anti_joins,
                _transform_generate_date_array,
                _qualify_unnested_columns,
                _eliminate_dot_variant_lookup,
            ]
        ),
        exp.SHA: rename_func("SHA1"),
        exp.SHA1Digest: rename_func("SHA1_BINARY"),
        exp.MD5Digest: rename_func("MD5_BINARY"),
        exp.MD5NumberLower64: rename_func("MD5_NUMBER_LOWER64"),
        exp.MD5NumberUpper64: rename_func("MD5_NUMBER_UPPER64"),
        exp.LowerHex: rename_func("TO_CHAR"),
        exp.Skewness: rename_func("SKEW"),
        exp.StarMap: rename_func("OBJECT_CONSTRUCT"),
        exp.StartsWith: rename_func("STARTSWITH"),
        exp.EndsWith: rename_func("ENDSWITH"),
        exp.Rand: lambda self, e: self.func("RANDOM", e.this),
        exp.StrPosition: lambda self, e: strposition_sql(
            self, e, func_name="CHARINDEX", supports_position=True
        ),
        exp.StrToDate: lambda self, e: self.func("DATE", e.this, self.format_time(e)),
        exp.StringToArray: rename_func("STRTOK_TO_ARRAY"),
        exp.Stuff: rename_func("INSERT"),
        exp.StPoint: rename_func("ST_MAKEPOINT"),
        exp.TimeAdd: date_delta_sql("TIMEADD"),
        exp.TimeSlice: lambda self, e: self.func(
            "TIME_SLICE",
            e.this,
            e.expression,
            unit_to_str(e),
            e.args.get("kind"),
        ),
        exp.Timestamp: no_timestamp_sql,
        exp.TimestampAdd: date_delta_sql("TIMESTAMPADD"),
        exp.TimestampDiff: lambda self, e: self.func("TIMESTAMPDIFF", e.unit, e.expression, e.this),
        exp.TimestampTrunc: timestamptrunc_sql(),
        exp.TimeStrToTime: timestrtotime_sql,
        exp.TimeToUnix: lambda self, e: f"EXTRACT(epoch_second FROM {self.sql(e, 'this')})",
        exp.ToArray: rename_func("TO_ARRAY"),
        exp.ToChar: lambda self, e: self.function_fallback_sql(e),
        exp.TsOrDsAdd: date_delta_sql("DATEADD", cast=True),
        exp.TsOrDsDiff: date_delta_sql("DATEDIFF"),
        exp.TsOrDsToDate: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}TO_DATE", e.this, self.format_time(e)
        ),
        exp.TsOrDsToTime: lambda self, e: self.func(
            f"{'TRY_' if e.args.get('safe') else ''}TO_TIME", e.this, self.format_time(e)
        ),
        exp.Unhex: rename_func("HEX_DECODE_BINARY"),
        exp.UnixToTime: lambda self, e: self.func("TO_TIMESTAMP", e.this, e.args.get("scale")),
        exp.Uuid: rename_func("UUID_STRING"),
        exp.VarMap: lambda self, e: var_map_sql(self, e, "OBJECT_CONSTRUCT"),
        exp.Booland: rename_func("BOOLAND"),
        exp.Boolor: rename_func("BOOLOR"),
        exp.WeekOfYear: rename_func("WEEKISO"),
        exp.YearOfWeek: rename_func("YEAROFWEEK"),
        exp.YearOfWeekIso: rename_func("YEAROFWEEKISO"),
        exp.Xor: rename_func("BOOLXOR"),
        exp.ByteLength: rename_func("OCTET_LENGTH"),
        exp.Flatten: rename_func("ARRAY_FLATTEN"),
        exp.ArrayConcatAgg: lambda self, e: self.func("ARRAY_FLATTEN", exp.ArrayAgg(this=e.this)),
        exp.SHA2Digest: lambda self, e: self.func(
            "SHA2_BINARY", e.this, e.args.get("length") or exp.Literal.number(256)
        ),
    }

    def sortarray_sql(self, expression: exp.SortArray) -> str:
        pass

    def nthvalue_sql(self, expression: exp.NthValue) -> str:
        pass

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
    }

    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        exp.DType.BIGDECIMAL: "DOUBLE",
        exp.DType.JSON: "VARIANT",
        exp.DType.NESTED: "OBJECT",
        exp.DType.STRUCT: "OBJECT",
        exp.DType.TEXT: "VARCHAR",
    }

    TOKEN_MAPPING = {
        TokenType.AUTO_INCREMENT: "AUTOINCREMENT",
    }

    PROPERTIES_LOCATION = {
        **generator.Generator.PROPERTIES_LOCATION,
        exp.CredentialsProperty: exp.Properties.Location.POST_WITH,
        exp.LocationProperty: exp.Properties.Location.POST_WITH,
        exp.PartitionedByProperty: exp.Properties.Location.POST_SCHEMA,
        exp.RowAccessProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SetProperty: exp.Properties.Location.UNSUPPORTED,
        exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
    }

    UNSUPPORTED_VALUES_EXPRESSIONS = {
        exp.Map,
        exp.StarMap,
        exp.Struct,
        exp.VarMap,
    }

    RESPECT_IGNORE_NULLS_UNSUPPORTED_EXPRESSIONS = (exp.ArrayAgg,)

    def with_properties(self, properties: exp.Properties) -> str:
        pass

    def values_sql(self, expression: exp.Values, values_as_table: bool = True) -> str:
        pass

    def datatype_sql(self, expression: exp.DataType) -> str:
        # Check if this is a FLOAT type nested inside a VECTOR type
        # VECTOR only accepts FLOAT (not DOUBLE), INT, and STRING as element types
        # https://docs.snowflake.com/en/sql-reference/data-types-vector
        pass

    def tonumber_sql(self, expression: exp.ToNumber) -> str:
        pass

    def timestampfromparts_sql(self, expression: exp.TimestampFromParts) -> str:
        pass

    def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
        if expression.is_type(exp.DType.GEOGRAPHY):
            return self.func("TO_GEOGRAPHY", expression.this)
        if expression.is_type(exp.DType.GEOMETRY):
            return self.func("TO_GEOMETRY", expression.this)

        return super().cast_sql(expression, safe_prefix=safe_prefix)

    def trycast_sql(self, expression: exp.TryCast) -> str:
        value = expression.this

        if value.type is None:
            from sqlglot.optimizer.annotate_types import annotate_types

            value = annotate_types(value, dialect=self.dialect)

        # Snowflake requires that TRY_CAST's value be a string
        # If TRY_CAST is being roundtripped (since Snowflake is the only dialect that sets "requires_string") or
        # if we can deduce that the value is a string, then we can generate TRY_CAST
        if expression.args.get("requires_string") or value.is_type(*exp.DataType.TEXT_TYPES):
            return super().trycast_sql(expression)

        return self.cast_sql(expression)

    def log_sql(self, expression: exp.Log) -> str:
        pass

    def greatest_sql(self, expression: exp.Greatest) -> str:
        pass

    def least_sql(self, expression: exp.Least) -> str:
        pass

    def generator_sql(self, expression: exp.Generator) -> str:
        pass

    def unnest_sql(self, expression: exp.Unnest) -> str:
        pass

    def show_sql(self, expression: exp.Show) -> str:
        terse = "TERSE " if expression.args.get("terse") else ""
        iceberg = "ICEBERG " if expression.args.get("iceberg") else ""
        history = " HISTORY" if expression.args.get("history") else ""
        like = self.sql(expression, "like")
        like = f" LIKE {like}" if like else ""

        scope = self.sql(expression, "scope")
        scope = f" {scope}" if scope else ""

        scope_kind = self.sql(expression, "scope_kind")
        if scope_kind:
            scope_kind = f" IN {scope_kind}"

        starts_with = self.sql(expression, "starts_with")
        if starts_with:
            starts_with = f" STARTS WITH {starts_with}"

        limit = self.sql(expression, "limit")

        from_ = self.sql(expression, "from_")
        if from_:
            from_ = f" FROM {from_}"

        privileges = self.expressions(expression, key="privileges", flat=True)
        privileges = f" WITH PRIVILEGES {privileges}" if privileges else ""

        return f"SHOW {terse}{iceberg}{expression.name}{history}{like}{scope_kind}{scope}{starts_with}{limit}{from_}{privileges}"

    def rowaccessproperty_sql(self, expression: exp.RowAccessProperty) -> str:
        if not expression.this:
            return "ROW ACCESS"
        on = f" ON ({self.expressions(expression, flat=True)})" if expression.expressions else ""
        return f"WITH ROW ACCESS POLICY {self.sql(expression, 'this')}{on}"

    def describe_sql(self, expression: exp.Describe) -> str:
        kind_value = expression.args.get("kind") or "TABLE"

        properties = expression.args.get("properties")
        if properties:
            qualifier = self.expressions(properties, sep=" ")
            kind = f" {qualifier} {kind_value}"
        else:
            kind = f" {kind_value}"

        this = f" {self.sql(expression, 'this')}"
        expressions = self.expressions(expression, flat=True)
        expressions = f" {expressions}" if expressions else ""
        return f"DESCRIBE{kind}{this}{expressions}"

    def generatedasidentitycolumnconstraint_sql(
        self, expression: exp.GeneratedAsIdentityColumnConstraint
    ) -> str:
        start = expression.args.get("start")
        start = f" START {start}" if start else ""
        increment = expression.args.get("increment")
        increment = f" INCREMENT {increment}" if increment else ""

        order = expression.args.get("order")
        if order is not None:
            order_clause = " ORDER" if order else " NOORDER"
        else:
            order_clause = ""

        return f"AUTOINCREMENT{start}{increment}{order_clause}"

    def cluster_sql(self, expression: exp.Cluster) -> str:
        pass

    def struct_sql(self, expression: exp.Struct) -> str:
        pass

    @unsupported_args("weight", "accuracy")
    def approxquantile_sql(self, expression: exp.ApproxQuantile) -> str:
        pass

    def alterset_sql(self, expression: exp.AlterSet) -> str:
        pass

    def strtotime_sql(self, expression: exp.StrToTime):
        # target_type is stored as a DataType instance
        pass

    def timestampsub_sql(self, expression: exp.TimestampSub):
        pass

    def jsonextract_sql(self, expression: exp.JSONExtract):
        pass

    def timetostr_sql(self, expression: exp.TimeToStr) -> str:
        pass

    def datesub_sql(self, expression: exp.DateSub) -> str:
        pass

    def select_sql(self, expression: exp.Select) -> str:
        pass

    def createable_sql(self, expression: exp.Create, locations: defaultdict) -> str:
        pass

    def arrayagg_sql(self, expression: exp.ArrayAgg) -> str:
        pass

    def arraytostring_sql(self, expression: exp.ArrayToString) -> str:
        pass

    def array_sql(self, expression: exp.Array) -> str:
        pass

    def currentdate_sql(self, expression: exp.CurrentDate) -> str:
        pass

    def dot_sql(self, expression: exp.Dot) -> str:
        pass

    def modelattribute_sql(self, expression: exp.ModelAttribute) -> str:
        pass

    def format_sql(self, expression: exp.Format) -> str:
        pass

    def splitpart_sql(self, expression: exp.SplitPart) -> str:
        # Set part_index to 1 if missing
        pass

    def uniform_sql(self, expression: exp.Uniform) -> str:
        pass

    def window_sql(self, expression: exp.Window) -> str:
        spec = expression.args.get("spec")
        this = expression.this

        if (
            (
                isinstance(this, RANKING_WINDOW_FUNCTIONS_WITH_FRAME)
                or (
                    isinstance(this, (exp.RespectNulls, exp.IgnoreNulls))
                    and isinstance(this.this, RANKING_WINDOW_FUNCTIONS_WITH_FRAME)
                )
            )
            and spec
            and (
                spec.text("kind").upper() == "ROWS"
                and spec.text("start").upper() == "UNBOUNDED"
                and spec.text("start_side").upper() == "PRECEDING"
                and spec.text("end").upper() == "UNBOUNDED"
                and spec.text("end_side").upper() == "FOLLOWING"
            )
        ):
            # omit the default window from window ranking functions
            expression.set("spec", None)
        return super().window_sql(expression)
