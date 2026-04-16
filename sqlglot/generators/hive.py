from __future__ import annotations

import re
from functools import partial

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    DATE_ADD_OR_SUB,
    approx_count_distinct_sql,
    arg_max_or_min_no_count,
    datestrtodate_sql,
    if_sql,
    is_parse_json,
    left_to_substring_sql,
    max_or_greatest,
    min_or_least,
    no_ilike_sql,
    no_recursive_cte_sql,
    no_trycast_sql,
    regexp_extract_sql,
    regexp_replace_sql,
    rename_func,
    right_to_substring_sql,
    strposition_sql,
    struct_extract_sql,
    time_format,
    timestrtotime_sql,
    trim_sql,
    unit_to_str,
    var_map_sql,
    sequence_sql,
    property_sql,
)
from sqlglot.transforms import (
    remove_unique_constraints,
    ctas_with_tmp_tables_to_create_tmp_view,
    preprocess,
    move_schema_columns_to_partitioned_by,
)
from sqlglot.generator import unsupported_args

# These constants are duplicated from the Hive dialect class to avoid circular imports.
# They must be kept in sync with Hive.TIME_FORMAT, Hive.DATE_FORMAT, Hive.DATEINT_FORMAT.
HIVE_TIME_FORMAT = "'yyyy-MM-dd HH:mm:ss'"
HIVE_DATE_FORMAT = "'yyyy-MM-dd'"
HIVE_DATEINT_FORMAT = "'yyyyMMdd'"

# (FuncType, Multiplier)
DATE_DELTA_INTERVAL = {
    "YEAR": ("ADD_MONTHS", 12),
    "MONTH": ("ADD_MONTHS", 1),
    "QUARTER": ("ADD_MONTHS", 3),
    "WEEK": ("DATE_ADD", 7),
    "DAY": ("DATE_ADD", 1),
}

TIME_DIFF_FACTOR = {
    "MILLISECOND": " * 1000",
    "SECOND": "",
    "MINUTE": " / 60",
    "HOUR": " / 3600",
}

DIFF_MONTH_SWITCH = ("YEAR", "QUARTER", "MONTH")

HIVE_TS_OR_DS_EXPRESSIONS: tuple[type[exp.Expr], ...] = (
    exp.DateDiff,
    exp.Day,
    exp.Month,
    exp.Year,
)


def _add_date_sql(self: HiveGenerator, expression: DATE_ADD_OR_SUB) -> str:
    pass


def _date_diff_sql(self: HiveGenerator, expression: exp.DateDiff | exp.TsOrDsDiff) -> str:
    pass


def _json_format_sql(self: HiveGenerator, expression: exp.JSONFormat) -> str:
    pass


@generator.unsupported_args(("expression", "Hive's SORT_ARRAY does not support a comparator."))
def _array_sort_sql(self: HiveGenerator, expression: exp.ArraySort) -> str:
    pass


def _str_to_unix_sql(self: HiveGenerator, expression: exp.StrToUnix) -> str:
    pass


def _unix_to_time_sql(self: HiveGenerator, expression: exp.UnixToTime) -> str:
    timestamp = self.sql(expression, "this")
    scale = expression.args.get("scale")
    if scale in (None, exp.UnixToTime.SECONDS):
        return rename_func("FROM_UNIXTIME")(self, expression)

    return f"FROM_UNIXTIME({timestamp} / POW(10, {scale}))"


def _str_to_date_sql(self: HiveGenerator, expression: exp.StrToDate) -> str:
    pass


def _str_to_time_sql(self: HiveGenerator, expression: exp.StrToTime) -> str:
    this = self.sql(expression, "this")
    time_format = self.format_time(expression)
    if time_format not in (HIVE_TIME_FORMAT, HIVE_DATE_FORMAT):
        this = f"FROM_UNIXTIME(UNIX_TIMESTAMP({this}, {time_format}))"
    return f"CAST({this} AS TIMESTAMP)"


def _to_date_sql(self: HiveGenerator, expression: exp.TsOrDsToDate) -> str:
    pass


class HiveGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False
    LIMIT_FETCH = "LIMIT"
    TABLESAMPLE_WITH_METHOD = False
    JOIN_HINTS = False
    TABLE_HINTS = False
    QUERY_HINTS = False
    INDEX_ON = "ON TABLE"
    EXTRACT_ALLOWS_QUOTES = False
    NVL2_SUPPORTED = False
    LAST_DAY_SUPPORTS_DATE_PART = False
    JSON_PATH_SINGLE_QUOTE_ESCAPE = True
    SAFE_JSON_PATH_KEY_RE = re.compile(r"^[_\-a-zA-Z][\-\w]*$")
    SUPPORTS_TO_NUMBER = False
    WITH_PROPERTIES_PREFIX = "TBLPROPERTIES"
    PARSE_JSON_NAME: str | None = None
    PAD_FILL_PATTERN_IS_REQUIRED = True
    SUPPORTS_MEDIAN = False
    ARRAY_SIZE_NAME = "SIZE"
    ALTER_SET_TYPE = ""

    EXPRESSIONS_WITHOUT_NESTED_CTES = {
        exp.Insert,
        exp.Select,
        exp.Subquery,
        exp.SetOperation,
    }

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
        exp.JSONPathWildcard,
    }

    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        exp.DType.BIT: "BOOLEAN",
        exp.DType.BLOB: "BINARY",
        exp.DType.DATETIME: "TIMESTAMP",
        exp.DType.ROWVERSION: "BINARY",
        exp.DType.TEXT: "STRING",
        exp.DType.TIME: "TIMESTAMP",
        exp.DType.TIMESTAMPNTZ: "TIMESTAMP",
        exp.DType.TIMESTAMPTZ: "TIMESTAMP",
        exp.DType.UTINYINT: "SMALLINT",
        exp.DType.VARBINARY: "BINARY",
    }

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.Property: property_sql,
        exp.AnyValue: rename_func("FIRST"),
        exp.ApproxDistinct: approx_count_distinct_sql,
        exp.ArgMax: arg_max_or_min_no_count("MAX_BY"),
        exp.ArgMin: arg_max_or_min_no_count("MIN_BY"),
        exp.Array: transforms.preprocess([transforms.inherit_struct_field_names]),
        exp.ArrayConcat: rename_func("CONCAT"),
        exp.ArrayToString: lambda self, e: self.func("CONCAT_WS", e.expression, e.this),
        exp.ArraySort: _array_sort_sql,
        exp.With: no_recursive_cte_sql,
        exp.DateAdd: _add_date_sql,
        exp.DateDiff: _date_diff_sql,
        exp.DateStrToDate: datestrtodate_sql,
        exp.DateSub: _add_date_sql,
        exp.DateToDi: lambda self, e: (
            f"CAST(DATE_FORMAT({self.sql(e, 'this')}, {HIVE_DATEINT_FORMAT}) AS INT)"
        ),
        exp.DiToDate: lambda self, e: (
            f"TO_DATE(CAST({self.sql(e, 'this')} AS STRING), {HIVE_DATEINT_FORMAT})"
        ),
        exp.StorageHandlerProperty: lambda self, e: f"STORED BY {self.sql(e, 'this')}",
        exp.FromBase64: rename_func("UNBASE64"),
        exp.GenerateSeries: sequence_sql,
        exp.GenerateDateArray: sequence_sql,
        exp.If: if_sql(),
        exp.ILike: no_ilike_sql,
        exp.IntDiv: lambda self, e: self.binary(e, "DIV"),
        exp.IsNan: rename_func("ISNAN"),
        exp.JSONExtract: lambda self, e: self.func("GET_JSON_OBJECT", e.this, e.expression),
        exp.JSONExtractScalar: lambda self, e: self.func("GET_JSON_OBJECT", e.this, e.expression),
        exp.JSONFormat: _json_format_sql,
        exp.Left: left_to_substring_sql,
        exp.Map: var_map_sql,
        exp.Max: max_or_greatest,
        exp.MD5Digest: lambda self, e: self.func("UNHEX", self.func("MD5", e.this)),
        exp.Min: min_or_least,
        exp.MonthsBetween: lambda self, e: self.func("MONTHS_BETWEEN", e.this, e.expression),
        exp.NotNullColumnConstraint: lambda _, e: "" if e.args.get("allow_null") else "NOT NULL",
        exp.VarMap: var_map_sql,
        exp.Create: preprocess(
            [
                remove_unique_constraints,
                ctas_with_tmp_tables_to_create_tmp_view,
                move_schema_columns_to_partitioned_by,
            ]
        ),
        exp.Quantile: rename_func("PERCENTILE"),
        exp.ApproxQuantile: rename_func("PERCENTILE_APPROX"),
        exp.RegexpExtract: regexp_extract_sql,
        exp.RegexpExtractAll: regexp_extract_sql,
        exp.RegexpReplace: regexp_replace_sql,
        exp.RegexpLike: lambda self, e: self.binary(e, "RLIKE"),
        exp.RegexpSplit: rename_func("SPLIT"),
        exp.Right: right_to_substring_sql,
        exp.SchemaCommentProperty: lambda self, e: self.naked_property(e),
        exp.ArrayUniqueAgg: rename_func("COLLECT_SET"),
        exp.Split: lambda self, e: self.func(
            "SPLIT", e.this, self.func("CONCAT", "'\\\\Q'", e.expression, "'\\\\E'")
        ),
        exp.Select: transforms.preprocess(
            [
                transforms.eliminate_qualify,
                transforms.eliminate_distinct_on,
                partial(transforms.unnest_to_explode, unnest_using_arrays_zip=False),
                transforms.any_to_exists,
            ]
        ),
        exp.StrPosition: lambda self, e: strposition_sql(
            self, e, func_name="LOCATE", supports_position=True
        ),
        exp.StrToDate: _str_to_date_sql,
        exp.StrToTime: _str_to_time_sql,
        exp.StrToUnix: _str_to_unix_sql,
        exp.StructExtract: struct_extract_sql,
        exp.StarMap: rename_func("MAP"),
        exp.Table: transforms.preprocess([transforms.unnest_generate_series]),
        exp.TimeStrToDate: rename_func("TO_DATE"),
        exp.TimeStrToTime: timestrtotime_sql,
        exp.TimeStrToUnix: rename_func("UNIX_TIMESTAMP"),
        exp.TimestampTrunc: lambda self, e: self.func("TRUNC", e.this, unit_to_str(e)),
        exp.TimeToUnix: rename_func("UNIX_TIMESTAMP"),
        exp.ToBase64: rename_func("BASE64"),
        exp.TsOrDiToDi: lambda self, e: (
            f"CAST(SUBSTR(REPLACE(CAST({self.sql(e, 'this')} AS STRING), '-', ''), 1, 8) AS INT)"
        ),
        exp.TsOrDsAdd: _add_date_sql,
        exp.TsOrDsDiff: _date_diff_sql,
        exp.TsOrDsToDate: _to_date_sql,
        exp.TryCast: no_trycast_sql,
        exp.Trim: trim_sql,
        exp.Unicode: rename_func("ASCII"),
        exp.UnixToStr: lambda self, e: self.func(
            "FROM_UNIXTIME", e.this, time_format("hive")(self, e)
        ),
        exp.UnixToTime: _unix_to_time_sql,
        exp.UnixToTimeStr: rename_func("FROM_UNIXTIME"),
        exp.Unnest: rename_func("EXPLODE"),
        exp.PartitionedByProperty: lambda self, e: f"PARTITIONED BY {self.sql(e, 'this')}",
        exp.NumberToStr: rename_func("FORMAT_NUMBER"),
        exp.National: lambda self, e: self.national_sql(e, prefix=""),
        exp.ClusteredColumnConstraint: lambda self, e: (
            f"({self.expressions(e, 'this', indent=False)})"
        ),
        exp.NonClusteredColumnConstraint: lambda self, e: (
            f"({self.expressions(e, 'this', indent=False)})"
        ),
        exp.NotForReplicationColumnConstraint: lambda *_: "",
        exp.OnProperty: lambda *_: "",
        exp.PartitionedByBucket: lambda self, e: self.func("BUCKET", e.expression, e.this),
        exp.PartitionByTruncate: lambda self, e: self.func("TRUNCATE", e.expression, e.this),
        exp.PrimaryKeyColumnConstraint: lambda *_: "PRIMARY KEY",
        exp.WeekOfYear: rename_func("WEEKOFYEAR"),
        exp.DayOfMonth: rename_func("DAYOFMONTH"),
        exp.DayOfWeek: rename_func("DAYOFWEEK"),
        exp.Levenshtein: unsupported_args("ins_cost", "del_cost", "sub_cost", "max_dist")(
            rename_func("LEVENSHTEIN")
        ),
    }

    PROPERTIES_LOCATION = {
        **generator.Generator.PROPERTIES_LOCATION,
        exp.FileFormatProperty: exp.Properties.Location.POST_SCHEMA,
        exp.PartitionedByProperty: exp.Properties.Location.POST_SCHEMA,
        exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
        exp.WithDataProperty: exp.Properties.Location.UNSUPPORTED,
    }

    TS_OR_DS_EXPRESSIONS = HIVE_TS_OR_DS_EXPRESSIONS

    IGNORE_NULLS_FUNCS = (exp.First, exp.Last, exp.FirstValue, exp.LastValue)

    def ignorenulls_sql(self, expression: exp.IgnoreNulls) -> str:
        pass

    def unnest_sql(self, expression: exp.Unnest) -> str:
        pass

    def _jsonpathkey_sql(self, expression: exp.JSONPathKey) -> str:
        if isinstance(expression.this, exp.JSONPathWildcard):
            self.unsupported("Unsupported wildcard in JSONPathKey expression")
            return ""

        return super()._jsonpathkey_sql(expression)

    def parameter_sql(self, expression: exp.Parameter) -> str:
        pass

    def schema_sql(self, expression: exp.Schema) -> str:
        pass

    def constraint_sql(self, expression: exp.Constraint) -> str:
        pass

    def rowformatserdeproperty_sql(self, expression: exp.RowFormatSerdeProperty) -> str:
        pass

    def arrayagg_sql(self, expression: exp.ArrayAgg) -> str:
        pass

    # Hive/Spark lack native numeric TRUNC. CAST to BIGINT truncates toward zero (not rounds).
    # Potential enhancement: a TRUNC_TEMPLATE using FLOOR/CEIL with scale (Spark 3.3+)
    # could preserve decimals: CASE WHEN x >= 0 THEN FLOOR(x, d) ELSE CEIL(x, d) END
    @unsupported_args("decimals")
    def trunc_sql(self, expression: exp.Trunc) -> str:
        pass

    def datatype_sql(self, expression: exp.DataType) -> str:
        pass

    def version_sql(self, expression: exp.Version) -> str:
        pass

    def struct_sql(self, expression: exp.Struct) -> str:
        pass

    def columndef_sql(self, expression: exp.ColumnDef, sep: str = " ") -> str:
        pass

    def altercolumn_sql(self, expression: exp.AlterColumn) -> str:
        pass

    def renamecolumn_sql(self, expression: exp.RenameColumn) -> str:
        pass

    def alterset_sql(self, expression: exp.AlterSet) -> str:
        pass

    def serdeproperties_sql(self, expression: exp.SerdeProperties) -> str:
        pass

    def exists_sql(self, expression: exp.Exists) -> str:
        pass

    def timetostr_sql(self, expression: exp.TimeToStr) -> str:
        pass

    def usingproperty_sql(self, expression: exp.UsingProperty) -> str:
        pass

    def fileformatproperty_sql(self, expression: exp.FileFormatProperty) -> str:
        pass
