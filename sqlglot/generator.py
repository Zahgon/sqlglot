from __future__ import annotations

import logging
import re
import typing as t
from collections import defaultdict
from functools import reduce, wraps

from sqlglot import exp
from sqlglot.errors import ErrorLevel, UnsupportedError, concat_messages
from sqlglot.expressions import apply_index_offset
from sqlglot.helper import csv, name_sequence, seq_get
from sqlglot.jsonpath import ALL_JSON_PATH_PARTS, JSON_PATH_PART_TRANSFORMS
from sqlglot.time import format_time
from sqlglot.tokens import TokenType

if t.TYPE_CHECKING:
    from sqlglot._typing import E
    from sqlglot.dialects.dialect import DialectType

    G = t.TypeVar("G", bound="Generator")
    GeneratorMethod = t.Callable[[G, E], str]

logger = logging.getLogger("sqlglot")

ESCAPED_UNICODE_RE = re.compile(r"\\(\d+)")
UNSUPPORTED_TEMPLATE = "Argument '{}' is not supported for expression '{}' when targeting {}."


def unsupported_args(
    *args: str | tuple[str, str],
) -> t.Callable[[GeneratorMethod], GeneratorMethod]:
    """
    Decorator that can be used to mark certain args of an `Expr` subclass as unsupported.
    It expects a sequence of argument names or pairs of the form (argument_name, diagnostic_msg).
    """
    diagnostic_by_arg: dict[str, str | None] = {}
    for arg in args:
        if isinstance(arg, str):
            diagnostic_by_arg[arg] = None
        else:
            diagnostic_by_arg[arg[0]] = arg[1]

    def decorator(func: GeneratorMethod) -> GeneratorMethod:
        @wraps(func)
        def _func(generator: G, expression: E) -> str:
            pass

        return _func

    return decorator


AFTER_HAVING_MODIFIER_TRANSFORMS: dict[str, t.Any] = {
    "windows": lambda self, e: (
        self.seg("WINDOW ") + self.expressions(e, key="windows", flat=True)
        if e.args.get("windows")
        else ""
    ),
    "qualify": lambda self, e: self.sql(e, "qualify"),
}


_DISPATCH_CACHE: dict[type[Generator], dict[type[exp.Expr], t.Callable[..., str]]] = {}


def _build_dispatch(
    cls: type[Generator],
) -> dict[type[exp.Expr], t.Callable[..., str]]:
    pass


class Generator:
    """
    Generator converts a given syntax tree to the corresponding SQL string.

    Args:
        pretty: Whether to format the produced SQL string.
            Default: False.
        identify: Determines when an identifier should be quoted. Possible values are:
            False (default): Never quote, except in cases where it's mandatory by the dialect.
            True: Always quote except for specials cases.
            'safe': Only quote identifiers that are case insensitive.
        normalize: Whether to normalize identifiers to lowercase.
            Default: False.
        pad: The pad size in a formatted string. For example, this affects the indentation of
            a projection in a query, relative to its nesting level.
            Default: 2.
        indent: The indentation size in a formatted string. For example, this affects the
            indentation of subqueries and filters under a `WHERE` clause.
            Default: 2.
        normalize_functions: How to normalize function names. Possible values are:
            "upper" or True (default): Convert names to uppercase.
            "lower": Convert names to lowercase.
            False: Disables function name normalization.
        unsupported_level: Determines the generator's behavior when it encounters unsupported expressions.
            Default ErrorLevel.WARN.
        max_unsupported: Maximum number of unsupported messages to include in a raised UnsupportedError.
            This is only relevant if unsupported_level is ErrorLevel.RAISE.
            Default: 3
        leading_comma: Whether the comma is leading or trailing in select expressions.
            This is only relevant when generating in pretty mode.
            Default: False
        max_text_width: The max number of characters in a segment before creating new lines in pretty mode.
            The default is on the smaller end because the length only represents a segment and not the true
            line length.
            Default: 80
        comments: Whether to preserve comments in the output SQL code.
            Default: True
    """

    TRANSFORMS: t.ClassVar[dict[type[exp.Expr], t.Callable[..., str]]] = {
        **JSON_PATH_PART_TRANSFORMS,
        exp.Adjacent: lambda self, e: self.binary(e, "-|-"),
        exp.AllowedValuesProperty: lambda self, e: (
            f"ALLOWED_VALUES {self.expressions(e, flat=True)}"
        ),
        exp.AnalyzeColumns: lambda self, e: self.sql(e, "this"),
        exp.AnalyzeWith: lambda self, e: self.expressions(e, prefix="WITH ", sep=" "),
        exp.ArrayContainsAll: lambda self, e: self.binary(e, "@>"),
        exp.ArrayOverlaps: lambda self, e: self.binary(e, "&&"),
        exp.AssumeColumnConstraint: lambda self, e: f"ASSUME ({self.sql(e, 'this')})",
        exp.AutoRefreshProperty: lambda self, e: f"AUTO REFRESH {self.sql(e, 'this')}",
        exp.BackupProperty: lambda self, e: f"BACKUP {self.sql(e, 'this')}",
        exp.CaseSpecificColumnConstraint: lambda _, e: (
            f"{'NOT ' if e.args.get('not_') else ''}CASESPECIFIC"
        ),
        exp.Ceil: lambda self, e: self.ceil_floor(e),
        exp.CharacterSetColumnConstraint: lambda self, e: f"CHARACTER SET {self.sql(e, 'this')}",
        exp.CharacterSetProperty: lambda self, e: (
            f"{'DEFAULT ' if e.args.get('default') else ''}CHARACTER SET={self.sql(e, 'this')}"
        ),
        exp.ClusteredColumnConstraint: lambda self, e: (
            f"CLUSTERED ({self.expressions(e, 'this', indent=False)})"
        ),
        exp.CollateColumnConstraint: lambda self, e: f"COLLATE {self.sql(e, 'this')}",
        exp.CommentColumnConstraint: lambda self, e: f"COMMENT {self.sql(e, 'this')}",
        exp.ConnectByRoot: lambda self, e: f"CONNECT_BY_ROOT {self.sql(e, 'this')}",
        exp.ConvertToCharset: lambda self, e: self.func(
            "CONVERT", e.this, e.args["dest"], e.args.get("source")
        ),
        exp.CopyGrantsProperty: lambda *_: "COPY GRANTS",
        exp.CredentialsProperty: lambda self, e: (
            f"CREDENTIALS=({self.expressions(e, 'expressions', sep=' ')})"
        ),
        exp.CurrentCatalog: lambda *_: "CURRENT_CATALOG",
        exp.SessionUser: lambda *_: "SESSION_USER",
        exp.DateFormatColumnConstraint: lambda self, e: f"FORMAT {self.sql(e, 'this')}",
        exp.DefaultColumnConstraint: lambda self, e: f"DEFAULT {self.sql(e, 'this')}",
        exp.ApiProperty: lambda *_: "API",
        exp.ApplicationProperty: lambda *_: "APPLICATION",
        exp.CatalogProperty: lambda *_: "CATALOG",
        exp.ComputeProperty: lambda *_: "COMPUTE",
        exp.DatabaseProperty: lambda *_: "DATABASE",
        exp.DynamicProperty: lambda *_: "DYNAMIC",
        exp.EmptyProperty: lambda *_: "EMPTY",
        exp.EncodeColumnConstraint: lambda self, e: f"ENCODE {self.sql(e, 'this')}",
        exp.EndStatement: lambda *_: "END",
        exp.EnviromentProperty: lambda self, e: f"ENVIRONMENT ({self.expressions(e, flat=True)})",
        exp.HandlerProperty: lambda self, e: f"HANDLER {self.sql(e, 'this')}",
        exp.ParameterStyleProperty: lambda self, e: f"PARAMETER STYLE {self.sql(e, 'this')}",
        exp.EphemeralColumnConstraint: lambda self, e: (
            f"EPHEMERAL{(' ' + self.sql(e, 'this')) if e.this else ''}"
        ),
        exp.ExcludeColumnConstraint: lambda self, e: f"EXCLUDE {self.sql(e, 'this').lstrip()}",
        exp.ExecuteAsProperty: lambda self, e: self.naked_property(e),
        exp.Except: lambda self, e: self.set_operations(e),
        exp.ExternalProperty: lambda *_: "EXTERNAL",
        exp.Floor: lambda self, e: self.ceil_floor(e),
        exp.Get: lambda self, e: self.get_put_sql(e),
        exp.GlobalProperty: lambda *_: "GLOBAL",
        exp.HeapProperty: lambda *_: "HEAP",
        exp.HybridProperty: lambda *_: "HYBRID",
        exp.IcebergProperty: lambda *_: "ICEBERG",
        exp.InheritsProperty: lambda self, e: f"INHERITS ({self.expressions(e, flat=True)})",
        exp.InlineLengthColumnConstraint: lambda self, e: f"INLINE LENGTH {self.sql(e, 'this')}",
        exp.InputModelProperty: lambda self, e: f"INPUT{self.sql(e, 'this')}",
        exp.Intersect: lambda self, e: self.set_operations(e),
        exp.IntervalSpan: lambda self, e: f"{self.sql(e, 'this')} TO {self.sql(e, 'expression')}",
        exp.Int64: lambda self, e: self.sql(exp.cast(e.this, exp.DType.BIGINT)),
        exp.JSONBContainsAnyTopKeys: lambda self, e: self.binary(e, "?|"),
        exp.JSONBContainsAllTopKeys: lambda self, e: self.binary(e, "?&"),
        exp.JSONBDeleteAtPath: lambda self, e: self.binary(e, "#-"),
        exp.JSONObject: lambda self, e: self._jsonobject_sql(e),
        exp.JSONObjectAgg: lambda self, e: self._jsonobject_sql(e),
        exp.LanguageProperty: lambda self, e: self.naked_property(e),
        exp.LocationProperty: lambda self, e: self.naked_property(e),
        exp.LogProperty: lambda _, e: f"{'NO ' if e.args.get('no') else ''}LOG",
        exp.MaskingProperty: lambda *_: "MASKING",
        exp.MaterializedProperty: lambda *_: "MATERIALIZED",
        exp.NetFunc: lambda self, e: f"NET.{self.sql(e, 'this')}",
        exp.NetworkProperty: lambda *_: "NETWORK",
        exp.NonClusteredColumnConstraint: lambda self, e: (
            f"NONCLUSTERED ({self.expressions(e, 'this', indent=False)})"
        ),
        exp.NoPrimaryIndexProperty: lambda *_: "NO PRIMARY INDEX",
        exp.NotForReplicationColumnConstraint: lambda *_: "NOT FOR REPLICATION",
        exp.OnCommitProperty: lambda _, e: (
            f"ON COMMIT {'DELETE' if e.args.get('delete') else 'PRESERVE'} ROWS"
        ),
        exp.OnProperty: lambda self, e: f"ON {self.sql(e, 'this')}",
        exp.OnUpdateColumnConstraint: lambda self, e: f"ON UPDATE {self.sql(e, 'this')}",
        exp.Operator: lambda self, e: self.binary(e, ""),  # The operator is produced in `binary`
        exp.OutputModelProperty: lambda self, e: f"OUTPUT{self.sql(e, 'this')}",
        exp.ExtendsLeft: lambda self, e: self.binary(e, "&<"),
        exp.ExtendsRight: lambda self, e: self.binary(e, "&>"),
        exp.PathColumnConstraint: lambda self, e: f"PATH {self.sql(e, 'this')}",
        exp.PartitionedByBucket: lambda self, e: self.func("BUCKET", e.this, e.expression),
        exp.PartitionByTruncate: lambda self, e: self.func("TRUNCATE", e.this, e.expression),
        exp.PivotAny: lambda self, e: f"ANY{self.sql(e, 'this')}",
        exp.PositionalColumn: lambda self, e: f"#{self.sql(e, 'this')}",
        exp.ProjectionPolicyColumnConstraint: lambda self, e: (
            f"PROJECTION POLICY {self.sql(e, 'this')}"
        ),
        exp.ZeroFillColumnConstraint: lambda self, e: "ZEROFILL",
        exp.Put: lambda self, e: self.get_put_sql(e),
        exp.RemoteWithConnectionModelProperty: lambda self, e: (
            f"REMOTE WITH CONNECTION {self.sql(e, 'this')}"
        ),
        exp.ReturnsProperty: lambda self, e: (
            "RETURNS NULL ON NULL INPUT" if e.args.get("null") else self.naked_property(e)
        ),
        exp.RowAccessProperty: lambda *_: "ROW ACCESS",
        exp.SafeFunc: lambda self, e: f"SAFE.{self.sql(e, 'this')}",
        exp.SampleProperty: lambda self, e: f"SAMPLE BY {self.sql(e, 'this')}",
        exp.SecureProperty: lambda *_: "SECURE",
        exp.SecurityIntegrationProperty: lambda *_: "SECURITY",
        exp.SetConfigProperty: lambda self, e: self.sql(e, "this"),
        exp.SetProperty: lambda _, e: f"{'MULTI' if e.args.get('multi') else ''}SET",
        exp.SettingsProperty: lambda self, e: f"SETTINGS{self.seg('')}{(self.expressions(e))}",
        exp.SharingProperty: lambda self, e: f"SHARING={self.sql(e, 'this')}",
        exp.SqlReadWriteProperty: lambda _, e: e.name,
        exp.SqlSecurityProperty: lambda self, e: f"SQL SECURITY {self.sql(e, 'this')}",
        exp.StabilityProperty: lambda _, e: e.name,
        exp.Stream: lambda self, e: f"STREAM {self.sql(e, 'this')}",
        exp.StreamingTableProperty: lambda *_: "STREAMING",
        exp.StrictProperty: lambda *_: "STRICT",
        exp.SwapTable: lambda self, e: f"SWAP WITH {self.sql(e, 'this')}",
        exp.TableColumn: lambda self, e: self.sql(e.this),
        exp.Tags: lambda self, e: f"TAG ({self.expressions(e, flat=True)})",
        exp.TemporaryProperty: lambda *_: "TEMPORARY",
        exp.TitleColumnConstraint: lambda self, e: f"TITLE {self.sql(e, 'this')}",
        exp.ToMap: lambda self, e: f"MAP {self.sql(e, 'this')}",
        exp.ToTableProperty: lambda self, e: f"TO {self.sql(e.this)}",
        exp.TransformModelProperty: lambda self, e: self.func("TRANSFORM", *e.expressions),
        exp.TransientProperty: lambda *_: "TRANSIENT",
        exp.VirtualProperty: lambda *_: "VIRTUAL",
        exp.TriggerExecute: lambda self, e: f"EXECUTE FUNCTION {self.sql(e, 'this')}",
        exp.Union: lambda self, e: self.set_operations(e),
        exp.UnloggedProperty: lambda *_: "UNLOGGED",
        exp.UsingTemplateProperty: lambda self, e: f"USING TEMPLATE {self.sql(e, 'this')}",
        exp.UsingData: lambda self, e: f"USING DATA {self.sql(e, 'this')}",
        exp.UppercaseColumnConstraint: lambda *_: "UPPERCASE",
        exp.UtcDate: lambda self, e: self.sql(exp.CurrentDate(this=exp.Literal.string("UTC"))),
        exp.UtcTime: lambda self, e: self.sql(exp.CurrentTime(this=exp.Literal.string("UTC"))),
        exp.UtcTimestamp: lambda self, e: self.sql(
            exp.CurrentTimestamp(this=exp.Literal.string("UTC"))
        ),
        exp.Variadic: lambda self, e: f"VARIADIC {self.sql(e, 'this')}",
        exp.VarMap: lambda self, e: self.func("MAP", e.args["keys"], e.args["values"]),
        exp.ViewAttributeProperty: lambda self, e: f"WITH {self.sql(e, 'this')}",
        exp.VolatileProperty: lambda *_: "VOLATILE",
        exp.WithJournalTableProperty: lambda self, e: f"WITH JOURNAL TABLE={self.sql(e, 'this')}",
        exp.WithProcedureOptions: lambda self, e: f"WITH {self.expressions(e, flat=True)}",
        exp.WithSchemaBindingProperty: lambda self, e: f"WITH SCHEMA {self.sql(e, 'this')}",
        exp.WithOperator: lambda self, e: f"{self.sql(e, 'this')} WITH {self.sql(e, 'op')}",
        exp.ForceProperty: lambda *_: "FORCE",
    }

    # Whether null ordering is supported in order by
    # True: Full Support, None: No support, False: No support for certain cases
    # such as window specifications, aggregate functions etc
    NULL_ORDERING_SUPPORTED: bool | None = True

    # Window functions that support NULLS FIRST/LAST
    WINDOW_FUNCS_WITH_NULL_ORDERING: t.ClassVar[tuple[type[exp.Expression], ...]] = ()

    # Whether ignore nulls is inside the agg or outside.
    # FIRST(x IGNORE NULLS) OVER vs FIRST (x) IGNORE NULLS OVER
    IGNORE_NULLS_IN_FUNC = False

    # Whether IGNORE NULLS is placed before ORDER BY in the agg.
    # FIRST(x IGNORE NULLS ORDER BY y) vs FIRST(x ORDER BY y IGNORE NULLS)
    IGNORE_NULLS_BEFORE_ORDER = True

    # Whether locking reads (i.e. SELECT ... FOR UPDATE/SHARE) are supported
    LOCKING_READS_SUPPORTED = False

    # Whether the EXCEPT and INTERSECT operations can return duplicates
    EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE = True

    # Wrap derived values in parens, usually standard but spark doesn't support it
    WRAP_DERIVED_VALUES = True

    # Whether create function uses an AS before the RETURN
    CREATE_FUNCTION_RETURN_AS = True

    # Whether MERGE ... WHEN MATCHED BY SOURCE is allowed
    MATCHED_BY_SOURCE = True

    # Whether MERGE ... WHEN MATCHED/NOT MATCHED THEN UPDATE/INSERT ... WHERE is supported
    SUPPORTS_MERGE_WHERE = False

    # Whether the INTERVAL expression works only with values like '1 day'
    SINGLE_STRING_INTERVAL = False

    # Whether the plural form of date parts like day (i.e. "days") is supported in INTERVALs
    INTERVAL_ALLOWS_PLURAL_FORM = True

    # Whether limit and fetch are supported (possible values: "ALL", "LIMIT", "FETCH")
    LIMIT_FETCH = "ALL"

    # Whether limit and fetch allows expresions or just limits
    LIMIT_ONLY_LITERALS = False

    # Whether a table is allowed to be renamed with a db
    RENAME_TABLE_WITH_DB = True

    # The separator for grouping sets and rollups
    GROUPINGS_SEP = ","

    # The string used for creating an index on a table
    INDEX_ON = "ON"

    # Separator for IN/OUT parameter mode (Oracle uses " " for "IN OUT", PostgreSQL uses "" for "INOUT")
    INOUT_SEPARATOR = " "

    # Whether join hints should be generated
    JOIN_HINTS = True

    # Whether directed joins are supported
    DIRECTED_JOINS = False

    # Whether table hints should be generated
    TABLE_HINTS = True

    # Whether query hints should be generated
    QUERY_HINTS = True

    # What kind of separator to use for query hints
    QUERY_HINT_SEP = ", "

    # Whether comparing against booleans (e.g. x IS TRUE) is supported
    IS_BOOL_ALLOWED = True

    # Whether to include the "SET" keyword in the "INSERT ... ON DUPLICATE KEY UPDATE" statement
    DUPLICATE_KEY_UPDATE_WITH_SET = True

    # Whether to generate the limit as TOP <value> instead of LIMIT <value>
    LIMIT_IS_TOP = False

    # Whether to generate INSERT INTO ... RETURNING or INSERT INTO RETURNING ...
    RETURNING_END = True

    # Whether to generate an unquoted value for EXTRACT's date part argument
    EXTRACT_ALLOWS_QUOTES = True

    # Whether TIMETZ / TIMESTAMPTZ will be generated using the "WITH TIME ZONE" syntax
    TZ_TO_WITH_TIME_ZONE = False

    # Whether the NVL2 function is supported
    NVL2_SUPPORTED = True

    # https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax
    SELECT_KINDS: tuple[str, ...] = ("STRUCT", "VALUE")

    # Whether VALUES statements can be used as derived tables.
    # MySQL 5 and Redshift do not allow this, so when False, it will convert
    # SELECT * VALUES into SELECT UNION
    VALUES_AS_TABLE = True

    # Whether the word COLUMN is included when adding a column with ALTER TABLE
    ALTER_TABLE_INCLUDE_COLUMN_KEYWORD = True

    # UNNEST WITH ORDINALITY (presto) instead of UNNEST WITH OFFSET (bigquery)
    UNNEST_WITH_ORDINALITY = True

    # Whether FILTER (WHERE cond) can be used for conditional aggregation
    AGGREGATE_FILTER_SUPPORTED = True

    # Whether JOIN sides (LEFT, RIGHT) are supported in conjunction with SEMI/ANTI join kinds
    SEMI_ANTI_JOIN_WITH_SIDE = True

    # Whether to include the type of a computed column in the CREATE DDL
    COMPUTED_COLUMN_WITH_TYPE = True

    # Whether CREATE TABLE .. COPY .. is supported. False means we'll generate CLONE instead of COPY
    SUPPORTS_TABLE_COPY = True

    # Whether parentheses are required around the table sample's expression
    TABLESAMPLE_REQUIRES_PARENS = True

    # Whether a table sample clause's size needs to be followed by the ROWS keyword
    TABLESAMPLE_SIZE_IS_ROWS = True

    # The keyword(s) to use when generating a sample clause
    TABLESAMPLE_KEYWORDS = "TABLESAMPLE"

    # Whether the TABLESAMPLE clause supports a method name, like BERNOULLI
    TABLESAMPLE_WITH_METHOD = True

    # The keyword to use when specifying the seed of a sample clause
    TABLESAMPLE_SEED_KEYWORD = "SEED"

    # Whether COLLATE is a function instead of a binary operator
    COLLATE_IS_FUNC = False

    # Whether data types support additional specifiers like e.g. CHAR or BYTE (oracle)
    DATA_TYPE_SPECIFIERS_ALLOWED = False

    # Whether conditions require booleans WHERE x = 0 vs WHERE x
    ENSURE_BOOLS = False

    # Whether the "RECURSIVE" keyword is required when defining recursive CTEs
    CTE_RECURSIVE_KEYWORD_REQUIRED = True

    # Whether CONCAT requires >1 arguments
    SUPPORTS_SINGLE_ARG_CONCAT = True

    # Whether LAST_DAY function supports a date part argument
    LAST_DAY_SUPPORTS_DATE_PART = True

    # Whether named columns are allowed in table aliases
    SUPPORTS_TABLE_ALIAS_COLUMNS = True

    # Whether UNPIVOT aliases are Identifiers (False means they're Literals)
    UNPIVOT_ALIASES_ARE_IDENTIFIERS = True

    # What delimiter to use for separating JSON key/value pairs
    JSON_KEY_VALUE_PAIR_SEP = ":"

    # INSERT OVERWRITE TABLE x override
    INSERT_OVERWRITE = " OVERWRITE TABLE"

    # Whether the SELECT .. INTO syntax is used instead of CTAS
    SUPPORTS_SELECT_INTO = False

    # Whether UNLOGGED tables can be created
    SUPPORTS_UNLOGGED_TABLES = False

    # Whether the CREATE TABLE LIKE statement is supported
    SUPPORTS_CREATE_TABLE_LIKE = True

    # Whether the LikeProperty needs to be specified inside of the schema clause
    LIKE_PROPERTY_INSIDE_SCHEMA = False

    # Whether DISTINCT can be followed by multiple args in an AggFunc. If not, it will be
    # transpiled into a series of CASE-WHEN-ELSE, ultimately using a tuple conseisting of the args
    MULTI_ARG_DISTINCT = True

    # Whether the JSON extraction operators expect a value of type JSON
    JSON_TYPE_REQUIRED_FOR_EXTRACTION = False

    # Whether bracketed keys like ["foo"] are supported in JSON paths
    JSON_PATH_BRACKETED_KEY_SUPPORTED = True

    # Whether to escape keys using single quotes in JSON paths
    JSON_PATH_SINGLE_QUOTE_ESCAPE = False

    # The JSONPathPart expressions supported by this dialect
    SUPPORTED_JSON_PATH_PARTS: t.ClassVar = ALL_JSON_PATH_PARTS.copy()

    # Whether any(f(x) for x in array) can be implemented by this dialect
    CAN_IMPLEMENT_ARRAY_ANY = False

    # Whether the function TO_NUMBER is supported
    SUPPORTS_TO_NUMBER = True

    # Whether EXCLUDE in window specification is supported
    SUPPORTS_WINDOW_EXCLUDE = False

    # Whether or not set op modifiers apply to the outer set op or select.
    # SELECT * FROM x UNION SELECT * FROM y LIMIT 1
    # True means limit 1 happens after the set op, False means it it happens on y.
    SET_OP_MODIFIERS = True

    # Whether parameters from COPY statement are wrapped in parentheses
    COPY_PARAMS_ARE_WRAPPED = True

    # Whether values of params are set with "=" token or empty space
    COPY_PARAMS_EQ_REQUIRED = False

    # Whether COPY statement has INTO keyword
    COPY_HAS_INTO_KEYWORD = True

    # Whether the conditional TRY(expression) function is supported
    TRY_SUPPORTED = True

    # Whether the UESCAPE syntax in unicode strings is supported
    SUPPORTS_UESCAPE = True

    # Function used to replace escaped unicode codes in unicode strings
    UNICODE_SUBSTITUTE: t.ClassVar[t.Any] = None

    # The keyword to use when generating a star projection with excluded columns
    STAR_EXCEPT = "EXCEPT"

    # The HEX function name
    HEX_FUNC = "HEX"

    # The keywords to use when prefixing & separating WITH based properties
    WITH_PROPERTIES_PREFIX = "WITH"

    # Whether to quote the generated expression of exp.JsonPath
    QUOTE_JSON_PATH = True

    # Whether the text pattern/fill (3rd) parameter of RPAD()/LPAD() is optional (defaults to space)
    PAD_FILL_PATTERN_IS_REQUIRED = False

    # Whether a projection can explode into multiple rows, e.g. by unnesting an array.
    SUPPORTS_EXPLODING_PROJECTIONS = True

    # Whether ARRAY_CONCAT can be generated with varlen args or if it should be reduced to 2-arg version
    ARRAY_CONCAT_IS_VAR_LEN = True

    # Whether CONVERT_TIMEZONE() is supported; if not, it will be generated as exp.AtTimeZone
    SUPPORTS_CONVERT_TIMEZONE = False

    # Whether MEDIAN(expr) is supported; if not, it will be generated as PERCENTILE_CONT(expr, 0.5)
    SUPPORTS_MEDIAN = True

    # Whether UNIX_SECONDS(timestamp) is supported
    SUPPORTS_UNIX_SECONDS = False

    # Whether to wrap <props> in `AlterSet`, e.g., ALTER ... SET (<props>)
    ALTER_SET_WRAPPED = False

    # Whether to normalize the date parts in EXTRACT(<date_part> FROM <expr>) into a common representation
    # For instance, to extract the day of week in ISO semantics, one can use ISODOW, DAYOFWEEKISO etc depending on the dialect.
    # TODO: The normalization should be done by default once we've tested it across all dialects.
    NORMALIZE_EXTRACT_DATE_PARTS = False

    # The name to generate for the JSONPath expression. If `None`, only `this` will be generated
    PARSE_JSON_NAME: str | None = "PARSE_JSON"

    # The function name of the exp.ArraySize expression
    ARRAY_SIZE_NAME: str = "ARRAY_LENGTH"

    # The syntax to use when altering the type of a column
    ALTER_SET_TYPE = "SET DATA TYPE"

    # Whether exp.ArraySize should generate the dimension arg too (valid for Postgres & DuckDB)
    # None -> Doesn't support it at all
    # False (DuckDB) -> Has backwards-compatible support, but preferably generated without
    # True (Postgres) -> Explicitly requires it
    ARRAY_SIZE_DIM_REQUIRED: bool | None = None

    # Whether a multi-argument DECODE(...) function is supported. If not, a CASE expression is generated
    SUPPORTS_DECODE_CASE = True

    # Whether SYMMETRIC and ASYMMETRIC flags are supported with BETWEEN expression
    SUPPORTS_BETWEEN_FLAGS = False

    # Whether LIKE and ILIKE support quantifiers such as LIKE ANY/ALL/SOME
    SUPPORTS_LIKE_QUANTIFIERS = True

    # Prefix which is appended to exp.Table expressions in MATCH AGAINST
    MATCH_AGAINST_TABLE_PREFIX: str | None = None

    # Whether to include the VARIABLE keyword for SET assignments
    SET_ASSIGNMENT_REQUIRES_VARIABLE_KEYWORD = False

    # The keyword to use for default value assignment in DECLARE statements
    DECLARE_DEFAULT_ASSIGNMENT = "="

    # Whether FROM is supported in UPDATE statements or if joins must be generated instead, e.g:
    # Supported (Postgres, Doris etc): UPDATE t1 SET t1.a = t2.b FROM t2
    # Unsupported (MySQL, SingleStore): UPDATE t1 JOIN t2 ON TRUE SET t1.a = t2.b
    UPDATE_STATEMENT_SUPPORTS_FROM = True

    # Whether SELECT *, ... EXCLUDE requires wrapping in a subquery for transpilation.
    STAR_EXCLUDE_REQUIRES_DERIVED_TABLE = True

    # Whether DROP and ALTER statements against Iceberg tables include 'ICEBERG', e.g.:
    # - Snowflake: DROP ICEBERG TABLE a.b;
    # - DuckDB:    DROP TABLE a.b;
    SUPPORTS_DROP_ALTER_ICEBERG_PROPERTY = True

    TYPE_MAPPING: t.ClassVar = {
        exp.DType.DATETIME2: "TIMESTAMP",
        exp.DType.NCHAR: "CHAR",
        exp.DType.NVARCHAR: "VARCHAR",
        exp.DType.MEDIUMTEXT: "TEXT",
        exp.DType.LONGTEXT: "TEXT",
        exp.DType.TINYTEXT: "TEXT",
        exp.DType.BLOB: "VARBINARY",
        exp.DType.MEDIUMBLOB: "BLOB",
        exp.DType.LONGBLOB: "BLOB",
        exp.DType.TINYBLOB: "BLOB",
        exp.DType.INET: "INET",
        exp.DType.ROWVERSION: "VARBINARY",
        exp.DType.SMALLDATETIME: "TIMESTAMP",
    }

    UNSUPPORTED_TYPES: t.ClassVar[set[exp.DType]] = set()

    TIME_PART_SINGULARS: t.ClassVar = {
        "MICROSECONDS": "MICROSECOND",
        "SECONDS": "SECOND",
        "MINUTES": "MINUTE",
        "HOURS": "HOUR",
        "DAYS": "DAY",
        "WEEKS": "WEEK",
        "MONTHS": "MONTH",
        "QUARTERS": "QUARTER",
        "YEARS": "YEAR",
    }

    AFTER_HAVING_MODIFIER_TRANSFORMS: t.ClassVar = {
        "cluster": lambda self, e: self.sql(e, "cluster"),
        "distribute": lambda self, e: self.sql(e, "distribute"),
        "sort": lambda self, e: self.sql(e, "sort"),
        **AFTER_HAVING_MODIFIER_TRANSFORMS,
    }

    TOKEN_MAPPING: t.ClassVar[dict[TokenType, str]] = {}

    STRUCT_DELIMITER: t.ClassVar = ("<", ">")

    PARAMETER_TOKEN = "@"
    NAMED_PLACEHOLDER_TOKEN = ":"

    EXPRESSION_PRECEDES_PROPERTIES_CREATABLES: t.ClassVar[set[str]] = set()

    PROPERTIES_LOCATION: t.ClassVar = {
        exp.AllowedValuesProperty: exp.Properties.Location.POST_SCHEMA,
        exp.AlgorithmProperty: exp.Properties.Location.POST_CREATE,
        exp.ApiProperty: exp.Properties.Location.POST_CREATE,
        exp.ApplicationProperty: exp.Properties.Location.POST_CREATE,
        exp.AutoIncrementProperty: exp.Properties.Location.POST_SCHEMA,
        exp.AutoRefreshProperty: exp.Properties.Location.POST_SCHEMA,
        exp.BackupProperty: exp.Properties.Location.POST_SCHEMA,
        exp.BlockCompressionProperty: exp.Properties.Location.POST_NAME,
        exp.CatalogProperty: exp.Properties.Location.POST_CREATE,
        exp.CharacterSetProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ChecksumProperty: exp.Properties.Location.POST_NAME,
        exp.CollateProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ComputeProperty: exp.Properties.Location.POST_CREATE,
        exp.CopyGrantsProperty: exp.Properties.Location.POST_SCHEMA,
        exp.Cluster: exp.Properties.Location.POST_SCHEMA,
        exp.ClusteredByProperty: exp.Properties.Location.POST_SCHEMA,
        exp.DistributedByProperty: exp.Properties.Location.POST_SCHEMA,
        exp.DuplicateKeyProperty: exp.Properties.Location.POST_SCHEMA,
        exp.DataBlocksizeProperty: exp.Properties.Location.POST_NAME,
        exp.DatabaseProperty: exp.Properties.Location.POST_CREATE,
        exp.DataDeletionProperty: exp.Properties.Location.POST_SCHEMA,
        exp.DefinerProperty: exp.Properties.Location.POST_CREATE,
        exp.DictRange: exp.Properties.Location.POST_SCHEMA,
        exp.DictProperty: exp.Properties.Location.POST_SCHEMA,
        exp.DynamicProperty: exp.Properties.Location.POST_CREATE,
        exp.DistKeyProperty: exp.Properties.Location.POST_SCHEMA,
        exp.DistStyleProperty: exp.Properties.Location.POST_SCHEMA,
        exp.EmptyProperty: exp.Properties.Location.POST_SCHEMA,
        exp.EncodeProperty: exp.Properties.Location.POST_EXPRESSION,
        exp.EngineProperty: exp.Properties.Location.POST_SCHEMA,
        exp.EnviromentProperty: exp.Properties.Location.POST_SCHEMA,
        exp.HandlerProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ParameterStyleProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ExecuteAsProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ExternalProperty: exp.Properties.Location.POST_CREATE,
        exp.FallbackProperty: exp.Properties.Location.POST_NAME,
        exp.FileFormatProperty: exp.Properties.Location.POST_WITH,
        exp.FreespaceProperty: exp.Properties.Location.POST_NAME,
        exp.GlobalProperty: exp.Properties.Location.POST_CREATE,
        exp.HeapProperty: exp.Properties.Location.POST_WITH,
        exp.HybridProperty: exp.Properties.Location.POST_CREATE,
        exp.InheritsProperty: exp.Properties.Location.POST_SCHEMA,
        exp.IcebergProperty: exp.Properties.Location.POST_CREATE,
        exp.IncludeProperty: exp.Properties.Location.POST_SCHEMA,
        exp.InputModelProperty: exp.Properties.Location.POST_SCHEMA,
        exp.IsolatedLoadingProperty: exp.Properties.Location.POST_NAME,
        exp.JournalProperty: exp.Properties.Location.POST_NAME,
        exp.LanguageProperty: exp.Properties.Location.POST_SCHEMA,
        exp.LikeProperty: exp.Properties.Location.POST_SCHEMA,
        exp.LocationProperty: exp.Properties.Location.POST_SCHEMA,
        exp.LockProperty: exp.Properties.Location.POST_SCHEMA,
        exp.LockingProperty: exp.Properties.Location.POST_ALIAS,
        exp.LogProperty: exp.Properties.Location.POST_NAME,
        exp.MaskingProperty: exp.Properties.Location.POST_CREATE,
        exp.MaterializedProperty: exp.Properties.Location.POST_CREATE,
        exp.MergeBlockRatioProperty: exp.Properties.Location.POST_NAME,
        exp.ModuleProperty: exp.Properties.Location.POST_SCHEMA,
        exp.NetworkProperty: exp.Properties.Location.POST_CREATE,
        exp.NoPrimaryIndexProperty: exp.Properties.Location.POST_EXPRESSION,
        exp.OnProperty: exp.Properties.Location.POST_SCHEMA,
        exp.OnCommitProperty: exp.Properties.Location.POST_EXPRESSION,
        exp.Order: exp.Properties.Location.POST_SCHEMA,
        exp.OutputModelProperty: exp.Properties.Location.POST_SCHEMA,
        exp.PartitionedByProperty: exp.Properties.Location.POST_WITH,
        exp.PartitionedOfProperty: exp.Properties.Location.POST_SCHEMA,
        exp.PrimaryKey: exp.Properties.Location.POST_SCHEMA,
        exp.Property: exp.Properties.Location.POST_WITH,
        exp.RefreshTriggerProperty: exp.Properties.Location.POST_SCHEMA,
        exp.RemoteWithConnectionModelProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ReturnsProperty: exp.Properties.Location.POST_SCHEMA,
        exp.RollupProperty: exp.Properties.Location.UNSUPPORTED,
        exp.RowAccessProperty: exp.Properties.Location.UNSUPPORTED,
        exp.RowFormatProperty: exp.Properties.Location.POST_SCHEMA,
        exp.RowFormatDelimitedProperty: exp.Properties.Location.POST_SCHEMA,
        exp.RowFormatSerdeProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SampleProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SchemaCommentProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SecureProperty: exp.Properties.Location.POST_CREATE,
        exp.SecurityIntegrationProperty: exp.Properties.Location.POST_CREATE,
        exp.SerdeProperties: exp.Properties.Location.POST_SCHEMA,
        exp.Set: exp.Properties.Location.POST_SCHEMA,
        exp.SettingsProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SetProperty: exp.Properties.Location.POST_CREATE,
        exp.SetConfigProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SharingProperty: exp.Properties.Location.POST_EXPRESSION,
        exp.SequenceProperties: exp.Properties.Location.POST_EXPRESSION,
        exp.TriggerProperties: exp.Properties.Location.POST_EXPRESSION,
        exp.SortKeyProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SqlReadWriteProperty: exp.Properties.Location.POST_SCHEMA,
        exp.SqlSecurityProperty: exp.Properties.Location.POST_SCHEMA,
        exp.StabilityProperty: exp.Properties.Location.POST_SCHEMA,
        exp.StorageHandlerProperty: exp.Properties.Location.POST_SCHEMA,
        exp.StreamingTableProperty: exp.Properties.Location.POST_CREATE,
        exp.StrictProperty: exp.Properties.Location.POST_SCHEMA,
        exp.Tags: exp.Properties.Location.POST_WITH,
        exp.TemporaryProperty: exp.Properties.Location.POST_CREATE,
        exp.ToTableProperty: exp.Properties.Location.POST_SCHEMA,
        exp.TransientProperty: exp.Properties.Location.POST_CREATE,
        exp.TransformModelProperty: exp.Properties.Location.POST_SCHEMA,
        exp.MergeTreeTTL: exp.Properties.Location.POST_SCHEMA,
        exp.UnloggedProperty: exp.Properties.Location.POST_CREATE,
        exp.UsingProperty: exp.Properties.Location.POST_EXPRESSION,
        exp.UsingTemplateProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ViewAttributeProperty: exp.Properties.Location.POST_SCHEMA,
        exp.VirtualProperty: exp.Properties.Location.POST_CREATE,
        exp.VolatileProperty: exp.Properties.Location.POST_CREATE,
        exp.WithDataProperty: exp.Properties.Location.POST_EXPRESSION,
        exp.WithJournalTableProperty: exp.Properties.Location.POST_NAME,
        exp.WithProcedureOptions: exp.Properties.Location.POST_SCHEMA,
        exp.WithSchemaBindingProperty: exp.Properties.Location.POST_SCHEMA,
        exp.WithSystemVersioningProperty: exp.Properties.Location.POST_SCHEMA,
        exp.ForceProperty: exp.Properties.Location.POST_CREATE,
    }

    # Keywords that can't be used as unquoted identifier names
    RESERVED_KEYWORDS: t.ClassVar[set[str]] = set()

    # Exprs whose comments are separated from them for better formatting
    WITH_SEPARATED_COMMENTS: t.ClassVar[tuple[type[exp.Expr], ...]] = (
        exp.Command,
        exp.Create,
        exp.Describe,
        exp.Delete,
        exp.Drop,
        exp.From,
        exp.Insert,
        exp.Join,
        exp.MultitableInserts,
        exp.Order,
        exp.Group,
        exp.Having,
        exp.Select,
        exp.SetOperation,
        exp.Update,
        exp.Where,
        exp.With,
    )

    # Exprs that should not have their comments generated in maybe_comment
    EXCLUDE_COMMENTS: t.ClassVar[tuple[type[exp.Expr], ...]] = (
        exp.Binary,
        exp.SetOperation,
    )

    # Exprs that can remain unwrapped when appearing in the context of an INTERVAL
    UNWRAPPED_INTERVAL_VALUES: t.ClassVar[tuple[type[exp.Expr], ...]] = (
        exp.Column,
        exp.Literal,
        exp.Neg,
        exp.Paren,
    )

    PARAMETERIZABLE_TEXT_TYPES: t.ClassVar = {
        exp.DType.NVARCHAR,
        exp.DType.VARCHAR,
        exp.DType.CHAR,
        exp.DType.NCHAR,
    }

    # Exprs that need to have all CTEs under them bubbled up to them
    EXPRESSIONS_WITHOUT_NESTED_CTES: t.ClassVar[set[type[exp.Expr]]] = set()

    RESPECT_IGNORE_NULLS_UNSUPPORTED_EXPRESSIONS: t.ClassVar[tuple[type[exp.Expr], ...]] = ()

    SAFE_JSON_PATH_KEY_RE: t.ClassVar = exp.SAFE_IDENTIFIER_RE

    SENTINEL_LINE_BREAK = "__SQLGLOT__LB__"

    __slots__ = (
        "pretty",
        "identify",
        "normalize",
        "pad",
        "_indent",
        "normalize_functions",
        "unsupported_level",
        "max_unsupported",
        "leading_comma",
        "max_text_width",
        "comments",
        "dialect",
        "unsupported_messages",
        "_escaped_quote_end",
        "_escaped_byte_quote_end",
        "_escaped_identifier_end",
        "_next_name",
        "_identifier_start",
        "_identifier_end",
        "_quote_json_path_key_using_brackets",
        "_dispatch",
    )

    def __init__(
        self,
        pretty: bool | int | None = None,
        identify: str | bool = False,
        normalize: bool = False,
        pad: int = 2,
        indent: int = 2,
        normalize_functions: str | bool | None = None,
        unsupported_level: ErrorLevel = ErrorLevel.WARN,
        max_unsupported: int = 3,
        leading_comma: bool = False,
        max_text_width: int = 80,
        comments: bool = True,
        dialect: DialectType = None,
    ):
        import sqlglot
        import sqlglot.dialects.dialect

        self.pretty = pretty if pretty is not None else sqlglot.pretty
        self.identify = identify
        self.normalize = normalize
        self.pad = pad
        self._indent = indent
        self.unsupported_level = unsupported_level
        self.max_unsupported = max_unsupported
        self.leading_comma = leading_comma
        self.max_text_width = max_text_width
        self.comments = comments
        self.dialect = sqlglot.dialects.dialect.Dialect.get_or_raise(dialect)

        # This is both a Dialect property and a Generator argument, so we prioritize the latter
        self.normalize_functions = (
            self.dialect.NORMALIZE_FUNCTIONS if normalize_functions is None else normalize_functions
        )

        self.unsupported_messages: list[str] = []
        self._escaped_quote_end: str = (
            self.dialect.tokenizer_class.STRING_ESCAPES[0] + self.dialect.QUOTE_END
        )
        self._escaped_byte_quote_end: str = (
            self.dialect.tokenizer_class.STRING_ESCAPES[0] + self.dialect.BYTE_END
            if self.dialect.BYTE_END
            else ""
        )
        self._escaped_identifier_end = self.dialect.IDENTIFIER_END * 2

        self._next_name = name_sequence("_t")

        self._identifier_start = self.dialect.IDENTIFIER_START
        self._identifier_end = self.dialect.IDENTIFIER_END

        self._quote_json_path_key_using_brackets = True

        cls = type(self)
        dispatch = _DISPATCH_CACHE.get(cls)
        if dispatch is None:
            dispatch = _build_dispatch(cls)
            _DISPATCH_CACHE[cls] = dispatch
        self._dispatch = dispatch

    def generate(self, expression: exp.Expr, copy: bool = True) -> str:
        """
        Generates the SQL string corresponding to the given syntax tree.

        Args:
            expression: The syntax tree.
            copy: Whether to copy the expression. The generator performs mutations so
                it is safer to copy.

        Returns:
            The SQL string corresponding to `expression`.
        """
        if copy:
            expression = expression.copy()

        expression = self.preprocess(expression)

        self.unsupported_messages = []
        sql = self.sql(expression).strip()

        if self.pretty:
            sql = sql.replace(self.SENTINEL_LINE_BREAK, "\n")

        if self.unsupported_level == ErrorLevel.IGNORE:
            return sql

        if self.unsupported_level == ErrorLevel.WARN:
            for msg in self.unsupported_messages:
                logger.warning(msg)
        elif self.unsupported_level == ErrorLevel.RAISE and self.unsupported_messages:
            raise UnsupportedError(concat_messages(self.unsupported_messages, self.max_unsupported))

        return sql

    def preprocess(self, expression: exp.Expr) -> exp.Expr:
        """Apply generic preprocessing transformations to a given expression."""
        expression = self._move_ctes_to_top_level(expression)

        if self.ENSURE_BOOLS:
            import sqlglot.transforms

            expression = sqlglot.transforms.ensure_bools(expression)

        return expression

    def _move_ctes_to_top_level(self, expression: E) -> E:
        if (
            not expression.parent
            and type(expression) in self.EXPRESSIONS_WITHOUT_NESTED_CTES
            and any(node.parent is not expression for node in expression.find_all(exp.With))
        ):
            import sqlglot.transforms

            expression = sqlglot.transforms.move_ctes_to_top_level(expression)
        return expression

    def unsupported(self, message: str) -> None:
        if self.unsupported_level == ErrorLevel.IMMEDIATE:
            raise UnsupportedError(message)
        self.unsupported_messages.append(message)

    def sep(self, sep: str = " ") -> str:
        return f"{sep.strip()}\n" if self.pretty else sep

    def seg(self, sql: str, sep: str = " ") -> str:
        return f"{self.sep(sep)}{sql}"

    def sanitize_comment(self, comment: str) -> str:
        comment = " " + comment if comment[0].strip() else comment
        comment = comment + " " if comment[-1].strip() else comment

        # Escape block comment markers to prevent premature closure or unintended nesting.
        # This is necessary because single-line comments (--) are converted to block comments
        # (/* */) on output, and any */ in the original text would close the comment early.
        comment = comment.replace("*/", "* /").replace("/*", "/ *")

        return comment

    def maybe_comment(
        self,
        sql: str,
        expression: exp.Expr | None = None,
        comments: list[str] | None = None,
        separated: bool = False,
    ) -> str:
        comments = (
            ((expression and expression.comments) if comments is None else comments)  # type: ignore
            if self.comments
            else None
        )

        if not comments or isinstance(expression, self.EXCLUDE_COMMENTS):
            return sql

        comments_sql = " ".join(
            f"/*{self.sanitize_comment(comment)}*/" for comment in comments if comment
        )

        if not comments_sql:
            return sql

        comments_sql = self._replace_line_breaks(comments_sql)

        if separated or isinstance(expression, self.WITH_SEPARATED_COMMENTS):
            return (
                f"{self.sep()}{comments_sql}{sql}"
                if not sql or sql[0].isspace()
                else f"{comments_sql}{self.sep()}{sql}"
            )

        return f"{sql} {comments_sql}"

    def wrap(self, expression: exp.Expr | str) -> str:
        this_sql = (
            self.sql(expression)
            if isinstance(expression, exp.UNWRAPPED_QUERIES)
            else self.sql(expression, "this")
        )
        if not this_sql:
            return "()"

        this_sql = self.indent(this_sql, level=1, pad=0)
        return f"({self.sep('')}{this_sql}{self.seg(')', sep='')}"

    def no_identify(self, func: t.Callable[..., str], *args, **kwargs) -> str:
        pass

    def normalize_func(self, name: str) -> str:
        if self.normalize_functions == "upper" or self.normalize_functions is True:
            return name.upper()
        if self.normalize_functions == "lower":
            return name.lower()
        return name

    def indent(
        self,
        sql: str,
        level: int = 0,
        pad: int | None = None,
        skip_first: bool = False,
        skip_last: bool = False,
    ) -> str:
        if not self.pretty or not sql:
            return sql

        pad = self.pad if pad is None else pad
        lines = sql.split("\n")

        return "\n".join(
            (
                line
                if (skip_first and i == 0) or (skip_last and i == len(lines) - 1)
                else f"{' ' * (level * self._indent + pad)}{line}"
            )
            for i, line in enumerate(lines)
        )

    def sql(
        self,
        expression: str | exp.Expr | None,
        key: str | None = None,
        comment: bool = True,
    ) -> str:
        if not expression:
            return ""

        if isinstance(expression, str):
            return expression

        if key:
            value = expression.args.get(key)
            if value:
                return self.sql(value)
            return ""

        handler = self._dispatch.get(expression.__class__)

        if handler:
            sql = handler(self, expression)
        elif isinstance(expression, exp.Func):
            sql = self.function_fallback_sql(expression)
        elif isinstance(expression, exp.Property):
            sql = self.property_sql(expression)
        else:
            raise ValueError(f"Unsupported expression type {expression.__class__.__name__}")

        return self.maybe_comment(sql, expression) if self.comments and comment else sql

    def uncache_sql(self, expression: exp.Uncache) -> str:
        pass

    def cache_sql(self, expression: exp.Cache) -> str:
        pass

    def characterset_sql(self, expression: exp.CharacterSet) -> str:
        pass

    def column_parts(self, expression: exp.Column) -> str:
        pass

    def column_sql(self, expression: exp.Column) -> str:
        pass

    def pseudocolumn_sql(self, expression: exp.Pseudocolumn) -> str:
        pass

    def columnposition_sql(self, expression: exp.ColumnPosition) -> str:
        pass

    def columndef_sql(self, expression: exp.ColumnDef, sep: str = " ") -> str:
        pass

    def columnconstraint_sql(self, expression: exp.ColumnConstraint) -> str:
        pass

    def computedcolumnconstraint_sql(self, expression: exp.ComputedColumnConstraint) -> str:
        pass

    def autoincrementcolumnconstraint_sql(self, _: exp.AutoIncrementColumnConstraint) -> str:
        pass

    def compresscolumnconstraint_sql(self, expression: exp.CompressColumnConstraint) -> str:
        pass

    def generatedasidentitycolumnconstraint_sql(
        self, expression: exp.GeneratedAsIdentityColumnConstraint
    ) -> str:
        this = ""
        if expression.this is not None:
            on_null = " ON NULL" if expression.args.get("on_null") else ""
            this = " ALWAYS" if expression.this else f" BY DEFAULT{on_null}"

        start = expression.args.get("start")
        start = f"START WITH {start}" if start else ""
        increment = expression.args.get("increment")
        increment = f" INCREMENT BY {increment}" if increment else ""
        minvalue = expression.args.get("minvalue")
        minvalue = f" MINVALUE {minvalue}" if minvalue else ""
        maxvalue = expression.args.get("maxvalue")
        maxvalue = f" MAXVALUE {maxvalue}" if maxvalue else ""
        cycle = expression.args.get("cycle")
        cycle_sql = ""

        if cycle is not None:
            cycle_sql = f"{' NO' if not cycle else ''} CYCLE"
            cycle_sql = cycle_sql.strip() if not start and not increment else cycle_sql

        sequence_opts = ""
        if start or increment or cycle_sql:
            sequence_opts = f"{start}{increment}{minvalue}{maxvalue}{cycle_sql}"
            sequence_opts = f" ({sequence_opts.strip()})"

        expr = self.sql(expression, "expression")
        expr = f"({expr})" if expr else "IDENTITY"

        return f"GENERATED{this} AS {expr}{sequence_opts}"

    def generatedasrowcolumnconstraint_sql(
        self, expression: exp.GeneratedAsRowColumnConstraint
    ) -> str:
        pass

    def periodforsystemtimeconstraint_sql(
        self, expression: exp.PeriodForSystemTimeConstraint
    ) -> str:
        pass

    def notnullcolumnconstraint_sql(self, expression: exp.NotNullColumnConstraint) -> str:
        pass

    def primarykeycolumnconstraint_sql(self, expression: exp.PrimaryKeyColumnConstraint) -> str:
        pass

    def uniquecolumnconstraint_sql(self, expression: exp.UniqueColumnConstraint) -> str:
        pass

    def inoutcolumnconstraint_sql(self, expression: exp.InOutColumnConstraint) -> str:
        pass

    def createable_sql(self, expression: exp.Create, locations: defaultdict) -> str:
        pass

    def create_sql(self, expression: exp.Create) -> str:
        pass

    def sequenceproperties_sql(self, expression: exp.SequenceProperties) -> str:
        pass

    def triggerproperties_sql(self, expression: exp.TriggerProperties) -> str:
        pass

    def triggerreferencing_sql(self, expression: exp.TriggerReferencing) -> str:
        pass

    def triggerevent_sql(self, expression: exp.TriggerEvent) -> str:
        pass

    def clone_sql(self, expression: exp.Clone) -> str:
        pass

    def describe_sql(self, expression: exp.Describe) -> str:
        style = expression.args.get("style")
        style = f" {style}" if style else ""
        partition = self.sql(expression, "partition")
        partition = f" {partition}" if partition else ""
        format = self.sql(expression, "format")
        format = f" {format}" if format else ""
        as_json = " AS JSON" if expression.args.get("as_json") else ""

        return f"DESCRIBE{style}{format} {self.sql(expression, 'this')}{partition}{as_json}"

    def heredoc_sql(self, expression: exp.Heredoc) -> str:
        pass

    def prepend_ctes(self, expression: exp.Expr, sql: str) -> str:
        with_ = self.sql(expression, "with_")
        if with_:
            sql = f"{with_}{self.sep()}{sql}"
        return sql

    def with_sql(self, expression: exp.With) -> str:
        sql = self.expressions(expression, flat=True)
        recursive = (
            "RECURSIVE "
            if self.CTE_RECURSIVE_KEYWORD_REQUIRED and expression.args.get("recursive")
            else ""
        )
        search = self.sql(expression, "search")
        search = f" {search}" if search else ""

        return f"WITH {recursive}{sql}{search}"

    def cte_sql(self, expression: exp.CTE) -> str:
        pass

    def tablealias_sql(self, expression: exp.TableAlias) -> str:
        pass

    def bitstring_sql(self, expression: exp.BitString) -> str:
        pass

    def hexstring_sql(
        self, expression: exp.HexString, binary_function_repr: str | None = None
    ) -> str:
        this = self.sql(expression, "this")
        is_integer_type = expression.args.get("is_integer")

        if (is_integer_type and not self.dialect.HEX_STRING_IS_INTEGER_TYPE) or (
            not self.dialect.HEX_START and not binary_function_repr
        ):
            # Integer representation will be returned if:
            # - The read dialect treats the hex value as integer literal but not the write
            # - The transpilation is not supported (write dialect hasn't set HEX_START or the param flag)
            return f"{int(this, 16)}"

        if not is_integer_type:
            # Read dialect treats the hex value as BINARY/BLOB
            if binary_function_repr:
                # The write dialect supports the transpilation to its equivalent BINARY/BLOB
                return self.func(binary_function_repr, exp.Literal.string(this))
            if self.dialect.HEX_STRING_IS_INTEGER_TYPE:
                # The write dialect does not support the transpilation, it'll treat the hex value as INTEGER
                self.unsupported("Unsupported transpilation from BINARY/BLOB hex string")

        return f"{self.dialect.HEX_START}{this}{self.dialect.HEX_END}"

    def bytestring_sql(self, expression: exp.ByteString) -> str:
        pass

    def unicodestring_sql(self, expression: exp.UnicodeString) -> str:
        pass

    def rawstring_sql(self, expression: exp.RawString) -> str:
        pass

    def datatypeparam_sql(self, expression: exp.DataTypeParam) -> str:
        pass

    def datatype_sql(self, expression: exp.DataType) -> str:
        pass

    def directory_sql(self, expression: exp.Directory) -> str:
        pass

    def delete_sql(self, expression: exp.Delete) -> str:
        pass

    def drop_sql(self, expression: exp.Drop) -> str:
        pass

    def set_operation(self, expression: exp.SetOperation) -> str:
        op_type = type(expression)
        op_name = op_type.key.upper()

        distinct = expression.args.get("distinct")
        if (
            distinct is False
            and op_type in (exp.Except, exp.Intersect)
            and not self.EXCEPT_INTERSECT_SUPPORT_ALL_CLAUSE
        ):
            self.unsupported(f"{op_name} ALL is not supported")

        default_distinct = self.dialect.SET_OP_DISTINCT_BY_DEFAULT[op_type]

        if distinct is None:
            distinct = default_distinct
            if distinct is None:
                self.unsupported(f"{op_name} requires DISTINCT or ALL to be specified")

        if distinct is default_distinct:
            distinct_or_all = ""
        else:
            distinct_or_all = " DISTINCT" if distinct else " ALL"

        side_kind = " ".join(filter(None, [expression.side, expression.kind]))
        side_kind = f"{side_kind} " if side_kind else ""

        by_name = " BY NAME" if expression.args.get("by_name") else ""
        on = self.expressions(expression, key="on", flat=True)
        on = f" ON ({on})" if on else ""

        return f"{side_kind}{op_name}{distinct_or_all}{by_name}{on}"

    def set_operations(self, expression: exp.SetOperation) -> str:
        if not self.SET_OP_MODIFIERS:
            limit = expression.args.get("limit")
            order = expression.args.get("order")

            if limit or order:
                select = self._move_ctes_to_top_level(
                    exp.subquery(expression, "_l_0", copy=False).select("*", copy=False)
                )

                if limit:
                    select = select.limit(limit.pop(), copy=False)
                if order:
                    select = select.order_by(order.pop(), copy=False)
                return self.sql(select)

        sqls: list[str] = []
        stack: list[str | exp.Expr] = [expression]

        while stack:
            node = stack.pop()

            if isinstance(node, exp.SetOperation):
                stack.append(node.expression)
                stack.append(
                    self.maybe_comment(
                        self.set_operation(node), comments=node.comments, separated=True
                    )
                )
                stack.append(node.this)
            else:
                sqls.append(self.sql(node))

        this = self.sep().join(sqls)
        this = self.query_modifiers(expression, this)
        return self.prepend_ctes(expression, this)

    def fetch_sql(self, expression: exp.Fetch) -> str:
        pass

    def limitoptions_sql(self, expression: exp.LimitOptions) -> str:
        pass

    def filter_sql(self, expression: exp.Filter) -> str:
        if self.AGGREGATE_FILTER_SUPPORTED:
            this = self.sql(expression, "this")
            where = self.sql(expression, "expression").strip()
            return f"{this} FILTER({where})"

        agg = expression.this
        agg_arg = agg.this
        cond = expression.expression.this
        agg_arg.replace(exp.If(this=cond.copy(), true=agg_arg.copy()))
        return self.sql(agg)

    def hint_sql(self, expression: exp.Hint) -> str:
        pass

    def indexparameters_sql(self, expression: exp.IndexParameters) -> str:
        pass

    def index_sql(self, expression: exp.Index) -> str:
        pass

    def identifier_sql(self, expression: exp.Identifier) -> str:
        pass

    def hex_sql(self, expression: exp.Hex) -> str:
        pass

    def lowerhex_sql(self, expression: exp.LowerHex) -> str:
        pass

    def inputoutputformat_sql(self, expression: exp.InputOutputFormat) -> str:
        pass

    def national_sql(self, expression: exp.National, prefix: str = "N") -> str:
        string = self.sql(exp.Literal.string(expression.name))
        return f"{prefix}{string}"

    def partition_sql(self, expression: exp.Partition) -> str:
        pass

    def properties_sql(self, expression: exp.Properties) -> str:
        pass

    def root_properties(self, properties: exp.Properties) -> str:
        pass

    def properties(
        self,
        properties: exp.Properties,
        prefix: str = "",
        sep: str = ", ",
        suffix: str = "",
        wrapped: bool = True,
    ) -> str:
        if properties.expressions:
            expressions = self.expressions(properties, sep=sep, indent=False)
            if expressions:
                expressions = self.wrap(expressions) if wrapped else expressions
                return f"{prefix}{' ' if prefix.strip() else ''}{expressions}{suffix}"
        return ""

    def with_properties(self, properties: exp.Properties) -> str:
        pass

    def locate_properties(self, properties: exp.Properties) -> defaultdict:
        pass

    def property_name(self, expression: exp.Property, string_key: bool = False) -> str:
        if isinstance(expression.this, exp.Dot):
            return self.sql(expression, "this")
        return f"'{expression.name}'" if string_key else expression.name

    def property_sql(self, expression: exp.Property) -> str:
        property_cls = expression.__class__
        if property_cls == exp.Property:
            return f"{self.property_name(expression)}={self.sql(expression, 'value')}"

        property_name = exp.Properties.PROPERTY_TO_NAME.get(property_cls)
        if not property_name:
            self.unsupported(f"Unsupported property {expression.key}")

        return f"{property_name}={self.sql(expression, 'this')}"

    def uuidproperty_sql(self, expression: exp.UuidProperty) -> str:
        pass

    def likeproperty_sql(self, expression: exp.LikeProperty) -> str:
        pass

    def fallbackproperty_sql(self, expression: exp.FallbackProperty) -> str:
        pass

    def journalproperty_sql(self, expression: exp.JournalProperty) -> str:
        pass

    def freespaceproperty_sql(self, expression: exp.FreespaceProperty) -> str:
        pass

    def checksumproperty_sql(self, expression: exp.ChecksumProperty) -> str:
        pass

    def mergeblockratioproperty_sql(self, expression: exp.MergeBlockRatioProperty) -> str:
        pass

    def moduleproperty_sql(self, expression: exp.ModuleProperty) -> str:
        pass

    def datablocksizeproperty_sql(self, expression: exp.DataBlocksizeProperty) -> str:
        pass

    def blockcompressionproperty_sql(self, expression: exp.BlockCompressionProperty) -> str:
        pass

    def isolatedloadingproperty_sql(self, expression: exp.IsolatedLoadingProperty) -> str:
        pass

    def partitionboundspec_sql(self, expression: exp.PartitionBoundSpec) -> str:
        pass

    def partitionedofproperty_sql(self, expression: exp.PartitionedOfProperty) -> str:
        pass

    def lockingproperty_sql(self, expression: exp.LockingProperty) -> str:
        pass

    def withdataproperty_sql(self, expression: exp.WithDataProperty) -> str:
        pass

    def withsystemversioningproperty_sql(self, expression: exp.WithSystemVersioningProperty) -> str:
        pass

    def insert_sql(self, expression: exp.Insert) -> str:
        pass

    def introducer_sql(self, expression: exp.Introducer) -> str:
        pass

    def kill_sql(self, expression: exp.Kill) -> str:
        pass

    def pseudotype_sql(self, expression: exp.PseudoType) -> str:
        pass

    def objectidentifier_sql(self, expression: exp.ObjectIdentifier) -> str:
        pass

    def onconflict_sql(self, expression: exp.OnConflict) -> str:
        pass

    def returning_sql(self, expression: exp.Returning) -> str:
        pass

    def rowformatdelimitedproperty_sql(self, expression: exp.RowFormatDelimitedProperty) -> str:
        pass

    def withtablehint_sql(self, expression: exp.WithTableHint) -> str:
        pass

    def indextablehint_sql(self, expression: exp.IndexTableHint) -> str:
        pass

    def historicaldata_sql(self, expression: exp.HistoricalData) -> str:
        pass

    def table_parts(self, expression: exp.Table) -> str:
        return ".".join(
            self.sql(part)
            for part in (
                expression.args.get("catalog"),
                expression.args.get("db"),
                expression.args.get("this"),
            )
            if part is not None
        )

    def table_sql(self, expression: exp.Table, sep: str = " AS ") -> str:
        table = self.table_parts(expression)
        only = "ONLY " if expression.args.get("only") else ""
        partition = self.sql(expression, "partition")
        partition = f" {partition}" if partition else ""
        version = self.sql(expression, "version")
        version = f" {version}" if version else ""
        alias = self.sql(expression, "alias")
        alias = f"{sep}{alias}" if alias else ""

        sample = self.sql(expression, "sample")
        post_alias = ""
        pre_alias = ""

        if self.dialect.ALIAS_POST_TABLESAMPLE:
            pre_alias = sample
        else:
            post_alias = sample

        if self.dialect.ALIAS_POST_VERSION:
            pre_alias = f"{pre_alias}{version}"
        else:
            post_alias = f"{post_alias}{version}"

        hints = self.expressions(expression, key="hints", sep=" ")
        hints = f" {hints}" if hints and self.TABLE_HINTS else ""
        pivots = self.expressions(expression, key="pivots", sep="", flat=True)
        joins = self.indent(
            self.expressions(expression, key="joins", sep="", flat=True), skip_first=True
        )
        laterals = self.expressions(expression, key="laterals", sep="")

        file_format = self.sql(expression, "format")
        if file_format:
            pattern = self.sql(expression, "pattern")
            pattern = f", PATTERN => {pattern}" if pattern else ""
            file_format = f" (FILE_FORMAT => {file_format}{pattern})"

        ordinality = expression.args.get("ordinality") or ""
        if ordinality:
            ordinality = f" WITH ORDINALITY{alias}"
            alias = ""

        when = self.sql(expression, "when")
        if when:
            table = f"{table} {when}"

        changes = self.sql(expression, "changes")
        changes = f" {changes}" if changes else ""

        rows_from = self.expressions(expression, key="rows_from")
        if rows_from:
            table = f"ROWS FROM {self.wrap(rows_from)}"

        indexed = expression.args.get("indexed")
        if indexed is not None:
            indexed = f" INDEXED BY {self.sql(indexed)}" if indexed else " NOT INDEXED"
        else:
            indexed = ""

        return f"{only}{table}{changes}{partition}{file_format}{pre_alias}{alias}{indexed}{hints}{pivots}{post_alias}{joins}{laterals}{ordinality}"

    def tablefromrows_sql(self, expression: exp.TableFromRows) -> str:
        pass

    def tablesample_sql(
        self,
        expression: exp.TableSample,
        tablesample_keyword: str | None = None,
    ) -> str:
        method = self.sql(expression, "method")
        method = f"{method} " if method and self.TABLESAMPLE_WITH_METHOD else ""
        numerator = self.sql(expression, "bucket_numerator")
        denominator = self.sql(expression, "bucket_denominator")
        field = self.sql(expression, "bucket_field")
        field = f" ON {field}" if field else ""
        bucket = f"BUCKET {numerator} OUT OF {denominator}{field}" if numerator else ""
        seed = self.sql(expression, "seed")
        seed = f" {self.TABLESAMPLE_SEED_KEYWORD} ({seed})" if seed else ""

        size = self.sql(expression, "size")
        if size and self.TABLESAMPLE_SIZE_IS_ROWS:
            size = f"{size} ROWS"

        percent = self.sql(expression, "percent")
        if percent and not self.dialect.TABLESAMPLE_SIZE_IS_PERCENT:
            percent = f"{percent} PERCENT"

        expr = f"{bucket}{percent}{size}"
        if self.TABLESAMPLE_REQUIRES_PARENS:
            expr = f"({expr})"

        return f" {tablesample_keyword or self.TABLESAMPLE_KEYWORDS} {method}{expr}{seed}"

    def pivot_sql(self, expression: exp.Pivot) -> str:
        pass

    def version_sql(self, expression: exp.Version) -> str:
        pass

    def tuple_sql(self, expression: exp.Tuple) -> str:
        pass

    def _update_from_joins_sql(self, expression: exp.Update) -> tuple[str, str]:
        """
        Returns (join_sql, from_sql) for UPDATE statements.
        - join_sql: placed after UPDATE table, before SET
        - from_sql: placed after SET clause (standard position)
        Dialects like MySQL need to convert FROM to JOIN syntax.
        """
        pass

    def update_sql(self, expression: exp.Update) -> str:
        pass

    def values_sql(self, expression: exp.Values, values_as_table: bool = True) -> str:
        pass

    def var_sql(self, expression: exp.Var) -> str:
        pass

    @unsupported_args("expressions")
    def into_sql(self, expression: exp.Into) -> str:
        pass

    def from_sql(self, expression: exp.From) -> str:
        pass

    def groupingsets_sql(self, expression: exp.GroupingSets) -> str:
        pass

    def rollup_sql(self, expression: exp.Rollup) -> str:
        pass

    def rollupindex_sql(self, expression: exp.RollupIndex) -> str:
        pass

    def rollupproperty_sql(self, expression: exp.RollupProperty) -> str:
        pass

    def cube_sql(self, expression: exp.Cube) -> str:
        pass

    def group_sql(self, expression: exp.Group) -> str:
        pass

    def having_sql(self, expression: exp.Having) -> str:
        pass

    def connect_sql(self, expression: exp.Connect) -> str:
        pass

    def prior_sql(self, expression: exp.Prior) -> str:
        pass

    def join_sql(self, expression: exp.Join) -> str:
        pass

    def lambda_sql(self, expression: exp.Lambda, arrow_sep: str = "->", wrap: bool = True) -> str:
        pass

    def lateral_op(self, expression: exp.Lateral) -> str:
        cross_apply = expression.args.get("cross_apply")

        # https://www.mssqltips.com/sqlservertip/1958/sql-server-cross-apply-and-outer-apply/
        if cross_apply is True:
            op = "INNER JOIN "
        elif cross_apply is False:
            op = "LEFT JOIN "
        else:
            op = ""

        return f"{op}LATERAL"

    def lateral_sql(self, expression: exp.Lateral) -> str:
        this = self.sql(expression, "this")

        if expression.args.get("view"):
            alias = expression.args["alias"]
            columns = self.expressions(alias, key="columns", flat=True)
            table = f" {alias.name}" if alias.name else ""
            columns = f" AS {columns}" if columns else ""
            op_sql = self.seg(f"LATERAL VIEW{' OUTER' if expression.args.get('outer') else ''}")
            return f"{op_sql}{self.sep()}{this}{table}{columns}"

        alias = self.sql(expression, "alias")
        alias = f" AS {alias}" if alias else ""

        ordinality = expression.args.get("ordinality") or ""
        if ordinality:
            ordinality = f" WITH ORDINALITY{alias}"
            alias = ""

        return f"{self.lateral_op(expression)} {this}{alias}{ordinality}"

    def limit_sql(self, expression: exp.Limit, top: bool = False) -> str:
        pass

    def offset_sql(self, expression: exp.Offset) -> str:
        pass

    def setitem_sql(self, expression: exp.SetItem) -> str:
        pass

    def set_sql(self, expression: exp.Set) -> str:
        pass

    def queryband_sql(self, expression: exp.QueryBand) -> str:
        pass

    def pragma_sql(self, expression: exp.Pragma) -> str:
        pass

    def lock_sql(self, expression: exp.Lock) -> str:
        pass

    def literal_sql(self, expression: exp.Literal) -> str:
        pass

    def escape_str(
        self,
        text: str,
        escape_backslash: bool = True,
        delimiter: str | None = None,
        escaped_delimiter: str | None = None,
        is_byte_string: bool = False,
    ) -> str:
        if is_byte_string:
            supports_escape_sequences = self.dialect.BYTE_STRINGS_SUPPORT_ESCAPED_SEQUENCES
        else:
            supports_escape_sequences = self.dialect.STRINGS_SUPPORT_ESCAPED_SEQUENCES

        if supports_escape_sequences:
            text = "".join(
                self.dialect.ESCAPED_SEQUENCES.get(ch, ch) if escape_backslash or ch != "\\" else ch
                for ch in text
            )

        delimiter = delimiter or self.dialect.QUOTE_END
        escaped_delimiter = escaped_delimiter or self._escaped_quote_end

        return self._replace_line_breaks(text).replace(delimiter, escaped_delimiter)

    def loaddata_sql(self, expression: exp.LoadData) -> str:
        pass

    def null_sql(self, *_) -> str:
        pass

    def boolean_sql(self, expression: exp.Boolean) -> str:
        pass

    def booland_sql(self, expression: exp.Booland) -> str:
        pass

    def boolor_sql(self, expression: exp.Boolor) -> str:
        pass

    def order_sql(self, expression: exp.Order, flat: bool = False) -> str:
        this = self.sql(expression, "this")
        this = f"{this} " if this else this
        siblings = "SIBLINGS " if expression.args.get("siblings") else ""
        return self.op_expressions(f"{this}ORDER {siblings}BY", expression, flat=bool(this) or flat)

    def withfill_sql(self, expression: exp.WithFill) -> str:
        pass

    def cluster_sql(self, expression: exp.Cluster) -> str:
        pass

    def distribute_sql(self, expression: exp.Distribute) -> str:
        pass

    def sort_sql(self, expression: exp.Sort) -> str:
        pass

    def ordered_sql(self, expression: exp.Ordered) -> str:
        pass

    def matchrecognizemeasure_sql(self, expression: exp.MatchRecognizeMeasure) -> str:
        pass

    def matchrecognize_sql(self, expression: exp.MatchRecognize) -> str:
        pass

    def query_modifiers(self, expression: exp.Expr, *sqls: str) -> str:
        limit = expression.args.get("limit")

        if self.LIMIT_FETCH == "LIMIT" and isinstance(limit, exp.Fetch):
            limit = exp.Limit(expression=exp.maybe_copy(limit.args.get("count")))
        elif self.LIMIT_FETCH == "FETCH" and isinstance(limit, exp.Limit):
            limit = exp.Fetch(direction="FIRST", count=exp.maybe_copy(limit.expression))

        return csv(
            *sqls,
            *[self.sql(join) for join in expression.args.get("joins") or []],
            self.sql(expression, "match"),
            *[self.sql(lateral) for lateral in expression.args.get("laterals") or []],
            self.sql(expression, "prewhere"),
            self.sql(expression, "where"),
            self.sql(expression, "connect"),
            self.sql(expression, "group"),
            self.sql(expression, "having"),
            *[gen(self, expression) for gen in self.AFTER_HAVING_MODIFIER_TRANSFORMS.values()],
            self.sql(expression, "order"),
            *self.offset_limit_modifiers(expression, isinstance(limit, exp.Fetch), limit),
            *self.after_limit_modifiers(expression),
            self.options_modifier(expression),
            self.for_modifiers(expression),
            sep="",
        )

    def options_modifier(self, expression: exp.Expr) -> str:
        options = self.expressions(expression, key="options")
        return f" {options}" if options else ""

    def for_modifiers(self, expression: exp.Expr) -> str:
        for_modifiers = self.expressions(expression, key="for_")
        return f"{self.sep()}FOR XML{self.seg(for_modifiers)}" if for_modifiers else ""

    def queryoption_sql(self, expression: exp.QueryOption) -> str:
        pass

    def offset_limit_modifiers(
        self, expression: exp.Expr, fetch: bool, limit: exp.Fetch | exp.Limit | None
    ) -> list[str]:
        return [
            self.sql(expression, "offset") if fetch else self.sql(limit),
            self.sql(limit) if fetch else self.sql(expression, "offset"),
        ]

    def after_limit_modifiers(self, expression: exp.Expr) -> list[str]:
        locks = self.expressions(expression, key="locks", sep=" ")
        locks = f" {locks}" if locks else ""
        return [locks, self.sql(expression, "sample")]

    def select_sql(self, expression: exp.Select) -> str:
        pass

    def schema_sql(self, expression: exp.Schema) -> str:
        pass

    def schema_columns_sql(self, expression: exp.Expr) -> str:
        pass

    def star_sql(self, expression: exp.Star) -> str:
        pass

    def parameter_sql(self, expression: exp.Parameter) -> str:
        pass

    def sessionparameter_sql(self, expression: exp.SessionParameter) -> str:
        pass

    def placeholder_sql(self, expression: exp.Placeholder) -> str:
        pass

    def subquery_sql(self, expression: exp.Subquery, sep: str = " AS ") -> str:
        alias = self.sql(expression, "alias")
        alias = f"{sep}{alias}" if alias else ""
        sample = self.sql(expression, "sample")
        if self.dialect.ALIAS_POST_TABLESAMPLE and sample:
            alias = f"{sample}{alias}"

            # Set to None so it's not generated again by self.query_modifiers()
            expression.set("sample", None)

        pivots = self.expressions(expression, key="pivots", sep="", flat=True)
        sql = self.query_modifiers(expression, self.wrap(expression), alias, pivots)
        return self.prepend_ctes(expression, sql)

    def qualify_sql(self, expression: exp.Qualify) -> str:
        pass

    def unnest_sql(self, expression: exp.Unnest) -> str:
        pass

    def prewhere_sql(self, expression: exp.PreWhere) -> str:
        pass

    def where_sql(self, expression: exp.Where) -> str:
        pass

    def window_sql(self, expression: exp.Window) -> str:
        this = self.sql(expression, "this")
        partition = self.partition_by_sql(expression)
        order = expression.args.get("order")
        order = self.order_sql(order, flat=True) if order else ""
        spec = self.sql(expression, "spec")
        alias = self.sql(expression, "alias")
        over = self.sql(expression, "over") or "OVER"

        this = f"{this} {'AS' if expression.arg_key == 'windows' else over}"

        first = expression.args.get("first")
        if first is None:
            first = ""
        else:
            first = "FIRST" if first else "LAST"

        if not partition and not order and not spec and alias:
            return f"{this} {alias}"

        args = self.format_args(
            *[arg for arg in (alias, first, partition, order, spec) if arg], sep=" "
        )
        return f"{this} ({args})"

    def partition_by_sql(self, expression: exp.Window | exp.MatchRecognize) -> str:
        partition = self.expressions(expression, key="partition_by", flat=True)
        return f"PARTITION BY {partition}" if partition else ""

    def windowspec_sql(self, expression: exp.WindowSpec) -> str:
        pass

    def withingroup_sql(self, expression: exp.WithinGroup) -> str:
        pass

    def between_sql(self, expression: exp.Between) -> str:
        pass

    def bracket_offset_expressions(
        self, expression: exp.Bracket, index_offset: int | None = None
    ) -> list[exp.Expr]:
        pass

    def bracket_sql(self, expression: exp.Bracket) -> str:
        pass

    def all_sql(self, expression: exp.All) -> str:
        pass

    def any_sql(self, expression: exp.Any) -> str:
        pass

    def exists_sql(self, expression: exp.Exists) -> str:
        pass

    def case_sql(self, expression: exp.Case) -> str:
        this = self.sql(expression, "this")
        statements = [f"CASE {this}" if this else "CASE"]

        for e in expression.args["ifs"]:
            statements.append(f"WHEN {self.sql(e, 'this')}")
            statements.append(f"THEN {self.sql(e, 'true')}")

        default = self.sql(expression, "default")

        if default:
            statements.append(f"ELSE {default}")

        statements.append("END")

        if self.pretty and self.too_wide(statements):
            return self.indent("\n".join(statements), skip_first=True, skip_last=True)

        return " ".join(statements)

    def constraint_sql(self, expression: exp.Constraint) -> str:
        pass

    def nextvaluefor_sql(self, expression: exp.NextValueFor) -> str:
        pass

    def extract_sql(self, expression: exp.Extract) -> str:
        pass

    def trim_sql(self, expression: exp.Trim) -> str:
        trim_type = self.sql(expression, "position")

        if trim_type == "LEADING":
            func_name = "LTRIM"
        elif trim_type == "TRAILING":
            func_name = "RTRIM"
        else:
            func_name = "TRIM"

        return self.func(func_name, expression.this, expression.expression)

    def convert_concat_args(self, expression: exp.Func) -> list[exp.Expr]:
        pass

    def concat_sql(self, expression: exp.Concat) -> str:
        pass

    def concatws_sql(self, expression: exp.ConcatWs) -> str:
        pass

    def check_sql(self, expression: exp.Check) -> str:
        pass

    def foreignkey_sql(self, expression: exp.ForeignKey) -> str:
        pass

    def primarykey_sql(self, expression: exp.PrimaryKey) -> str:
        pass

    def if_sql(self, expression: exp.If) -> str:
        return self.case_sql(exp.Case(ifs=[expression], default=expression.args.get("false")))

    def matchagainst_sql(self, expression: exp.MatchAgainst) -> str:
        if self.MATCH_AGAINST_TABLE_PREFIX:
            expressions = []
            for expr in expression.expressions:
                if isinstance(expr, exp.Table):
                    expressions.append(f"TABLE {self.sql(expr)}")
                else:
                    expressions.append(expr)
        else:
            expressions = expression.expressions

        modifier = expression.args.get("modifier")
        modifier = f" {modifier}" if modifier else ""
        return (
            f"{self.func('MATCH', *expressions)} AGAINST({self.sql(expression, 'this')}{modifier})"
        )

    def jsonkeyvalue_sql(self, expression: exp.JSONKeyValue) -> str:
        pass

    def jsonpath_sql(self, expression: exp.JSONPath) -> str:
        pass

    def json_path_part(self, expression: int | str | exp.JSONPathPart) -> str:
        if isinstance(expression, exp.JSONPathPart):
            transform = self.TRANSFORMS.get(expression.__class__)
            if not callable(transform):
                self.unsupported(f"Unsupported JSONPathPart type {expression.__class__.__name__}")
                return ""

            return transform(self, expression)

        if isinstance(expression, int):
            return str(expression)

        if self._quote_json_path_key_using_brackets and self.JSON_PATH_SINGLE_QUOTE_ESCAPE:
            escaped = expression.replace("'", "\\'")
            escaped = f"\\'{expression}\\'"
        else:
            escaped = expression.replace('"', '\\"')
            escaped = f'"{escaped}"'

        return escaped

    def formatjson_sql(self, expression: exp.FormatJson) -> str:
        pass

    def formatphrase_sql(self, expression: exp.FormatPhrase) -> str:
        # Output the Teradata column FORMAT override.
        # https://docs.teradata.com/r/Enterprise_IntelliFlex_VMware/SQL-Data-Types-and-Literals/Data-Type-Formats-and-Format-Phrases/FORMAT
        pass

    def _jsonobject_sql(
        self, expression: exp.JSONObject | exp.JSONObjectAgg, name: str = ""
    ) -> str:
        null_handling = expression.args.get("null_handling")
        null_handling = f" {null_handling}" if null_handling else ""

        unique_keys = expression.args.get("unique_keys")
        if unique_keys is not None:
            unique_keys = f" {'WITH' if unique_keys else 'WITHOUT'} UNIQUE KEYS"
        else:
            unique_keys = ""

        return_type = self.sql(expression, "return_type")
        return_type = f" RETURNING {return_type}" if return_type else ""
        encoding = self.sql(expression, "encoding")
        encoding = f" ENCODING {encoding}" if encoding else ""

        if not name:
            name = "JSON_OBJECT" if isinstance(expression, exp.JSONObject) else "JSON_OBJECTAGG"

        return self.func(
            name,
            *expression.expressions,
            suffix=f"{null_handling}{unique_keys}{return_type}{encoding})",
        )

    def jsonarray_sql(self, expression: exp.JSONArray) -> str:
        pass

    def jsonarrayagg_sql(self, expression: exp.JSONArrayAgg) -> str:
        pass

    def jsoncolumndef_sql(self, expression: exp.JSONColumnDef) -> str:
        pass

    def jsonschema_sql(self, expression: exp.JSONSchema) -> str:
        pass

    def jsontable_sql(self, expression: exp.JSONTable) -> str:
        pass

    def openjsoncolumndef_sql(self, expression: exp.OpenJSONColumnDef) -> str:
        pass

    def openjson_sql(self, expression: exp.OpenJSON) -> str:
        pass

    def in_sql(self, expression: exp.In) -> str:
        pass

    def in_unnest_op(self, unnest: exp.Unnest) -> str:
        pass

    def interval_sql(self, expression: exp.Interval) -> str:
        pass

    def return_sql(self, expression: exp.Return) -> str:
        pass

    def reference_sql(self, expression: exp.Reference) -> str:
        pass

    def anonymous_sql(self, expression: exp.Anonymous) -> str:
        # We don't normalize qualified functions such as a.b.foo(), because they can be case-sensitive
        pass

    def paren_sql(self, expression: exp.Paren) -> str:
        pass

    def neg_sql(self, expression: exp.Neg) -> str:
        # This makes sure we don't convert "- - 5" to "--5", which is a comment
        pass

    def not_sql(self, expression: exp.Not) -> str:
        pass

    def alias_sql(self, expression: exp.Alias) -> str:
        pass

    def pivotalias_sql(self, expression: exp.PivotAlias) -> str:
        pass

    def aliases_sql(self, expression: exp.Aliases) -> str:
        pass

    def atindex_sql(self, expression: exp.AtIndex) -> str:
        pass

    def attimezone_sql(self, expression: exp.AtTimeZone) -> str:
        pass

    def fromtimezone_sql(self, expression: exp.FromTimeZone) -> str:
        pass

    def add_sql(self, expression: exp.Add) -> str:
        pass

    def and_sql(self, expression: exp.And, stack: list[str | exp.Expr] | None = None) -> str:
        pass

    def or_sql(self, expression: exp.Or, stack: list[str | exp.Expr] | None = None) -> str:
        pass

    def xor_sql(self, expression: exp.Xor, stack: list[str | exp.Expr] | None = None) -> str:
        pass

    def connector_sql(
        self,
        expression: exp.Connector,
        op: str,
        stack: list[str | exp.Expr] | None = None,
    ) -> str:
        pass

    def bitwiseand_sql(self, expression: exp.BitwiseAnd) -> str:
        pass

    def bitwiseleftshift_sql(self, expression: exp.BitwiseLeftShift) -> str:
        pass

    def bitwisenot_sql(self, expression: exp.BitwiseNot) -> str:
        pass

    def bitwiseor_sql(self, expression: exp.BitwiseOr) -> str:
        pass

    def bitwiserightshift_sql(self, expression: exp.BitwiseRightShift) -> str:
        pass

    def bitwisexor_sql(self, expression: exp.BitwiseXor) -> str:
        pass

    def cast_sql(self, expression: exp.Cast, safe_prefix: str | None = None) -> str:
        format_sql = self.sql(expression, "format")
        format_sql = f" FORMAT {format_sql}" if format_sql else ""
        to_sql = self.sql(expression, "to")
        to_sql = f" {to_sql}" if to_sql else ""
        action = self.sql(expression, "action")
        action = f" {action}" if action else ""
        default = self.sql(expression, "default")
        default = f" DEFAULT {default} ON CONVERSION ERROR" if default else ""
        return f"{safe_prefix or ''}CAST({self.sql(expression, 'this')} AS{to_sql}{default}{format_sql}{action})"

    # Base implementation that excludes safe, zone, and target_type metadata args
    def strtotime_sql(self, expression: exp.StrToTime) -> str:
        pass

    def currentdate_sql(self, expression: exp.CurrentDate) -> str:
        pass

    def collate_sql(self, expression: exp.Collate) -> str:
        pass

    def command_sql(self, expression: exp.Command) -> str:
        pass

    def comment_sql(self, expression: exp.Comment) -> str:
        pass

    def mergetreettlaction_sql(self, expression: exp.MergeTreeTTLAction) -> str:
        pass

    def mergetreettl_sql(self, expression: exp.MergeTreeTTL) -> str:
        pass

    def transaction_sql(self, expression: exp.Transaction) -> str:
        pass

    def commit_sql(self, expression: exp.Commit) -> str:
        pass

    def rollback_sql(self, expression: exp.Rollback) -> str:
        pass

    def altercolumn_sql(self, expression: exp.AlterColumn) -> str:
        pass

    def alterindex_sql(self, expression: exp.AlterIndex) -> str:
        pass

    def alterdiststyle_sql(self, expression: exp.AlterDistStyle) -> str:
        pass

    def altersortkey_sql(self, expression: exp.AlterSortKey) -> str:
        pass

    def alterrename_sql(self, expression: exp.AlterRename, include_to: bool = True) -> str:
        pass

    def renamecolumn_sql(self, expression: exp.RenameColumn) -> str:
        pass

    def alterset_sql(self, expression: exp.AlterSet) -> str:
        pass

    def alter_sql(self, expression: exp.Alter) -> str:
        pass

    def altersession_sql(self, expression: exp.AlterSession) -> str:
        pass

    def add_column_sql(self, expression: exp.Expr) -> str:
        pass

    def droppartition_sql(self, expression: exp.DropPartition) -> str:
        pass

    def addconstraint_sql(self, expression: exp.AddConstraint) -> str:
        pass

    def addpartition_sql(self, expression: exp.AddPartition) -> str:
        pass

    def distinct_sql(self, expression: exp.Distinct) -> str:
        pass

    def ignorenulls_sql(self, expression: exp.IgnoreNulls) -> str:
        pass

    def respectnulls_sql(self, expression: exp.RespectNulls) -> str:
        pass

    def havingmax_sql(self, expression: exp.HavingMax) -> str:
        pass

    def intdiv_sql(self, expression: exp.IntDiv) -> str:
        pass

    def dpipe_sql(self, expression: exp.DPipe) -> str:
        pass

    def div_sql(self, expression: exp.Div) -> str:
        pass

    def safedivide_sql(self, expression: exp.SafeDivide) -> str:
        pass

    def overlaps_sql(self, expression: exp.Overlaps) -> str:
        pass

    def distance_sql(self, expression: exp.Distance) -> str:
        pass

    def dot_sql(self, expression: exp.Dot) -> str:
        pass

    def eq_sql(self, expression: exp.EQ) -> str:
        pass

    def propertyeq_sql(self, expression: exp.PropertyEQ) -> str:
        pass

    def escape_sql(self, expression: exp.Escape) -> str:
        pass

    def glob_sql(self, expression: exp.Glob) -> str:
        pass

    def gt_sql(self, expression: exp.GT) -> str:
        pass

    def gte_sql(self, expression: exp.GTE) -> str:
        pass

    def is_sql(self, expression: exp.Is) -> str:
        pass

    def _like_sql(
        self,
        expression: exp.Like | exp.ILike,
        escape: exp.Escape | None = None,
    ) -> str:
        this = expression.this
        rhs = expression.expression

        if isinstance(expression, exp.Like):
            exp_class: type[exp.Like | exp.ILike] = exp.Like
            op = "LIKE"
        else:
            exp_class = exp.ILike
            op = "ILIKE"

        if isinstance(rhs, (exp.All, exp.Any)) and not self.SUPPORTS_LIKE_QUANTIFIERS:
            exprs = rhs.this.unnest()

            if isinstance(exprs, exp.Tuple):
                exprs = exprs.expressions
            else:
                exprs = [exprs]

            connective = exp.or_ if isinstance(rhs, exp.Any) else exp.and_

            def _make_like(expr: exp.Expression) -> exp.Expression:
                like: exp.Expression = exp_class(this=this, expression=expr)
                if escape:
                    like = exp.Escape(this=like, expression=escape.expression.copy())
                return like

            like_expr: exp.Expr = _make_like(exprs[0])
            for expr in exprs[1:]:
                like_expr = connective(like_expr, _make_like(expr), copy=False)

            parent = escape.parent if escape else expression.parent
            if not isinstance(parent, (type(like_expr), exp.Paren)) and isinstance(
                parent, exp.Condition
            ):
                like_expr = exp.paren(like_expr, copy=False)

            return self.sql(like_expr)

        return self.binary(expression, op)

    def like_sql(self, expression: exp.Like) -> str:
        return self._like_sql(expression)

    def ilike_sql(self, expression: exp.ILike) -> str:
        pass

    def match_sql(self, expression: exp.Match) -> str:
        pass

    def similarto_sql(self, expression: exp.SimilarTo) -> str:
        pass

    def lt_sql(self, expression: exp.LT) -> str:
        pass

    def lte_sql(self, expression: exp.LTE) -> str:
        pass

    def mod_sql(self, expression: exp.Mod) -> str:
        pass

    def mul_sql(self, expression: exp.Mul) -> str:
        pass

    def neq_sql(self, expression: exp.NEQ) -> str:
        pass

    def nullsafeeq_sql(self, expression: exp.NullSafeEQ) -> str:
        pass

    def nullsafeneq_sql(self, expression: exp.NullSafeNEQ) -> str:
        pass

    def sub_sql(self, expression: exp.Sub) -> str:
        pass

    def trycast_sql(self, expression: exp.TryCast) -> str:
        return self.cast_sql(expression, safe_prefix="TRY_")

    def jsoncast_sql(self, expression: exp.JSONCast) -> str:
        pass

    def try_sql(self, expression: exp.Try) -> str:
        pass

    def log_sql(self, expression: exp.Log) -> str:
        pass

    def use_sql(self, expression: exp.Use) -> str:
        pass

    def binary(self, expression: exp.Binary, op: str) -> str:
        sqls: list[str] = []
        stack: list[None | str | exp.Expr] = [expression]
        binary_type = type(expression)

        while stack:
            node = stack.pop()

            if type(node) is binary_type:
                op_func = node.args.get("operator")
                if op_func:
                    op = f"OPERATOR({self.sql(op_func)})"

                stack.append(node.args.get("expression"))
                stack.append(f" {self.maybe_comment(op, comments=node.comments)} ")
                stack.append(node.args.get("this"))
            else:
                sqls.append(self.sql(node))

        return "".join(sqls)

    def ceil_floor(self, expression: exp.Ceil | exp.Floor) -> str:
        to_clause = self.sql(expression, "to")
        if to_clause:
            return f"{expression.sql_name()}({self.sql(expression, 'this')} TO {to_clause})"

        return self.function_fallback_sql(expression)

    def function_fallback_sql(self, expression: exp.Func) -> str:
        args = []

        for key in expression.arg_types:
            arg_value = expression.args.get(key)

            if isinstance(arg_value, list):
                for value in arg_value:
                    args.append(value)
            elif arg_value is not None:
                args.append(arg_value)

        if self.dialect.PRESERVE_ORIGINAL_NAMES:
            name = (expression._meta and expression.meta.get("name")) or expression.sql_name()
        else:
            name = expression.sql_name()

        return self.func(name, *args)

    def func(
        self,
        name: str,
        *args: t.Any,
        prefix: str = "(",
        suffix: str = ")",
        normalize: bool = True,
    ) -> str:
        name = self.normalize_func(name) if normalize else name
        return f"{name}{prefix}{self.format_args(*args)}{suffix}"

    def format_args(self, *args: t.Any, sep: str = ", ") -> str:
        arg_sqls = tuple(
            self.sql(arg) for arg in args if arg is not None and not isinstance(arg, bool)
        )
        if self.pretty and self.too_wide(arg_sqls):
            return self.indent(
                "\n" + f"{sep.strip()}\n".join(arg_sqls) + "\n", skip_first=True, skip_last=True
            )
        return sep.join(arg_sqls)

    def too_wide(self, args: t.Iterable) -> bool:
        return sum(len(arg) for arg in args) > self.max_text_width

    def format_time(
        self,
        expression: exp.Expr,
        inverse_time_mapping: dict[str, str] | None = None,
        inverse_time_trie: dict | None = None,
    ) -> str | None:
        return format_time(
            self.sql(expression, "format"),
            inverse_time_mapping or self.dialect.INVERSE_TIME_MAPPING,
            inverse_time_trie or self.dialect.INVERSE_TIME_TRIE,
        )

    def expressions(
        self,
        expression: exp.Expr | None = None,
        key: str | None = None,
        sqls: t.Collection[str | exp.Expr] | None = None,
        flat: bool = False,
        indent: bool = True,
        skip_first: bool = False,
        skip_last: bool = False,
        sep: str = ", ",
        prefix: str = "",
        dynamic: bool = False,
        new_line: bool = False,
    ) -> str:
        expressions = expression.args.get(key or "expressions") if expression else sqls

        if not expressions:
            return ""

        if flat:
            return sep.join(sql for sql in (self.sql(e) for e in expressions) if sql)

        num_sqls = len(expressions)
        result_sqls = []

        for i, e in enumerate(expressions):
            sql = self.sql(e, comment=False)
            if not sql:
                continue

            comments = self.maybe_comment("", e) if isinstance(e, exp.Expr) else ""

            if self.pretty:
                if self.leading_comma:
                    result_sqls.append(f"{sep if i > 0 else ''}{prefix}{sql}{comments}")
                else:
                    result_sqls.append(
                        f"{prefix}{sql}{(sep.rstrip() if comments else sep) if i + 1 < num_sqls else ''}{comments}"
                    )
            else:
                result_sqls.append(f"{prefix}{sql}{comments}{sep if i + 1 < num_sqls else ''}")

        if self.pretty and (not dynamic or self.too_wide(result_sqls)):
            if new_line:
                result_sqls.insert(0, "")
                result_sqls.append("")
            result_sql = "\n".join(s.rstrip() for s in result_sqls)
        else:
            result_sql = "".join(result_sqls)

        return (
            self.indent(result_sql, skip_first=skip_first, skip_last=skip_last)
            if indent
            else result_sql
        )

    def op_expressions(self, op: str, expression: exp.Expr, flat: bool = False) -> str:
        flat = flat or isinstance(expression.parent, exp.Properties)
        expressions_sql = self.expressions(expression, flat=flat)
        if flat:
            return f"{op} {expressions_sql}"
        return f"{self.seg(op)}{self.sep() if expressions_sql else ''}{expressions_sql}"

    def naked_property(self, expression: exp.Property) -> str:
        property_name = exp.Properties.PROPERTY_TO_NAME.get(expression.__class__)
        if not property_name:
            self.unsupported(f"Unsupported property {expression.__class__.__name__}")
        return f"{property_name} {self.sql(expression, 'this')}"

    def tag_sql(self, expression: exp.Tag) -> str:
        pass

    def token_sql(self, token_type: TokenType) -> str:
        pass

    def userdefinedfunction_sql(self, expression: exp.UserDefinedFunction) -> str:
        pass

    def joinhint_sql(self, expression: exp.JoinHint) -> str:
        pass

    def kwarg_sql(self, expression: exp.Kwarg) -> str:
        pass

    def when_sql(self, expression: exp.When) -> str:
        pass

    def whens_sql(self, expression: exp.Whens) -> str:
        pass

    def merge_sql(self, expression: exp.Merge) -> str:
        table = expression.this
        table_alias = ""

        hints = table.args.get("hints")
        if hints and table.alias and isinstance(hints[0], exp.WithTableHint):
            # T-SQL syntax is MERGE ... <target_table> [WITH (<merge_hint>)] [[AS] table_alias]
            table_alias = f" AS {self.sql(table.args['alias'].pop())}"

        this = self.sql(table)
        using = f"USING {self.sql(expression, 'using')}"
        whens = self.sql(expression, "whens")

        on = self.sql(expression, "on")
        on = f"ON {on}" if on else ""

        if not on:
            on = self.expressions(expression, key="using_cond")
            on = f"USING ({on})" if on else ""

        returning = self.sql(expression, "returning")
        if returning:
            whens = f"{whens}{returning}"

        sep = self.sep()

        return self.prepend_ctes(
            expression,
            f"MERGE INTO {this}{table_alias}{sep}{using}{sep}{on}{sep}{whens}",
        )

    @unsupported_args("format")
    def tochar_sql(self, expression: exp.ToChar) -> str:
        return self.sql(exp.cast(expression.this, exp.DType.TEXT))

    def tonumber_sql(self, expression: exp.ToNumber) -> str:
        pass

    def dictproperty_sql(self, expression: exp.DictProperty) -> str:
        pass

    def dictrange_sql(self, expression: exp.DictRange) -> str:
        pass

    def dictsubproperty_sql(self, expression: exp.DictSubProperty) -> str:
        pass

    def duplicatekeyproperty_sql(self, expression: exp.DuplicateKeyProperty) -> str:
        pass

    # https://docs.starrocks.io/docs/sql-reference/sql-statements/table_bucket_part_index/CREATE_TABLE/
    def uniquekeyproperty_sql(
        self, expression: exp.UniqueKeyProperty, prefix: str = "UNIQUE KEY"
    ) -> str:
        pass

    # https://docs.starrocks.io/docs/sql-reference/sql-statements/data-definition/CREATE_TABLE/#distribution_desc
    def distributedbyproperty_sql(self, expression: exp.DistributedByProperty) -> str:
        pass

    def oncluster_sql(self, expression: exp.OnCluster) -> str:
        pass

    def clusteredbyproperty_sql(self, expression: exp.ClusteredByProperty) -> str:
        pass

    def anyvalue_sql(self, expression: exp.AnyValue) -> str:
        pass

    def querytransform_sql(self, expression: exp.QueryTransform) -> str:
        pass

    def indexconstraintoption_sql(self, expression: exp.IndexConstraintOption) -> str:
        pass

    def checkcolumnconstraint_sql(self, expression: exp.CheckColumnConstraint) -> str:
        pass

    def indexcolumnconstraint_sql(self, expression: exp.IndexColumnConstraint) -> str:
        pass

    def nvl2_sql(self, expression: exp.Nvl2) -> str:
        pass

    def comprehension_sql(self, expression: exp.Comprehension) -> str:
        pass

    def columnprefix_sql(self, expression: exp.ColumnPrefix) -> str:
        pass

    def opclass_sql(self, expression: exp.Opclass) -> str:
        pass

    def _ml_sql(self, expression: exp.Func, name: str) -> str:
        pass

    def predict_sql(self, expression: exp.Predict) -> str:
        pass

    def generateembedding_sql(self, expression: exp.GenerateEmbedding) -> str:
        pass

    def generatetext_sql(self, expression: exp.GenerateText) -> str:
        pass

    def generatetable_sql(self, expression: exp.GenerateTable) -> str:
        pass

    def generatebool_sql(self, expression: exp.GenerateBool) -> str:
        pass

    def generateint_sql(self, expression: exp.GenerateInt) -> str:
        pass

    def generatedouble_sql(self, expression: exp.GenerateDouble) -> str:
        pass

    def mltranslate_sql(self, expression: exp.MLTranslate) -> str:
        pass

    def mlforecast_sql(self, expression: exp.MLForecast) -> str:
        pass

    def aiforecast_sql(self, expression: exp.AIForecast) -> str:
        pass

    def featuresattime_sql(self, expression: exp.FeaturesAtTime) -> str:
        pass

    def vectorsearch_sql(self, expression: exp.VectorSearch) -> str:
        pass

    def forin_sql(self, expression: exp.ForIn) -> str:
        pass

    def refresh_sql(self, expression: exp.Refresh) -> str:
        pass

    def toarray_sql(self, expression: exp.ToArray) -> str:
        pass

    def tsordstotime_sql(self, expression: exp.TsOrDsToTime) -> str:
        pass

    def tsordstotimestamp_sql(self, expression: exp.TsOrDsToTimestamp) -> str:
        pass

    def tsordstodatetime_sql(self, expression: exp.TsOrDsToDatetime) -> str:
        pass

    def tsordstodate_sql(self, expression: exp.TsOrDsToDate) -> str:
        pass

    def unixdate_sql(self, expression: exp.UnixDate) -> str:
        pass

    def lastday_sql(self, expression: exp.LastDay) -> str:
        pass

    def dateadd_sql(self, expression: exp.DateAdd) -> str:
        pass

    def arrayany_sql(self, expression: exp.ArrayAny) -> str:
        pass

    def struct_sql(self, expression: exp.Struct) -> str:
        pass

    def partitionrange_sql(self, expression: exp.PartitionRange) -> str:
        pass

    def truncatetable_sql(self, expression: exp.TruncateTable) -> str:
        pass

    # This transpiles T-SQL's CONVERT function
    # https://learn.microsoft.com/en-us/sql/t-sql/functions/cast-and-convert-transact-sql?view=sql-server-ver16
    def convert_sql(self, expression: exp.Convert) -> str:
        pass

    def _jsonpathkey_sql(self, expression: exp.JSONPathKey) -> str:
        this = expression.this
        if isinstance(this, exp.JSONPathWildcard):
            this = self.json_path_part(this)
            return f".{this}" if this else ""

        if self.SAFE_JSON_PATH_KEY_RE.match(this):
            return f".{this}"

        this = self.json_path_part(this)
        return (
            f"[{this}]"
            if self._quote_json_path_key_using_brackets and self.JSON_PATH_BRACKETED_KEY_SUPPORTED
            else f".{this}"
        )

    def _jsonpathsubscript_sql(self, expression: exp.JSONPathSubscript) -> str:
        this = self.json_path_part(expression.this)
        return f"[{this}]" if this else ""

    def _simplify_unless_literal(self, expression: E) -> E:
        if not isinstance(expression, exp.Literal):
            import sqlglot.optimizer.simplify

            expression = sqlglot.optimizer.simplify.simplify(expression, dialect=self.dialect)

        return expression

    def _embed_ignore_nulls(self, expression: exp.IgnoreNulls | exp.RespectNulls, text: str) -> str:
        pass

    def _replace_line_breaks(self, string: str) -> str:
        """We don't want to extra indent line breaks so we temporarily replace them with sentinels."""
        if self.pretty:
            return string.replace("\n", self.SENTINEL_LINE_BREAK)
        return string

    def copyparameter_sql(self, expression: exp.CopyParameter) -> str:
        pass

    def credentials_sql(self, expression: exp.Credentials) -> str:
        pass

    def copy_sql(self, expression: exp.Copy) -> str:
        pass

    def semicolon_sql(self, expression: exp.Semicolon) -> str:
        pass

    def datadeletionproperty_sql(self, expression: exp.DataDeletionProperty) -> str:
        pass

    def maskingpolicycolumnconstraint_sql(
        self, expression: exp.MaskingPolicyColumnConstraint
    ) -> str:
        pass

    def gapfill_sql(self, expression: exp.GapFill) -> str:
        pass

    def scope_resolution(self, rhs: str, scope_name: str) -> str:
        pass

    def scoperesolution_sql(self, expression: exp.ScopeResolution) -> str:
        pass

    def parsejson_sql(self, expression: exp.ParseJSON) -> str:
        pass

    def rand_sql(self, expression: exp.Rand) -> str:
        pass

    def changes_sql(self, expression: exp.Changes) -> str:
        pass

    def pad_sql(self, expression: exp.Pad) -> str:
        pass

    def summarize_sql(self, expression: exp.Summarize) -> str:
        pass

    def explodinggenerateseries_sql(self, expression: exp.ExplodingGenerateSeries) -> str:
        pass

    def converttimezone_sql(self, expression: exp.ConvertTimezone) -> str:
        pass

    def json_sql(self, expression: exp.JSON) -> str:
        pass

    def jsonvalue_sql(self, expression: exp.JSONValue) -> str:
        pass

    def skipjsoncolumn_sql(self, expression: exp.SkipJSONColumn) -> str:
        pass

    def conditionalinsert_sql(self, expression: exp.ConditionalInsert) -> str:
        pass

    def multitableinserts_sql(self, expression: exp.MultitableInserts) -> str:
        pass

    def oncondition_sql(self, expression: exp.OnCondition) -> str:
        # Static options like "NULL ON ERROR" are stored as strings, in contrast to "DEFAULT <expr> ON ERROR"
        pass

    def jsonextractquote_sql(self, expression: exp.JSONExtractQuote) -> str:
        pass

    def jsonexists_sql(self, expression: exp.JSONExists) -> str:
        pass

    def _add_arrayagg_null_filter(
        self,
        array_agg_sql: str,
        array_agg_expr: exp.ArrayAgg,
        column_expr: exp.Expr,
    ) -> str:
        """
        Add NULL filter to ARRAY_AGG if dialect requires it.

        Args:
            array_agg_sql: The generated ARRAY_AGG SQL string
            array_agg_expr: The ArrayAgg expression node
            column_expr: The column/expression to filter (before ORDER BY wrapping)

        Returns:
            SQL string with FILTER clause added if needed
        """
        pass

    def arrayagg_sql(self, expression: exp.ArrayAgg) -> str:
        pass

    def slice_sql(self, expression: exp.Slice) -> str:
        pass

    def apply_sql(self, expression: exp.Apply) -> str:
        pass

    def _grant_or_revoke_sql(
        self,
        expression: exp.Grant | exp.Revoke,
        keyword: str,
        preposition: str,
        grant_option_prefix: str = "",
        grant_option_suffix: str = "",
    ) -> str:
        pass

    def grant_sql(self, expression: exp.Grant) -> str:
        pass

    def revoke_sql(self, expression: exp.Revoke) -> str:
        pass

    def grantprivilege_sql(self, expression: exp.GrantPrivilege) -> str:
        pass

    def grantprincipal_sql(self, expression: exp.GrantPrincipal) -> str:
        pass

    def columns_sql(self, expression: exp.Columns) -> str:
        pass

    def overlay_sql(self, expression: exp.Overlay) -> str:
        pass

    @unsupported_args("format")
    def todouble_sql(self, expression: exp.ToDouble) -> str:
        pass

    def string_sql(self, expression: exp.String) -> str:
        pass

    def median_sql(self, expression: exp.Median) -> str:
        pass

    def overflowtruncatebehavior_sql(self, expression: exp.OverflowTruncateBehavior) -> str:
        pass

    def unixseconds_sql(self, expression: exp.UnixSeconds) -> str:
        pass

    def arraysize_sql(self, expression: exp.ArraySize) -> str:
        pass

    def attach_sql(self, expression: exp.Attach) -> str:
        pass

    def detach_sql(self, expression: exp.Detach) -> str:
        pass

    def attachoption_sql(self, expression: exp.AttachOption) -> str:
        pass

    def watermarkcolumnconstraint_sql(self, expression: exp.WatermarkColumnConstraint) -> str:
        pass

    def encodeproperty_sql(self, expression: exp.EncodeProperty) -> str:
        pass

    def includeproperty_sql(self, expression: exp.IncludeProperty) -> str:
        pass

    def xmlelement_sql(self, expression: exp.XMLElement) -> str:
        pass

    def xmlkeyvalueoption_sql(self, expression: exp.XMLKeyValueOption) -> str:
        pass

    def partitionbyrangeproperty_sql(self, expression: exp.PartitionByRangeProperty) -> str:
        pass

    def partitionbyrangepropertydynamic_sql(
        self, expression: exp.PartitionByRangePropertyDynamic
    ) -> str:
        pass

    def unpivotcolumns_sql(self, expression: exp.UnpivotColumns) -> str:
        pass

    def analyzesample_sql(self, expression: exp.AnalyzeSample) -> str:
        pass

    def analyzestatistics_sql(self, expression: exp.AnalyzeStatistics) -> str:
        pass

    def analyzehistogram_sql(self, expression: exp.AnalyzeHistogram) -> str:
        pass

    def analyzedelete_sql(self, expression: exp.AnalyzeDelete) -> str:
        pass

    def analyzelistchainedrows_sql(self, expression: exp.AnalyzeListChainedRows) -> str:
        pass

    def analyzevalidate_sql(self, expression: exp.AnalyzeValidate) -> str:
        pass

    def analyze_sql(self, expression: exp.Analyze) -> str:
        pass

    def xmltable_sql(self, expression: exp.XMLTable) -> str:
        pass

    def xmlnamespace_sql(self, expression: exp.XMLNamespace) -> str:
        pass

    def export_sql(self, expression: exp.Export) -> str:
        pass

    def declare_sql(self, expression: exp.Declare) -> str:
        pass

    def declareitem_sql(self, expression: exp.DeclareItem) -> str:
        pass

    def recursivewithsearch_sql(self, expression: exp.RecursiveWithSearch) -> str:
        pass

    def parameterizedagg_sql(self, expression: exp.ParameterizedAgg) -> str:
        pass

    def anonymousaggfunc_sql(self, expression: exp.AnonymousAggFunc) -> str:
        pass

    def combinedaggfunc_sql(self, expression: exp.CombinedAggFunc) -> str:
        pass

    def combinedparameterizedagg_sql(self, expression: exp.CombinedParameterizedAgg) -> str:
        pass

    def show_sql(self, expression: exp.Show) -> str:
        self.unsupported("Unsupported SHOW statement")
        return ""

    def install_sql(self, expression: exp.Install) -> str:
        pass

    def get_put_sql(self, expression: exp.Put | exp.Get) -> str:
        # Snowflake GET/PUT statements:
        #   PUT <file> <internalStage> <properties>
        #   GET <internalStage> <file> <properties>
        props = expression.args.get("properties")
        props_sql = self.properties(props, prefix=" ", sep=" ", wrapped=False) if props else ""
        this = self.sql(expression, "this")
        target = self.sql(expression, "target")

        if isinstance(expression, exp.Put):
            return f"PUT {this} {target}{props_sql}"
        else:
            return f"GET {target} {this}{props_sql}"

    def translatecharacters_sql(self, expression: exp.TranslateCharacters) -> str:
        pass

    def decodecase_sql(self, expression: exp.DecodeCase) -> str:
        pass

    def semanticview_sql(self, expression: exp.SemanticView) -> str:
        pass

    def getextract_sql(self, expression: exp.GetExtract) -> str:
        pass

    def datefromunixdate_sql(self, expression: exp.DateFromUnixDate) -> str:
        pass

    def space_sql(self: Generator, expression: exp.Space) -> str:
        pass

    def buildproperty_sql(self, expression: exp.BuildProperty) -> str:
        pass

    def refreshtriggerproperty_sql(self, expression: exp.RefreshTriggerProperty) -> str:
        pass

    def modelattribute_sql(self, expression: exp.ModelAttribute) -> str:
        pass

    def directorystage_sql(self, expression: exp.DirectoryStage) -> str:
        pass

    def uuid_sql(self, expression: exp.Uuid) -> str:
        pass

    def initcap_sql(self, expression: exp.Initcap) -> str:
        pass

    def localtime_sql(self, expression: exp.Localtime) -> str:
        pass

    def localtimestamp_sql(self, expression: exp.Localtimestamp) -> str:
        pass

    def weekstart_sql(self, expression: exp.WeekStart) -> str:
        pass

    def chr_sql(self, expression: exp.Chr, name: str = "CHR") -> str:
        this = self.expressions(expression)
        charset = self.sql(expression, "charset")
        using = f" USING {charset}" if charset else ""
        return self.func(name, this + using)

    def block_sql(self, expression: exp.Block) -> str:
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

    def altermodifysqlsecurity_sql(self, expression: exp.AlterModifySqlSecurity) -> str:
        pass

    def usingproperty_sql(self, expression: exp.UsingProperty) -> str:
        pass
