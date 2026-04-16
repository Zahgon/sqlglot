from __future__ import annotations


from sqlglot import exp, transforms
from sqlglot.dialects.dialect import (
    approx_count_distinct_sql,
    arrow_json_extract_sql,
    rename_func,
    unit_to_str,
    inline_array_sql,
    property_sql,
)
from sqlglot.generators.mysql import MySQLGenerator


def _eliminate_between_in_delete(expression: exp.Expr) -> exp.Expr:
    """
    StarRocks doesn't support BETWEEN in DELETE statements, so we convert
    BETWEEN expressions to explicit comparisons.

    https://docs.starrocks.io/docs/sql-reference/sql-statements/table_bucket_part_index/DELETE/#parameters

    Example:
        >>> from sqlglot import parse_one
        >>> expr = parse_one("DELETE FROM t WHERE x BETWEEN 1 AND 10")
        >>> print(_eliminate_between_in_delete(expr).sql(dialect="starrocks"))
        DELETE FROM t WHERE x >= 1 AND x <= 10
    """
    pass


# https://docs.starrocks.io/docs/sql-reference/sql-functions/spatial-functions/st_distance_sphere/
def st_distance_sphere(self, expression: exp.StDistance) -> str:
    pass


class StarRocksGenerator(MySQLGenerator):
    EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE = False
    JSON_TYPE_REQUIRED_FOR_EXTRACTION = False
    VARCHAR_REQUIRES_SIZE = False
    PARSE_JSON_NAME: str | None = "PARSE_JSON"
    WITH_PROPERTIES_PREFIX = "PROPERTIES"
    UPDATE_STATEMENT_SUPPORTS_FROM = True
    INSERT_OVERWRITE = " OVERWRITE"

    # StarRocks doesn't support "IS TRUE/FALSE" syntax.
    IS_BOOL_ALLOWED = False
    # StarRocks doesn't support renaming a table with a database.
    RENAME_TABLE_WITH_DB = False

    CAST_MAPPING = {}

    TYPE_MAPPING = {
        **MySQLGenerator.TYPE_MAPPING,
        exp.DType.INT128: "LARGEINT",
        exp.DType.TEXT: "STRING",
        exp.DType.TIMESTAMP: "DATETIME",
        exp.DType.TIMESTAMPTZ: "DATETIME",
    }

    SQL_SECURITY_VIEW_LOCATION = exp.Properties.Location.POST_SCHEMA

    PROPERTIES_LOCATION = {
        **MySQLGenerator.PROPERTIES_LOCATION,
        exp.PrimaryKey: exp.Properties.Location.POST_SCHEMA,
        exp.UniqueKeyProperty: exp.Properties.Location.POST_SCHEMA,
        exp.RollupProperty: exp.Properties.Location.POST_SCHEMA,
        exp.PartitionedByProperty: exp.Properties.Location.POST_SCHEMA,
    }

    TRANSFORMS = {
        **{k: v for k, v in MySQLGenerator.TRANSFORMS.items() if k is not exp.DateTrunc},
        exp.Array: inline_array_sql,
        exp.ArrayAgg: rename_func("ARRAY_AGG"),
        exp.ArrayFilter: rename_func("ARRAY_FILTER"),
        exp.ArrayToString: rename_func("ARRAY_JOIN"),
        exp.ApproxDistinct: approx_count_distinct_sql,
        exp.CurrentVersion: lambda *_: "CURRENT_VERSION()",
        exp.DateDiff: lambda self, e: self.func("DATE_DIFF", unit_to_str(e), e.this, e.expression),
        exp.Delete: transforms.preprocess([_eliminate_between_in_delete]),
        exp.Flatten: rename_func("ARRAY_FLATTEN"),
        exp.JSONExtractScalar: arrow_json_extract_sql,
        exp.JSONExtract: arrow_json_extract_sql,
        exp.Property: property_sql,
        exp.RegexpLike: rename_func("REGEXP"),
        exp.SchemaCommentProperty: lambda self, e: self.naked_property(e),
        exp.SqlSecurityProperty: lambda self, e: f"SECURITY {self.sql(e.this)}",
        exp.StDistance: st_distance_sphere,
        exp.StrToUnix: lambda self, e: self.func("UNIX_TIMESTAMP", e.this, self.format_time(e)),
        exp.TimestampTrunc: lambda self, e: self.func("DATE_TRUNC", unit_to_str(e), e.this),
        exp.TimeStrToDate: rename_func("TO_DATE"),
        exp.UnixToStr: lambda self, e: self.func("FROM_UNIXTIME", e.this, self.format_time(e)),
        exp.UnixToTime: rename_func("FROM_UNIXTIME"),
    }

    # https://docs.starrocks.io/docs/sql-reference/sql-statements/keywords/#reserved-keywords
    RESERVED_KEYWORDS = {
        "add",
        "all",
        "alter",
        "analyze",
        "and",
        "array",
        "as",
        "asc",
        "between",
        "bigint",
        "bitmap",
        "both",
        "by",
        "case",
        "char",
        "character",
        "check",
        "collate",
        "column",
        "compaction",
        "convert",
        "create",
        "cross",
        "cube",
        "current_date",
        "current_role",
        "current_time",
        "current_timestamp",
        "current_user",
        "database",
        "databases",
        "decimal",
        "decimalv2",
        "decimal32",
        "decimal64",
        "decimal128",
        "default",
        "deferred",
        "delete",
        "dense_rank",
        "desc",
        "describe",
        "distinct",
        "double",
        "drop",
        "dual",
        "else",
        "except",
        "exists",
        "explain",
        "false",
        "first_value",
        "float",
        "for",
        "force",
        "from",
        "full",
        "function",
        "grant",
        "group",
        "grouping",
        "grouping_id",
        "groups",
        "having",
        "hll",
        "host",
        "if",
        "ignore",
        "immediate",
        "in",
        "index",
        "infile",
        "inner",
        "insert",
        "int",
        "integer",
        "intersect",
        "into",
        "is",
        "join",
        "json",
        "key",
        "keys",
        "kill",
        "lag",
        "largeint",
        "last_value",
        "lateral",
        "lead",
        "left",
        "like",
        "limit",
        "load",
        "localtime",
        "localtimestamp",
        "maxvalue",
        "minus",
        "mod",
        "not",
        "ntile",
        "null",
        "on",
        "or",
        "order",
        "outer",
        "outfile",
        "over",
        "partition",
        "percentile",
        "primary",
        "procedure",
        "qualify",
        "range",
        "rank",
        "read",
        "regexp",
        "release",
        "rename",
        "replace",
        "revoke",
        "right",
        "rlike",
        "row",
        "row_number",
        "rows",
        "schema",
        "schemas",
        "select",
        "set",
        "set_var",
        "show",
        "smallint",
        "system",
        "table",
        "terminated",
        "text",
        "then",
        "tinyint",
        "to",
        "true",
        "union",
        "unique",
        "unsigned",
        "update",
        "use",
        "using",
        "values",
        "varchar",
        "when",
        "where",
        "with",
    }

    def create_sql(self, expression: exp.Create) -> str:
        # Starrocks' primary key is defined outside of the schema, so we need to move it there
        pass

    def partitionedbyproperty_sql(self, expression: exp.PartitionedByProperty) -> str:
        pass

    def cluster_sql(self, expression: exp.Cluster) -> str:
        """Generate StarRocks ORDER BY clause for clustering."""
        pass

    def refreshtriggerproperty_sql(self, expression: exp.RefreshTriggerProperty) -> str:
        """Generate StarRocks REFRESH clause for materialized views.
        There is a little difference of the syntax between StarRocks and Doris.
        """
        pass
