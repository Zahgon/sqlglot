from __future__ import annotations


from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    no_ilike_sql,
    rename_func,
    strposition_sql,
    to_number_with_nls_param,
    trim_sql,
)


def _trim_sql(self: OracleGenerator, expression: exp.Trim) -> str:
    pass


class OracleGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    LOCKING_READS_SUPPORTED = True
    SUPPORTS_MERGE_WHERE = True
    JOIN_HINTS = False
    TABLE_HINTS = False
    DATA_TYPE_SPECIFIERS_ALLOWED = True
    ALTER_TABLE_INCLUDE_COLUMN_KEYWORD = False
    LIMIT_FETCH = "FETCH"
    TABLESAMPLE_KEYWORDS = "SAMPLE"
    LAST_DAY_SUPPORTS_DATE_PART = False
    SUPPORTS_SELECT_INTO = True
    TZ_TO_WITH_TIME_ZONE = True
    SUPPORTS_WINDOW_EXCLUDE = True
    QUERY_HINT_SEP = " "
    SUPPORTS_DECODE_CASE = True

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        exp.DType.BLOB: "BLOB",
        exp.DType.TINYINT: "SMALLINT",
        exp.DType.SMALLINT: "SMALLINT",
        exp.DType.INT: "INT",
        exp.DType.BIGINT: "INT",
        exp.DType.DECIMAL: "NUMBER",
        exp.DType.DOUBLE: "DOUBLE PRECISION",
        exp.DType.VARCHAR: "VARCHAR2",
        exp.DType.NVARCHAR: "NVARCHAR2",
        exp.DType.NCHAR: "NCHAR",
        exp.DType.TEXT: "CLOB",
        exp.DType.TIMETZ: "TIME",
        exp.DType.TIMESTAMPNTZ: "TIMESTAMP",
        exp.DType.TIMESTAMPTZ: "TIMESTAMP",
        exp.DType.BINARY: "BLOB",
        exp.DType.VARBINARY: "BLOB",
        exp.DType.ROWVERSION: "BLOB",
    }

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.DateStrToDate: lambda self, e: self.func(
            "TO_DATE", e.this, exp.Literal.string("YYYY-MM-DD")
        ),
        exp.DateTrunc: lambda self, e: self.func("TRUNC", e.this, e.unit),
        exp.EuclideanDistance: rename_func("L2_DISTANCE"),
        exp.ILike: no_ilike_sql,
        exp.LogicalOr: rename_func("MAX"),
        exp.LogicalAnd: rename_func("MIN"),
        exp.Mod: rename_func("MOD"),
        exp.Rand: rename_func("DBMS_RANDOM.VALUE"),
        exp.Select: transforms.preprocess(
            [
                transforms.eliminate_distinct_on,
                transforms.eliminate_qualify,
            ]
        ),
        exp.StrPosition: lambda self, e: strposition_sql(
            self, e, func_name="INSTR", supports_position=True, supports_occurrence=True
        ),
        exp.StrToTime: lambda self, e: self.func("TO_TIMESTAMP", e.this, self.format_time(e)),
        exp.StrToDate: lambda self, e: self.func("TO_DATE", e.this, self.format_time(e)),
        exp.Subquery: lambda self, e: self.subquery_sql(e, sep=" "),
        exp.Substring: rename_func("SUBSTR"),
        exp.Table: lambda self, e: self.table_sql(e, sep=" "),
        exp.TableSample: lambda self, e: self.tablesample_sql(e),
        exp.TemporaryProperty: lambda _, e: f"{e.name or 'GLOBAL'} TEMPORARY",
        exp.TimeToStr: lambda self, e: self.func("TO_CHAR", e.this, self.format_time(e)),
        exp.ToChar: lambda self, e: self.function_fallback_sql(e),
        exp.ToNumber: to_number_with_nls_param,
        exp.Trim: _trim_sql,
        exp.Unicode: lambda self, e: f"ASCII(UNISTR({self.sql(e.this)}))",
        exp.UnixToTime: lambda self, e: (
            f"TO_DATE('1970-01-01', 'YYYY-MM-DD') + ({self.sql(e, 'this')} / 86400)"
        ),
        exp.UtcTimestamp: rename_func("UTC_TIMESTAMP"),
        exp.UtcTime: rename_func("UTC_TIME"),
        exp.Systimestamp: lambda self, e: "SYSTIMESTAMP",
    }

    PROPERTIES_LOCATION = {
        **generator.Generator.PROPERTIES_LOCATION,
        exp.VolatileProperty: exp.Properties.Location.UNSUPPORTED,
    }

    def currenttimestamp_sql(self, expression: exp.CurrentTimestamp) -> str:
        pass

    def offset_sql(self, expression: exp.Offset) -> str:
        pass

    def add_column_sql(self, expression: exp.Expr) -> str:
        pass

    def queryoption_sql(self, expression: exp.QueryOption) -> str:
        pass

    def coalesce_sql(self, expression: exp.Coalesce) -> str:
        pass

    def into_sql(self, expression: exp.Into) -> str:
        pass

    def hint_sql(self, expression: exp.Hint) -> str:
        pass

    def isascii_sql(self, expression: exp.IsAscii) -> str:
        pass

    def interval_sql(self, expression: exp.Interval) -> str:
        pass

    def columndef_sql(self, expression: exp.ColumnDef, sep: str = " ") -> str:
        pass
