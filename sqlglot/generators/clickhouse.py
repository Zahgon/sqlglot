from __future__ import annotations

import datetime
import typing as t

from sqlglot import exp, generator
from sqlglot.dialects.dialect import (
    arg_max_or_min_no_count,
    inline_array_sql,
    jarowinkler_similarity,
    json_extract_segments,
    json_path_key_only_name,
    length_or_char_length_sql,
    no_pivot_sql,
    rename_func,
    remove_from_array_using_filter,
    sha256_sql,
    strposition_sql,
    var_map_sql,
    unit_to_str,
    unit_to_var,
    trim_sql,
    sha2_digest_sql,
)
from sqlglot.generator import unsupported_args
from sqlglot.helper import is_int
from collections import defaultdict

DATETIME_DELTA = t.Union[exp.DateAdd, exp.DateDiff, exp.DateSub, exp.TimestampSub, exp.TimestampAdd]


def _unix_to_time_sql(self: ClickHouseGenerator, expression: exp.UnixToTime) -> str:
    scale = expression.args.get("scale")
    timestamp = expression.this

    if scale in (None, exp.UnixToTime.SECONDS):
        return self.func("fromUnixTimestamp", exp.cast(timestamp, exp.DType.BIGINT))
    if scale == exp.UnixToTime.MILLIS:
        return self.func("fromUnixTimestamp64Milli", exp.cast(timestamp, exp.DType.BIGINT))
    if scale == exp.UnixToTime.MICROS:
        return self.func("fromUnixTimestamp64Micro", exp.cast(timestamp, exp.DType.BIGINT))
    if scale == exp.UnixToTime.NANOS:
        return self.func("fromUnixTimestamp64Nano", exp.cast(timestamp, exp.DType.BIGINT))

    return self.func(
        "fromUnixTimestamp",
        exp.cast(exp.Div(this=timestamp, expression=exp.func("POW", 10, scale)), exp.DType.BIGINT),
    )


def _lower_func(sql: str) -> str:
    pass


def _quantile_sql(self: ClickHouseGenerator, expression: exp.Quantile) -> str:
    pass


def _datetime_delta_sql(name: str) -> t.Callable[[generator.Generator, DATETIME_DELTA], str]:
    def _delta_sql(self: generator.Generator, expression: DATETIME_DELTA) -> str:
        pass

    return _delta_sql


def _timestrtotime_sql(self: ClickHouseGenerator, expression: exp.TimeStrToTime):
    pass


def _map_sql(self: ClickHouseGenerator, expression: exp.Map | exp.VarMap) -> str:
    pass


def _json_cast_sql(self: ClickHouseGenerator, expression: exp.JSONCast) -> str:
    pass


class ClickHouseGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    QUERY_HINTS = False
    STRUCT_DELIMITER = ("(", ")")
    NVL2_SUPPORTED = False
    TABLESAMPLE_REQUIRES_PARENS = False
    TABLESAMPLE_SIZE_IS_ROWS = False
    TABLESAMPLE_KEYWORDS = "SAMPLE"
    LAST_DAY_SUPPORTS_DATE_PART = False
    CAN_IMPLEMENT_ARRAY_ANY = True
    SUPPORTS_TO_NUMBER = False
    JOIN_HINTS = False
    TABLE_HINTS = False
    GROUPINGS_SEP = ""
    SET_OP_MODIFIERS = False
    ARRAY_SIZE_NAME = "LENGTH"
    WRAP_DERIVED_VALUES = False

    STRING_TYPE_MAPPING: t.ClassVar = {
        exp.DType.BLOB: "String",
        exp.DType.CHAR: "String",
        exp.DType.LONGBLOB: "String",
        exp.DType.LONGTEXT: "String",
        exp.DType.MEDIUMBLOB: "String",
        exp.DType.MEDIUMTEXT: "String",
        exp.DType.TINYBLOB: "String",
        exp.DType.TINYTEXT: "String",
        exp.DType.TEXT: "String",
        exp.DType.VARBINARY: "String",
        exp.DType.VARCHAR: "String",
    }

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
    }

    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        exp.DType.BLOB: "String",
        exp.DType.CHAR: "String",
        exp.DType.LONGBLOB: "String",
        exp.DType.LONGTEXT: "String",
        exp.DType.MEDIUMBLOB: "String",
        exp.DType.MEDIUMTEXT: "String",
        exp.DType.TINYBLOB: "String",
        exp.DType.TINYTEXT: "String",
        exp.DType.TEXT: "String",
        exp.DType.VARBINARY: "String",
        exp.DType.VARCHAR: "String",
        exp.DType.ARRAY: "Array",
        exp.DType.BOOLEAN: "Bool",
        exp.DType.BIGINT: "Int64",
        exp.DType.DATE32: "Date32",
        exp.DType.DATETIME: "DateTime",
        exp.DType.DATETIME2: "DateTime",
        exp.DType.SMALLDATETIME: "DateTime",
        exp.DType.DATETIME64: "DateTime64",
        exp.DType.DECIMAL: "Decimal",
        exp.DType.DECIMAL32: "Decimal32",
        exp.DType.DECIMAL64: "Decimal64",
        exp.DType.DECIMAL128: "Decimal128",
        exp.DType.DECIMAL256: "Decimal256",
        exp.DType.TIMESTAMP: "DateTime",
        exp.DType.TIMESTAMPNTZ: "DateTime",
        exp.DType.TIMESTAMPTZ: "DateTime",
        exp.DType.DOUBLE: "Float64",
        exp.DType.ENUM: "Enum",
        exp.DType.ENUM8: "Enum8",
        exp.DType.ENUM16: "Enum16",
        exp.DType.FIXEDSTRING: "FixedString",
        exp.DType.FLOAT: "Float32",
        exp.DType.INT: "Int32",
        exp.DType.MEDIUMINT: "Int32",
        exp.DType.INT128: "Int128",
        exp.DType.INT256: "Int256",
        exp.DType.LOWCARDINALITY: "LowCardinality",
        exp.DType.MAP: "Map",
        exp.DType.NESTED: "Nested",
        exp.DType.NOTHING: "Nothing",
        exp.DType.SMALLINT: "Int16",
        exp.DType.STRUCT: "Tuple",
        exp.DType.TINYINT: "Int8",
        exp.DType.UBIGINT: "UInt64",
        exp.DType.UINT: "UInt32",
        exp.DType.UINT128: "UInt128",
        exp.DType.UINT256: "UInt256",
        exp.DType.USMALLINT: "UInt16",
        exp.DType.UTINYINT: "UInt8",
        exp.DType.IPV4: "IPv4",
        exp.DType.IPV6: "IPv6",
        exp.DType.POINT: "Point",
        exp.DType.RING: "Ring",
        exp.DType.LINESTRING: "LineString",
        exp.DType.MULTILINESTRING: "MultiLineString",
        exp.DType.POLYGON: "Polygon",
        exp.DType.MULTIPOLYGON: "MultiPolygon",
        exp.DType.AGGREGATEFUNCTION: "AggregateFunction",
        exp.DType.SIMPLEAGGREGATEFUNCTION: "SimpleAggregateFunction",
        exp.DType.DYNAMIC: "Dynamic",
    }

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.AnyValue: rename_func("any"),
        exp.ApproxDistinct: rename_func("uniq"),
        exp.ArrayDistinct: rename_func("arrayDistinct"),
        exp.ArrayConcat: rename_func("arrayConcat"),
        exp.ArrayContains: rename_func("has"),
        exp.ArrayFilter: lambda self, e: self.func("arrayFilter", e.expression, e.this),
        exp.ArrayRemove: remove_from_array_using_filter,
        exp.ArrayReverse: rename_func("arrayReverse"),
        exp.ArraySlice: rename_func("arraySlice"),
        exp.ArraySum: rename_func("arraySum"),
        exp.ArrayMax: rename_func("arrayMax"),
        exp.ArrayMin: rename_func("arrayMin"),
        exp.ArgMax: arg_max_or_min_no_count("argMax"),
        exp.ArgMin: arg_max_or_min_no_count("argMin"),
        exp.Array: inline_array_sql,
        exp.CityHash64: rename_func("cityHash64"),
        exp.CastToStrType: rename_func("CAST"),
        exp.CurrentDatabase: rename_func("CURRENT_DATABASE"),
        exp.CurrentSchemas: rename_func("CURRENT_SCHEMAS"),
        exp.CountIf: rename_func("countIf"),
        exp.CosineDistance: rename_func("cosineDistance"),
        exp.CompressColumnConstraint: lambda self, e: (
            f"CODEC({self.expressions(e, key='this', flat=True)})"
        ),
        exp.ComputedColumnConstraint: lambda self, e: (
            f"{'MATERIALIZED' if e.args.get('persisted') else 'ALIAS'} {self.sql(e, 'this')}"
        ),
        exp.CurrentDate: lambda self, e: self.func("CURRENT_DATE"),
        exp.CurrentVersion: rename_func("VERSION"),
        exp.DateAdd: _datetime_delta_sql("DATE_ADD"),
        exp.DateDiff: _datetime_delta_sql("DATE_DIFF"),
        exp.DateStrToDate: rename_func("toDate"),
        exp.DateSub: _datetime_delta_sql("DATE_SUB"),
        exp.Explode: rename_func("arrayJoin"),
        exp.FarmFingerprint: rename_func("farmFingerprint64"),
        exp.Final: lambda self, e: f"{self.sql(e, 'this')} FINAL",
        exp.IsNan: rename_func("isNaN"),
        exp.JarowinklerSimilarity: jarowinkler_similarity("jaroWinklerSimilarity"),
        exp.JSONCast: _json_cast_sql,
        exp.JSONExtract: json_extract_segments("JSONExtractString", quoted_index=False),
        exp.JSONExtractScalar: json_extract_segments("JSONExtractString", quoted_index=False),
        exp.JSONPathKey: json_path_key_only_name,
        exp.JSONPathRoot: lambda *_: "",
        exp.Length: length_or_char_length_sql,
        exp.Map: _map_sql,
        exp.Median: rename_func("median"),
        exp.Nullif: rename_func("nullIf"),
        exp.PartitionedByProperty: lambda self, e: f"PARTITION BY {self.sql(e, 'this')}",
        exp.Pivot: no_pivot_sql,
        exp.Quantile: _quantile_sql,
        exp.RegexpLike: lambda self, e: self.func("match", e.this, e.expression),
        exp.Rand: rename_func("randCanonical"),
        exp.StartsWith: rename_func("startsWith"),
        exp.Struct: rename_func("tuple"),
        exp.Trunc: rename_func("trunc"),
        exp.EndsWith: rename_func("endsWith"),
        exp.EuclideanDistance: rename_func("L2Distance"),
        exp.StrPosition: lambda self, e: strposition_sql(
            self,
            e,
            func_name="POSITION",
            supports_position=True,
            use_ansi_position=False,
        ),
        exp.TimeToStr: lambda self, e: self.func(
            "formatDateTime",
            e.this.this if isinstance(e.this, exp.TsOrDsToTimestamp) else e.this,
            self.format_time(e),
            e.args.get("zone"),
        ),
        exp.TimeStrToTime: _timestrtotime_sql,
        exp.TimestampAdd: _datetime_delta_sql("TIMESTAMP_ADD"),
        exp.TimestampSub: _datetime_delta_sql("TIMESTAMP_SUB"),
        exp.Typeof: rename_func("toTypeName"),
        exp.VarMap: _map_sql,
        exp.Xor: lambda self, e: self.func("xor", e.this, e.expression, *e.expressions),
        exp.MD5Digest: rename_func("MD5"),
        exp.MD5: lambda self, e: self.func("LOWER", self.func("HEX", self.func("MD5", e.this))),
        exp.SHA: rename_func("SHA1"),
        exp.SHA1Digest: rename_func("SHA1"),
        exp.SHA2: sha256_sql,
        exp.SHA2Digest: sha2_digest_sql,
        exp.Split: lambda self, e: self.func(
            "splitByString", e.args.get("expression"), e.this, e.args.get("limit")
        ),
        exp.RegexpSplit: lambda self, e: self.func(
            "splitByRegexp", e.args.get("expression"), e.this, e.args.get("limit")
        ),
        exp.UnixToTime: _unix_to_time_sql,
        exp.Trim: lambda self, e: trim_sql(self, e, default_trim_type="BOTH"),
        exp.Variance: rename_func("varSamp"),
        exp.SchemaCommentProperty: lambda self, e: self.naked_property(e),
        exp.Stddev: rename_func("stddevSamp"),
        exp.Chr: rename_func("CHAR"),
        exp.Lag: lambda self, e: self.func(
            "lagInFrame", e.this, e.args.get("offset"), e.args.get("default")
        ),
        exp.Lead: lambda self, e: self.func(
            "leadInFrame", e.this, e.args.get("offset"), e.args.get("default")
        ),
        exp.Levenshtein: unsupported_args("ins_cost", "del_cost", "sub_cost", "max_dist")(
            rename_func("editDistance")
        ),
        exp.ParseDatetime: rename_func("parseDateTime"),
    }

    PROPERTIES_LOCATION = {
        **generator.Generator.PROPERTIES_LOCATION,
        exp.DefinerProperty: exp.Properties.Location.POST_SCHEMA,
        exp.OnCluster: exp.Properties.Location.POST_NAME,
        exp.PartitionedByProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ToTableProperty: exp.Properties.Location.POST_NAME,
        exp.UuidProperty: exp.Properties.Location.POST_NAME,
        exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
    }

    # There's no list in docs, but it can be found in Clickhouse code
    # see `ClickHouse/src/Parsers/ParserCreate*.cpp`
    ON_CLUSTER_TARGETS = {
        "SCHEMA",  # Transpiled CREATE SCHEMA may have OnCluster property set
        "DATABASE",
        "TABLE",
        "VIEW",
        "DICTIONARY",
        "INDEX",
        "FUNCTION",
        "NAMED COLLECTION",
    }

    # https://clickhouse.com/docs/en/sql-reference/data-types/nullable
    NON_NULLABLE_TYPES = {
        exp.DType.ARRAY,
        exp.DType.MAP,
        exp.DType.STRUCT,
        exp.DType.POINT,
        exp.DType.RING,
        exp.DType.LINESTRING,
        exp.DType.MULTILINESTRING,
        exp.DType.POLYGON,
        exp.DType.MULTIPOLYGON,
    }

    def groupconcat_sql(self, expression: exp.GroupConcat) -> str:
        this = expression.this
        separator = expression.args.get("separator")

        if isinstance(this, exp.Limit) and this.this:
            limit = this
            this = limit.this.pop()
            return self.sql(
                exp.ParameterizedAgg(
                    this="groupConcat",
                    params=[this],
                    expressions=[separator, limit.expression],
                )
            )

        if separator:
            return self.sql(
                exp.ParameterizedAgg(
                    this="groupConcat",
                    params=[this],
                    expressions=[separator],
                )
            )

        return self.func("groupConcat", this)

    def offset_sql(self, expression: exp.Offset) -> str:
        pass

    def strtodate_sql(self, expression: exp.StrToDate) -> str:
        pass

    def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
        this = expression.this

        if isinstance(this, exp.StrToDate) and expression.to == exp.DType.DATETIME.into_expr():
            return self.sql(this)

        return super().cast_sql(expression, safe_prefix=safe_prefix)

    def trycast_sql(self, expression: exp.TryCast) -> str:
        dtype = expression.to
        if not dtype.is_type(*self.NON_NULLABLE_TYPES, check_nullable=True):
            # Casting x into Nullable(T) appears to behave similarly to TRY_CAST(x AS T)
            dtype.set("nullable", True)

        return super().cast_sql(expression)

    def _jsonpathsubscript_sql(self, expression: exp.JSONPathSubscript) -> str:
        this = self.json_path_part(expression.this)
        return str(int(this) + 1) if is_int(this) else this

    def likeproperty_sql(self, expression: exp.LikeProperty) -> str:
        pass

    def _any_to_has(
        self,
        expression: exp.EQ | exp.NEQ,
        default: t.Callable[[t.Any], str],
        prefix: str = "",
    ) -> str:
        pass

    def eq_sql(self, expression: exp.EQ) -> str:
        pass

    def neq_sql(self, expression: exp.NEQ) -> str:
        pass

    def regexpilike_sql(self, expression: exp.RegexpILike) -> str:
        # Manually add a flag to make the search case-insensitive
        pass

    def datatype_sql(self, expression: exp.DataType) -> str:
        # String is the standard ClickHouse type, every other variant is just an alias.
        # Additionally, any supplied length parameter will be ignored.
        #
        # https://clickhouse.com/docs/en/sql-reference/data-types/string
        pass

    def cte_sql(self, expression: exp.CTE) -> str:
        pass

    def after_limit_modifiers(self, expression: exp.Expr) -> list[str]:
        return super().after_limit_modifiers(expression) + [
            (
                self.seg("SETTINGS ") + self.expressions(expression, key="settings", flat=True)
                if expression.args.get("settings")
                else ""
            ),
            (
                self.seg("FORMAT ") + self.sql(expression, "format")
                if expression.args.get("format")
                else ""
            ),
        ]

    def placeholder_sql(self, expression: exp.Placeholder) -> str:
        pass

    def oncluster_sql(self, expression: exp.OnCluster) -> str:
        pass

    def createable_sql(self, expression: exp.Create, locations: defaultdict) -> str:
        pass

    def create_sql(self, expression: exp.Create) -> str:
        # The comment property comes last in CTAS statements, i.e. after the query
        pass

    def prewhere_sql(self, expression: exp.PreWhere) -> str:
        pass

    def indexcolumnconstraint_sql(self, expression: exp.IndexColumnConstraint) -> str:
        pass

    def partition_sql(self, expression: exp.Partition) -> str:
        pass

    def partitionid_sql(self, expression: exp.PartitionId) -> str:
        pass

    def replacepartition_sql(self, expression: exp.ReplacePartition) -> str:
        pass

    def projectiondef_sql(self, expression: exp.ProjectionDef) -> str:
        pass

    def nestedjsonselect_sql(self, expression: exp.NestedJSONSelect) -> str:
        pass

    def is_sql(self, expression: exp.Is) -> str:
        pass

    def in_sql(self, expression: exp.In) -> str:
        pass

    def not_sql(self, expression: exp.Not) -> str:
        pass

    def values_sql(self, expression: exp.Values, values_as_table: bool = True) -> str:
        # If the VALUES clause contains tuples of expressions, we need to treat it
        # as a table since Clickhouse will automatically alias it as such.
        pass

    def timestamptrunc_sql(self, expression: exp.TimestampTrunc) -> str:
        unit = unit_to_str(expression)
        # https://clickhouse.com/docs/whats-new/changelog/2023#improvement
        if self.dialect.version < (23, 12) and unit and unit.is_string:
            unit = exp.Literal.string(unit.name.lower())
        return self.func("dateTrunc", unit, expression.this, expression.args.get("zone"))
