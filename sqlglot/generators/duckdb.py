from __future__ import annotations

from decimal import Decimal
from itertools import groupby
import re
import typing as t

from sqlglot import exp, generator, transforms

from sqlglot.dialects.dialect import (
    DATETIME_DELTA,
    JSON_EXTRACT_TYPE,
    approx_count_distinct_sql,
    array_append_sql,
    array_compact_sql,
    array_concat_sql,
    arrow_json_extract_sql,
    count_if_to_sum,
    date_delta_to_binary_interval_op,
    datestrtodate_sql,
    encode_decode_sql,
    explode_to_unnest_sql,
    generate_series_sql,
    getbit_sql,
    groupconcat_sql,
    inline_array_unless_query,
    months_between_sql,
    no_datetime_sql,
    no_comment_column_constraint_sql,
    no_make_interval_sql,
    no_time_sql,
    no_timestamp_sql,
    rename_func,
    remove_from_array_using_filter,
    strposition_sql,
    str_to_time_sql,
    timestrtotime_sql,
    unit_to_str,
)
from sqlglot.generator import unsupported_args
from sqlglot.helper import is_date_unit, seq_get
from builtins import type as Type

# Regex to detect time zones in timestamps of the form [+|-]TT[:tt]
# The pattern matches timezone offsets that appear after the time portion
TIMEZONE_PATTERN = re.compile(r":\d{2}.*?[+\-]\d{2}(?::\d{2})?")

# Characters that must be escaped when building regex expressions in INITCAP
REGEX_ESCAPE_REPLACEMENTS = {
    "\\": "\\\\",
    "-": r"\-",
    "^": r"\^",
    "[": r"\[",
    "]": r"\]",
}

# Used to in RANDSTR transpilation
RANDSTR_CHAR_POOL = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
RANDSTR_SEED = 123456

# Whitespace control characters that DuckDB must process with `CHR({val})` calls
WS_CONTROL_CHARS_TO_DUCK = {
    "\u000b": 11,
    "\u001c": 28,
    "\u001d": 29,
    "\u001e": 30,
    "\u001f": 31,
}

# Days of week to ISO 8601 day-of-week numbers
# ISO 8601 standard: Monday=1, Tuesday=2, Wednesday=3, Thursday=4, Friday=5, Saturday=6, Sunday=7
WEEK_START_DAY_TO_DOW = {
    "MONDAY": 1,
    "TUESDAY": 2,
    "WEDNESDAY": 3,
    "THURSDAY": 4,
    "FRIDAY": 5,
    "SATURDAY": 6,
    "SUNDAY": 7,
}

MAX_BIT_POSITION = exp.Literal.number(32768)

# cs/as/ps are Snowflake defaults; DuckDB already behaves the same way, so they are safe to drop.
# Note: "as" is also a reserved keyword in DuckDB, making it impossible to pass through.
_SNOWFLAKE_COLLATION_DEFAULTS = frozenset({"cs", "as", "ps"})
_SNOWFLAKE_COLLATION_UNSUPPORTED = frozenset(
    {"ci", "ai", "upper", "lower", "utf8", "bin", "pi", "fl", "fu", "trim", "ltrim", "rtrim"}
)

# Window functions that support IGNORE/RESPECT NULLS in DuckDB
_IGNORE_RESPECT_NULLS_WINDOW_FUNCTIONS = (
    exp.FirstValue,
    exp.Lag,
    exp.LastValue,
    exp.Lead,
    exp.NthValue,
)

# SEQ function constants
_SEQ_BASE: exp.Expr = exp.maybe_parse("(ROW_NUMBER() OVER (ORDER BY 1) - 1)")
_SEQ_RESTRICTED = (exp.Where, exp.Having, exp.AggFunc, exp.Order, exp.Select)
# Maps SEQ expression types to their byte width (suffix indicates bytes: SEQ1=1, SEQ2=2, etc.)
_SEQ_BYTE_WIDTH = {exp.Seq1: 1, exp.Seq2: 2, exp.Seq4: 4, exp.Seq8: 8}

# Template for generating signed and unsigned SEQ values within a specified range
_SEQ_UNSIGNED: exp.Expr = exp.maybe_parse(":base % :max_val")
_SEQ_SIGNED: exp.Expr = exp.maybe_parse(
    "(CASE WHEN :base % :max_val >= :half "
    "THEN :base % :max_val - :max_val "
    "ELSE :base % :max_val END)"
)


def _apply_base64_alphabet_replacements(
    result: exp.Expr,
    alphabet: exp.Expr | None,
    reverse: bool = False,
) -> exp.Expr:
    """
    Apply base64 alphabet character replacements.

    Base64 alphabet can be 1-3 chars: 1st = index 62 ('+'), 2nd = index 63 ('/'), 3rd = padding ('=').
    zip truncates to the shorter string, so 1-char alphabet only replaces '+', 2-char replaces '+/', etc.

    Args:
        result: The expression to apply replacements to
        alphabet: Custom alphabet literal (expected chars for +/=)
        reverse: If False, replace default with custom (encode)
                 If True, replace custom with default (decode)
    """
    if isinstance(alphabet, exp.Literal) and alphabet.is_string:
        for default_char, new_char in zip("+/=", alphabet.this):
            if new_char != default_char:
                find, replace = (new_char, default_char) if reverse else (default_char, new_char)
                result = exp.Replace(
                    this=result,
                    expression=exp.Literal.string(find),
                    replacement=exp.Literal.string(replace),
                )
    return result


def _base64_decode_sql(self: DuckDBGenerator, expression: exp.Expr, to_string: bool) -> str:
    """
    Transpile Snowflake BASE64_DECODE_STRING/BINARY to DuckDB.

    DuckDB uses FROM_BASE64() which returns BLOB. For string output, wrap with DECODE().
    Custom alphabets require REPLACE() calls to convert to standard base64.
    """
    input_expr = expression.this
    alphabet = expression.args.get("alphabet")

    # Handle custom alphabet by replacing non-standard chars with standard ones
    input_expr = _apply_base64_alphabet_replacements(input_expr, alphabet, reverse=True)

    # FROM_BASE64 returns BLOB
    input_expr = exp.FromBase64(this=input_expr)

    if to_string:
        input_expr = exp.Decode(this=input_expr)

    return self.sql(input_expr)


def _last_day_sql(self: DuckDBGenerator, expression: exp.LastDay) -> str:
    """
    DuckDB's LAST_DAY only supports finding the last day of a month.
    For other date parts (year, quarter, week), we need to implement equivalent logic.
    """
    pass


def _is_nanosecond_unit(unit: exp.Expr | None) -> bool:
    return isinstance(unit, (exp.Var, exp.Literal)) and unit.name.upper() == "NANOSECOND"


def _handle_nanosecond_diff(
    self: DuckDBGenerator,
    end_time: exp.Expr,
    start_time: exp.Expr,
) -> str:
    """Generate NANOSECOND diff using EPOCH_NS since DATE_DIFF doesn't support it."""
    pass


def _to_boolean_sql(self: DuckDBGenerator, expression: exp.ToBoolean) -> str:
    """
    Transpile TO_BOOLEAN and TRY_TO_BOOLEAN functions from Snowflake to DuckDB equivalent.

    DuckDB's CAST to BOOLEAN supports most of Snowflake's TO_BOOLEAN strings except 'on'/'off'.
    We need to handle the 'on'/'off' cases explicitly.

    For TO_BOOLEAN (safe=False): NaN and INF values cause errors. We use DuckDB's native ERROR()
    function to replicate this behavior with a clear error message.

    For TRY_TO_BOOLEAN (safe=True): Use DuckDB's TRY_CAST for conversion, which returns NULL
    for invalid inputs instead of throwing errors.
    """
    pass


# BigQuery -> DuckDB conversion for the DATE function
def _date_sql(self: DuckDBGenerator, expression: exp.Date) -> str:
    pass


# BigQuery -> DuckDB conversion for the TIME_DIFF function
def _timediff_sql(self: DuckDBGenerator, expression: exp.TimeDiff) -> str:
    pass


def _date_delta_to_binary_interval_op(
    cast: bool = True,
) -> t.Callable[[DuckDBGenerator, DATETIME_DELTA], str]:
    """
    DuckDB override to handle:
    1. NANOSECOND operations (DuckDB doesn't support INTERVAL ... NANOSECOND)
    2. Float/decimal interval values (DuckDB INTERVAL requires integers)
    """
    base_impl = date_delta_to_binary_interval_op(cast=cast)

    def _duckdb_date_delta_sql(self: DuckDBGenerator, expression: DATETIME_DELTA) -> str:
        pass

    return _duckdb_date_delta_sql


def _array_insert_sql(self: DuckDBGenerator, expression: exp.ArrayInsert) -> str:
    """
    Transpile ARRAY_INSERT to DuckDB using LIST_CONCAT and slicing.

    Handles:
    - 0-based and 1-based indexing (normalizes to 0-based for calculations)
    - Negative position conversion (requires array length)
    - NULL propagation (source dialects return NULL, DuckDB creates single-element array)
    - Assumes position is within bounds per user constraint

    Note: All dialects that support ARRAY_INSERT (Snowflake, Spark, Databricks) have
    ARRAY_FUNCS_PROPAGATES_NULLS=True, so we always assume source propagates NULLs.

    Args:
        expression: The ArrayInsert expression to transpile.

    Returns:
        SQL string implementing ARRAY_INSERT behavior.
    """
    pass


def _array_remove_at_sql(self: DuckDBGenerator, expression: exp.ArrayRemoveAt) -> str:
    """
    Transpile ARRAY_REMOVE_AT to DuckDB using LIST_CONCAT and slicing.

    Handles:
    - Positive positions (0-based indexing)
    - Negative positions (from end of array)
    - NULL propagation (Snowflake returns NULL for NULL array, DuckDB doesn't auto-propagate)
    - Only supports literal integer positions (non-literals remain untranspiled)

    Transpilation patterns:
    - pos=0 (first): arr[2:]
    - pos>0 (middle): LIST_CONCAT(arr[1:p], arr[p+2:])
    - pos=-1 (last): arr[1:LEN(arr)-1]
    - pos<-1: LIST_CONCAT(arr[1:LEN(arr)+p], arr[LEN(arr)+p+2:])

    All wrapped in: CASE WHEN arr IS NULL THEN NULL ELSE ... END

    Args:
        expression: The ArrayRemoveAt expression to transpile.

    Returns:
        SQL string implementing ARRAY_REMOVE_AT behavior.
    """
    pass


@unsupported_args(("expression", "DuckDB's ARRAY_SORT does not support a comparator."))
def _array_sort_sql(self: DuckDBGenerator, expression: exp.ArraySort) -> str:
    pass


def _array_contains_sql(self: DuckDBGenerator, expression: exp.ArrayContains) -> str:
    pass


def _array_overlaps_sql(self: DuckDBGenerator, expression: exp.ArrayOverlaps) -> str:
    """
    Translates Snowflake's NULL-safe ARRAYS_OVERLAP to DuckDB.

    DuckDB's native && operator is not NULL-safe: [1,NULL,3] && [NULL,4,5] returns FALSE.
    Snowflake returns TRUE when both arrays contain NULL (NULLs are treated as known values).

    Generated SQL: (arr1 && arr2) OR (ARRAY_LENGTH(arr1) <> LIST_COUNT(arr1) AND ARRAY_LENGTH(arr2) <> LIST_COUNT(arr2))

    ARRAY_LENGTH counts all elements (including NULLs); LIST_COUNT counts only non-NULLs.
    When they differ, the array contains at least one NULL, matching Snowflake's NULL-safe semantics.
    """
    pass


def _struct_sql(self: DuckDBGenerator, expression: exp.Struct) -> str:
    pass


def _datatype_sql(self: DuckDBGenerator, expression: exp.DataType) -> str:
    pass


def _json_format_sql(self: DuckDBGenerator, expression: exp.JSONFormat) -> str:
    pass


def _build_seq_expression(base: exp.Expr, byte_width: int, signed: bool) -> exp.Expr:
    """Build a SEQ expression with the given base, byte width, and signedness."""
    bits = byte_width * 8
    max_val = exp.Literal.number(2**bits)

    if signed:
        half = exp.Literal.number(2 ** (bits - 1))
        return exp.replace_placeholders(_SEQ_SIGNED.copy(), base=base, max_val=max_val, half=half)
    return exp.replace_placeholders(_SEQ_UNSIGNED.copy(), base=base, max_val=max_val)


def _seq_to_range_in_generator(expression: exp.Expr) -> exp.Expr:
    """
    Transform SEQ functions to `range` column references when inside a GENERATOR context.

    When GENERATOR(ROWCOUNT => N) becomes RANGE(N) in DuckDB, it produces a column
    named `range` with values 0, 1, ..., N-1. SEQ functions produce the same sequence,
    so we replace them with `range % max_val` to avoid nested window function issues.
    """
    pass


def _seq_sql(self: DuckDBGenerator, expression: exp.Func, byte_width: int) -> str:
    """
    Transpile Snowflake SEQ1/SEQ2/SEQ4/SEQ8 to DuckDB.

    Generates monotonically increasing integers starting from 0.
    The signed parameter (0 or 1) affects wrap-around behavior:
    - Unsigned (0): wraps at 2^(bits) - 1
    - Signed (1): wraps at 2^(bits-1) - 1, then goes negative
    """
    # Warn if SEQ is in a restricted context (Select stops search at current scope)
    ancestor = expression.find_ancestor(*_SEQ_RESTRICTED)
    if ancestor and (
        (not isinstance(ancestor, (exp.Order, exp.Select)))
        or (isinstance(ancestor, exp.Order) and isinstance(ancestor.parent, exp.Window))
    ):
        self.unsupported("SEQ in restricted context is not supported - use CTE or subquery")

    result = _build_seq_expression(_SEQ_BASE.copy(), byte_width, signed=expression.name == "1")
    return self.sql(result)


def _unix_to_time_sql(self: DuckDBGenerator, expression: exp.UnixToTime) -> str:
    scale = expression.args.get("scale")
    timestamp = expression.this
    target_type = expression.args.get("target_type")

    # Check if we need NTZ (naive timestamp in UTC)
    is_ntz = target_type and target_type.this in (
        exp.DType.TIMESTAMP,
        exp.DType.TIMESTAMPNTZ,
    )

    if scale == exp.UnixToTime.MILLIS:
        # EPOCH_MS already returns TIMESTAMP (naive, UTC)
        return self.func("EPOCH_MS", timestamp)
    if scale == exp.UnixToTime.MICROS:
        # MAKE_TIMESTAMP already returns TIMESTAMP (naive, UTC)
        return self.func("MAKE_TIMESTAMP", timestamp)

    # Other scales: divide and use TO_TIMESTAMP
    if scale not in (None, exp.UnixToTime.SECONDS):
        timestamp = exp.Div(this=timestamp, expression=exp.func("POW", 10, scale))

    to_timestamp: exp.Expr = exp.Anonymous(this="TO_TIMESTAMP", expressions=[timestamp])

    if is_ntz:
        to_timestamp = exp.AtTimeZone(this=to_timestamp, zone=exp.Literal.string("UTC"))

    return self.sql(to_timestamp)


WRAPPED_JSON_EXTRACT_EXPRESSIONS = (exp.Binary, exp.Bracket, exp.In, exp.Not)


def _arrow_json_extract_sql(self: DuckDBGenerator, expression: JSON_EXTRACT_TYPE) -> str:
    pass


def _implicit_datetime_cast(
    arg: exp.Expr | None, type: exp.DType = exp.DType.DATE
) -> exp.Expr | None:
    if isinstance(arg, exp.Literal) and arg.is_string:
        ts = arg.name
        if type == exp.DType.DATE and ":" in ts:
            type = exp.DType.TIMESTAMPTZ if TIMEZONE_PATTERN.search(ts) else exp.DType.TIMESTAMP

        arg = exp.cast(arg, type)

    return arg


def _week_unit_to_dow(unit: exp.Expr | None) -> int | None:
    """
    Compute the Monday-based day shift to align DATE_DIFF('WEEK', ...) coming
    from other dialects, e.g BigQuery's WEEK(<day>) or ISOWEEK unit parts.

    Args:
        unit: The unit expression (Var for ISOWEEK or WeekStart)

    Returns:
        The ISO 8601 day number (Monday=1, Sunday=7 etc) or None if not a week unit or if day is dynamic (not a constant).

        Examples:
            "WEEK(SUNDAY)" -> 7
            "WEEK(MONDAY)" -> 1
            "ISOWEEK" -> 1
    """
    pass


def _build_week_trunc_expression(
    date_expr: exp.Expr,
    start_dow: int,
    preserve_start_day: bool = False,
) -> exp.Expr:
    """
    Build DATE_TRUNC expression for week boundaries with custom start day.

    DuckDB's DATE_TRUNC('WEEK', ...) always returns Monday. To align to a different
    start day, we shift the date before truncating.

    Args:
        date_expr: The date expression to truncate.
        start_dow: ISO 8601 day-of-week number (Monday=1, ..., Sunday=7).
        preserve_start_day: If True, reverse the shift after truncating so the result lands on the
            correct week start day. Needed for DATE_TRUNC (absolute result matters) but
            not for DATE_DIFF (only relative alignment matters).

    Shift formula: Sunday (7) gets +1, others get (1 - start_dow).
    """
    pass


def _date_diff_sql(self: DuckDBGenerator, expression: exp.DateDiff | exp.DatetimeDiff) -> str:
    pass


def _generate_datetime_array_sql(
    self: DuckDBGenerator, expression: exp.GenerateDateArray | exp.GenerateTimestampArray
) -> str:
    pass


def _json_extract_value_array_sql(
    self: DuckDBGenerator, expression: exp.JSONValueArray | exp.JSONExtractArray
) -> str:
    pass


def _cast_to_varchar(arg: exp.Expr | None) -> exp.Expr | None:
    if arg and arg.type and not arg.is_type(*exp.DataType.TEXT_TYPES, exp.DType.UNKNOWN):
        return exp.cast(arg, exp.DType.VARCHAR)
    return arg


def _cast_to_boolean(arg: exp.Expr | None) -> exp.Expr | None:
    if arg and not arg.is_type(exp.DType.BOOLEAN):
        return exp.cast(arg, exp.DType.BOOLEAN)
    return arg


def _is_binary(arg: exp.Expr) -> bool:
    return arg.is_type(
        exp.DType.BINARY,
        exp.DType.VARBINARY,
        exp.DType.BLOB,
    )


def _gen_with_cast_to_blob(self: DuckDBGenerator, expression: exp.Expr, result_sql: str) -> str:
    if _is_binary(expression):
        blob = exp.DataType.build("BLOB", dialect="duckdb")
        result_sql = self.sql(exp.Cast(this=result_sql, to=blob))
    return result_sql


def _cast_to_bit(arg: exp.Expr) -> exp.Expr:
    if not _is_binary(arg):
        return arg

    if isinstance(arg, exp.HexString):
        arg = exp.Unhex(this=exp.Literal.string(arg.this))

    return exp.cast(arg, exp.DType.BIT)


def _prepare_binary_bitwise_args(expression: exp.Binary) -> None:
    if _is_binary(expression.this):
        expression.set("this", _cast_to_bit(expression.this))
    if _is_binary(expression.expression):
        expression.set("expression", _cast_to_bit(expression.expression))


def _day_navigation_sql(self: DuckDBGenerator, expression: exp.NextDay | exp.PreviousDay) -> str:
    """
    Transpile Snowflake's NEXT_DAY / PREVIOUS_DAY to DuckDB using date arithmetic.

    Returns the DATE of the next/previous occurrence of the specified weekday.

    Formulas:
    - NEXT_DAY: (target_dow - current_dow + 6) % 7 + 1
    - PREVIOUS_DAY: (current_dow - target_dow + 6) % 7 + 1

    Supports both literal and non-literal day names:
    - Literal: Direct lookup (e.g., 'Monday' -> 1)
    - Non-literal: CASE statement for runtime evaluation

    Examples:
        NEXT_DAY('2024-01-01' (Monday), 'Monday')
          -> (1 - 1 + 6) % 7 + 1 = 6 % 7 + 1 = 7 days -> 2024-01-08

        PREVIOUS_DAY('2024-01-15' (Monday), 'Friday')
          -> (1 - 5 + 6) % 7 + 1 = 2 % 7 + 1 = 3 days -> 2024-01-12
    """
    pass


def _anyvalue_sql(self: DuckDBGenerator, expression: exp.AnyValue) -> str:
    # Transform ANY_VALUE(expr HAVING MAX/MIN having_expr) to ARG_MAX_NULL/ARG_MIN_NULL
    pass


def _bitwise_agg_sql(
    self: DuckDBGenerator,
    expression: exp.BitwiseOrAgg | exp.BitwiseAndAgg | exp.BitwiseXorAgg,
) -> str:
    """
    DuckDB's bitwise aggregate functions only accept integer types. For other types:
    - DECIMAL/STRING: Use CAST(arg AS INT) to convert directly, will round to nearest int
    - FLOAT/DOUBLE: Use ROUND(arg)::INT to round to nearest integer, required due to float precision loss
    """
    pass


def _literal_sql_with_ws_chr(self: DuckDBGenerator, literal: str) -> str:
    # DuckDB does not support \uXXXX escapes, so we must use CHR() instead of replacing them directly
    pass


def _escape_regex_metachars(
    self: DuckDBGenerator, delimiters: exp.Expr | None, delimiters_sql: str
) -> str:
    r"""
    Escapes regex metacharacters \ - ^ [ ] for use in character classes regex expressions.

    Literal strings are escaped at transpile time, expressions handled with REPLACE() calls.
    """
    pass


def _build_capitalization_sql(
    self: DuckDBGenerator,
    value_to_split: str,
    delimiters_sql: str,
) -> str:
    # empty string delimiter --> treat value as one word, no need to split
    pass


def _initcap_sql(self: DuckDBGenerator, expression: exp.Initcap) -> str:
    pass


def _boolxor_agg_sql(self: DuckDBGenerator, expression: exp.BoolxorAgg) -> str:
    """
    Snowflake's `BOOLXOR_AGG(col)` returns TRUE if exactly one input in `col` is TRUE, FALSE otherwise;
    Since DuckDB does not have a mapping function, we mimic the behavior by generating `COUNT_IF(col) = 1`.

    DuckDB's COUNT_IF strictly requires boolean inputs, so cast if not already boolean.
    """
    pass


def _bitshift_sql(
    self: DuckDBGenerator, expression: exp.BitwiseLeftShift | exp.BitwiseRightShift
) -> str:
    """
    Transform bitshift expressions for DuckDB by injecting BIT/INT128 casts.

    DuckDB's bitwise shift operators don't work with BLOB/BINARY types, so we cast
    them to BIT for the operation, then cast the result back to the original type.

    Note: Assumes type annotation has been applied with the source dialect.
    """
    pass


def _scale_rounding_sql(
    self: DuckDBGenerator,
    expression: exp.Expr,
    rounding_func: Type[exp.Expr],
) -> str | None:
    """
    Handle scale parameter transformation for rounding functions.

    DuckDB doesn't support the scale parameter for certain functions (e.g., FLOOR, CEIL),
    so we transform: FUNC(x, n) to ROUND(FUNC(x * 10^n) / 10^n, n)

    Args:
        self: The DuckDB generator instance
        expression: The expression to transform (must have 'this', 'decimals', and 'to' args)
        rounding_func: The rounding function class to use in the transformation

    Returns:
        The transformed SQL string if decimals parameter exists, None otherwise
    """
    pass


def _ceil_floor(self: DuckDBGenerator, expression: exp.Floor | exp.Ceil) -> str:
    pass


def _regr_val_sql(
    self: DuckDBGenerator,
    expression: exp.RegrValx | exp.RegrValy,
) -> str:
    """
    Transpile Snowflake's REGR_VALX/REGR_VALY to DuckDB equivalent.

    REGR_VALX(y, x) returns NULL if y is NULL; otherwise returns x.
    REGR_VALY(y, x) returns NULL if x is NULL; otherwise returns y.
    """
    pass


def _maybe_corr_null_to_false(
    expression: exp.Filter | exp.Window | exp.Corr,
) -> exp.Filter | exp.Window | exp.Corr | None:
    corr = expression
    while isinstance(corr, (exp.Window, exp.Filter)):
        corr = corr.this

    if not isinstance(corr, exp.Corr) or not corr.args.get("null_on_zero_variance"):
        return None

    corr.set("null_on_zero_variance", False)
    return expression


def _date_from_parts_sql(self, expression: exp.DateFromParts) -> str:
    """
    Snowflake's DATE_FROM_PARTS allows out-of-range values for the month and day input.
    E.g., larger values (month=13, day=100), zero-values (month=0, day=0), negative values (month=-13, day=-100).

    DuckDB's MAKE_DATE does not support out-of-range values, but DuckDB's INTERVAL type does.

    We convert to date arithmetic:
    DATE_FROM_PARTS(year, month, day)
    - MAKE_DATE(year, 1, 1) + INTERVAL (month-1) MONTH + INTERVAL (day-1) DAY
    """
    pass


def _round_arg(arg: exp.Expr, round_input: bool | None = None) -> exp.Expr:
    pass


def _boolnot_sql(self: DuckDBGenerator, expression: exp.Boolnot) -> str:
    pass


def _booland_sql(self: DuckDBGenerator, expression: exp.Booland) -> str:
    pass


def _boolor_sql(self: DuckDBGenerator, expression: exp.Boolor) -> str:
    pass


def _xor_sql(self: DuckDBGenerator, expression: exp.Xor) -> str:
    pass


def _explode_to_unnest_sql(self: DuckDBGenerator, expression: exp.Lateral) -> str:
    """Handle LATERAL VIEW EXPLODE/INLINE conversion to UNNEST for DuckDB."""
    pass


def _sha_sql(
    self: DuckDBGenerator,
    expression: exp.Expr,
    hash_func: str,
    is_binary: bool = False,
) -> str:
    arg = expression.this

    # For SHA2 variants, check digest length (DuckDB only supports SHA256)
    if hash_func == "SHA256":
        length = expression.text("length") or "256"
        if length != "256":
            self.unsupported("DuckDB only supports SHA256 hashing algorithm.")

    # Cast if type is incompatible with DuckDB
    if (
        arg.type
        and arg.type.this != exp.DType.UNKNOWN
        and not arg.is_type(*exp.DataType.TEXT_TYPES)
        and not _is_binary(arg)
    ):
        arg = exp.cast(arg, exp.DType.VARCHAR)

    result = self.func(hash_func, arg)
    return self.func("UNHEX", result) if is_binary else result


class DuckDBGenerator(generator.Generator):
    PARAMETER_TOKEN = "$"
    NAMED_PLACEHOLDER_TOKEN = "$"
    JOIN_HINTS = False
    TABLE_HINTS = False
    QUERY_HINTS = False
    LIMIT_FETCH = "LIMIT"
    STRUCT_DELIMITER = ("(", ")")
    RENAME_TABLE_WITH_DB = False
    NVL2_SUPPORTED = False
    SEMI_ANTI_JOIN_WITH_SIDE = False
    TABLESAMPLE_KEYWORDS = "USING SAMPLE"
    TABLESAMPLE_SEED_KEYWORD = "REPEATABLE"
    LAST_DAY_SUPPORTS_DATE_PART = False
    JSON_KEY_VALUE_PAIR_SEP = ","
    IGNORE_NULLS_IN_FUNC = True
    IGNORE_NULLS_BEFORE_ORDER = False
    JSON_PATH_BRACKETED_KEY_SUPPORTED = False
    SUPPORTS_CREATE_TABLE_LIKE = False
    MULTI_ARG_DISTINCT = False
    CAN_IMPLEMENT_ARRAY_ANY = True
    SUPPORTS_TO_NUMBER = False
    SELECT_KINDS: tuple[str, ...] = ()
    SUPPORTS_DECODE_CASE = False
    SUPPORTS_DROP_ALTER_ICEBERG_PROPERTY = False

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS
    SUPPORTS_WINDOW_EXCLUDE = True
    COPY_HAS_INTO_KEYWORD = False
    STAR_EXCEPT = "EXCLUDE"
    PAD_FILL_PATTERN_IS_REQUIRED = True
    ARRAY_SIZE_DIM_REQUIRED: bool | None = False
    NORMALIZE_EXTRACT_DATE_PARTS = True
    SUPPORTS_LIKE_QUANTIFIERS = False
    SET_ASSIGNMENT_REQUIRES_VARIABLE_KEYWORD = True

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        exp.AnyValue: _anyvalue_sql,
        exp.ApproxDistinct: approx_count_distinct_sql,
        exp.Boolnot: _boolnot_sql,
        exp.Booland: _booland_sql,
        exp.Boolor: _boolor_sql,
        exp.Array: transforms.preprocess(
            [transforms.inherit_struct_field_names],
            generator=inline_array_unless_query,
        ),
        exp.ArrayAppend: array_append_sql("LIST_APPEND"),
        exp.ArrayCompact: array_compact_sql,
        exp.ArrayConstructCompact: lambda self, e: self.sql(
            exp.ArrayCompact(this=exp.Array(expressions=e.expressions))
        ),
        exp.ArrayConcat: array_concat_sql("LIST_CONCAT"),
        exp.ArrayContains: _array_contains_sql,
        exp.ArrayOverlaps: _array_overlaps_sql,
        exp.ArrayFilter: rename_func("LIST_FILTER"),
        exp.ArrayInsert: _array_insert_sql,
        exp.ArrayPosition: lambda self, e: (
            self.sql(
                exp.Sub(
                    this=exp.ArrayPosition(this=e.this, expression=e.expression),
                    expression=exp.Literal.number(1),
                )
            )
            if e.args.get("zero_based")
            else self.func("ARRAY_POSITION", e.this, e.expression)
        ),
        exp.ArrayRemoveAt: _array_remove_at_sql,
        exp.ArrayRemove: remove_from_array_using_filter,
        exp.ArraySort: _array_sort_sql,
        exp.ArrayPrepend: array_append_sql("LIST_PREPEND", swap_params=True),
        exp.ArraySum: rename_func("LIST_SUM"),
        exp.ArrayMax: rename_func("LIST_MAX"),
        exp.ArrayMin: rename_func("LIST_MIN"),
        exp.Base64DecodeBinary: lambda self, e: _base64_decode_sql(self, e, to_string=False),
        exp.Base64DecodeString: lambda self, e: _base64_decode_sql(self, e, to_string=True),
        exp.BitwiseAnd: lambda self, e: self._bitwise_op(e, "&"),
        exp.BitwiseAndAgg: _bitwise_agg_sql,
        exp.BitwiseCount: rename_func("BIT_COUNT"),
        exp.BitwiseLeftShift: _bitshift_sql,
        exp.BitwiseOr: lambda self, e: self._bitwise_op(e, "|"),
        exp.BitwiseOrAgg: _bitwise_agg_sql,
        exp.BitwiseRightShift: _bitshift_sql,
        exp.BitwiseXorAgg: _bitwise_agg_sql,
        exp.CommentColumnConstraint: no_comment_column_constraint_sql,
        exp.Corr: lambda self, e: self._corr_sql(e),
        exp.CosineDistance: rename_func("LIST_COSINE_DISTANCE"),
        exp.CurrentTime: lambda *_: "CURRENT_TIME",
        exp.CurrentSchemas: lambda self, e: self.func(
            "current_schemas", e.this if e.this else exp.true()
        ),
        exp.CurrentTimestamp: lambda self, e: (
            self.sql(
                exp.AtTimeZone(this=exp.var("CURRENT_TIMESTAMP"), zone=exp.Literal.string("UTC"))
            )
            if e.args.get("sysdate")
            else "CURRENT_TIMESTAMP"
        ),
        exp.CurrentVersion: rename_func("version"),
        exp.Localtime: unsupported_args("this")(lambda *_: "LOCALTIME"),
        exp.DayOfMonth: rename_func("DAYOFMONTH"),
        exp.DayOfWeek: rename_func("DAYOFWEEK"),
        exp.DayOfWeekIso: rename_func("ISODOW"),
        exp.DayOfYear: rename_func("DAYOFYEAR"),
        exp.Dayname: lambda self, e: (
            self.func("STRFTIME", e.this, exp.Literal.string("%a"))
            if e.args.get("abbreviated")
            else self.func("DAYNAME", e.this)
        ),
        exp.Monthname: lambda self, e: (
            self.func("STRFTIME", e.this, exp.Literal.string("%b"))
            if e.args.get("abbreviated")
            else self.func("MONTHNAME", e.this)
        ),
        exp.DataType: _datatype_sql,
        exp.Date: _date_sql,
        exp.DateAdd: _date_delta_to_binary_interval_op(),
        exp.DateFromParts: _date_from_parts_sql,
        exp.DateSub: _date_delta_to_binary_interval_op(),
        exp.DateDiff: _date_diff_sql,
        exp.DateStrToDate: datestrtodate_sql,
        exp.Datetime: no_datetime_sql,
        exp.DatetimeDiff: _date_diff_sql,
        exp.DatetimeSub: _date_delta_to_binary_interval_op(),
        exp.DatetimeAdd: _date_delta_to_binary_interval_op(),
        exp.DateToDi: lambda self, e: (
            f"CAST(STRFTIME({self.sql(e, 'this')}, {self.dialect.DATEINT_FORMAT}) AS INT)"
        ),
        exp.Decode: lambda self, e: encode_decode_sql(self, e, "DECODE", replace=False),
        exp.DiToDate: lambda self, e: (
            f"CAST(STRPTIME(CAST({self.sql(e, 'this')} AS TEXT), {self.dialect.DATEINT_FORMAT}) AS DATE)"
        ),
        exp.Encode: lambda self, e: encode_decode_sql(self, e, "ENCODE", replace=False),
        exp.EqualNull: lambda self, e: self.sql(
            exp.NullSafeEQ(this=e.this, expression=e.expression)
        ),
        exp.EuclideanDistance: rename_func("LIST_DISTANCE"),
        exp.GenerateDateArray: _generate_datetime_array_sql,
        exp.GenerateSeries: generate_series_sql("GENERATE_SERIES", "RANGE"),
        exp.GenerateTimestampArray: _generate_datetime_array_sql,
        exp.Getbit: getbit_sql,
        exp.GroupConcat: lambda self, e: groupconcat_sql(self, e, within_group=False),
        exp.Explode: rename_func("UNNEST"),
        exp.IcebergProperty: lambda *_: "",
        exp.IntDiv: lambda self, e: self.binary(e, "//"),
        exp.IsInf: rename_func("ISINF"),
        exp.IsNan: rename_func("ISNAN"),
        exp.IsNullValue: lambda self, e: self.sql(
            exp.func("JSON_TYPE", e.this).eq(exp.Literal.string("NULL"))
        ),
        exp.IsArray: lambda self, e: self.sql(
            exp.func("JSON_TYPE", e.this).eq(exp.Literal.string("ARRAY"))
        ),
        exp.Ceil: _ceil_floor,
        exp.Floor: _ceil_floor,
        exp.JSONBExists: rename_func("JSON_EXISTS"),
        exp.JSONExtract: _arrow_json_extract_sql,
        exp.JSONExtractArray: _json_extract_value_array_sql,
        exp.JSONFormat: _json_format_sql,
        exp.JSONValueArray: _json_extract_value_array_sql,
        exp.Lateral: _explode_to_unnest_sql,
        exp.LogicalOr: lambda self, e: self.func("BOOL_OR", _cast_to_boolean(e.this)),
        exp.LogicalAnd: lambda self, e: self.func("BOOL_AND", _cast_to_boolean(e.this)),
        exp.Select: transforms.preprocess([_seq_to_range_in_generator]),
        exp.Seq1: lambda self, e: _seq_sql(self, e, 1),
        exp.Seq2: lambda self, e: _seq_sql(self, e, 2),
        exp.Seq4: lambda self, e: _seq_sql(self, e, 4),
        exp.Seq8: lambda self, e: _seq_sql(self, e, 8),
        exp.BoolxorAgg: _boolxor_agg_sql,
        exp.MakeInterval: lambda self, e: no_make_interval_sql(self, e, sep=" "),
        exp.Initcap: _initcap_sql,
        exp.MD5Digest: lambda self, e: self.func("UNHEX", self.func("MD5", e.this)),
        exp.SHA: lambda self, e: _sha_sql(self, e, "SHA1"),
        exp.SHA1Digest: lambda self, e: _sha_sql(self, e, "SHA1", is_binary=True),
        exp.SHA2: lambda self, e: _sha_sql(self, e, "SHA256"),
        exp.SHA2Digest: lambda self, e: _sha_sql(self, e, "SHA256", is_binary=True),
        exp.MonthsBetween: months_between_sql,
        exp.NextDay: _day_navigation_sql,
        exp.PercentileCont: rename_func("QUANTILE_CONT"),
        exp.PercentileDisc: rename_func("QUANTILE_DISC"),
        # DuckDB doesn't allow qualified columns inside of PIVOT expressions.
        # See: https://github.com/duckdb/duckdb/blob/671faf92411182f81dce42ac43de8bfb05d9909e/src/planner/binder/tableref/bind_pivot.cpp#L61-L62
        exp.Pivot: transforms.preprocess([transforms.unqualify_columns]),
        exp.PreviousDay: _day_navigation_sql,
        exp.RegexpILike: lambda self, e: self.func(
            "REGEXP_MATCHES", e.this, e.expression, exp.Literal.string("i")
        ),
        exp.RegexpSplit: rename_func("STR_SPLIT_REGEX"),
        exp.RegrValx: _regr_val_sql,
        exp.RegrValy: _regr_val_sql,
        exp.Return: lambda self, e: self.sql(e, "this"),
        exp.ReturnsProperty: lambda self, e: "TABLE" if isinstance(e.this, exp.Schema) else "",
        exp.StrToUnix: lambda self, e: self.func(
            "EPOCH", self.func("STRPTIME", e.this, self.format_time(e))
        ),
        exp.Struct: _struct_sql,
        exp.Transform: rename_func("LIST_TRANSFORM"),
        exp.TimeAdd: _date_delta_to_binary_interval_op(),
        exp.TimeSub: _date_delta_to_binary_interval_op(),
        exp.Time: no_time_sql,
        exp.TimeDiff: _timediff_sql,
        exp.Timestamp: no_timestamp_sql,
        exp.TimestampAdd: _date_delta_to_binary_interval_op(),
        exp.TimestampDiff: lambda self, e: self.func(
            "DATE_DIFF", exp.Literal.string(e.unit), e.expression, e.this
        ),
        exp.TimestampSub: _date_delta_to_binary_interval_op(),
        exp.TimeStrToDate: lambda self, e: self.sql(exp.cast(e.this, exp.DType.DATE)),
        exp.TimeStrToTime: timestrtotime_sql,
        exp.TimeStrToUnix: lambda self, e: self.func(
            "EPOCH", exp.cast(e.this, exp.DType.TIMESTAMP)
        ),
        exp.TimeToStr: lambda self, e: self.func("STRFTIME", e.this, self.format_time(e)),
        exp.ToBoolean: _to_boolean_sql,
        exp.ToVariant: lambda self, e: self.sql(
            exp.cast(e.this, exp.DataType.build("VARIANT", dialect="duckdb"))
        ),
        exp.TimeToUnix: rename_func("EPOCH"),
        exp.TsOrDiToDi: lambda self, e: (
            f"CAST(SUBSTR(REPLACE(CAST({self.sql(e, 'this')} AS TEXT), '-', ''), 1, 8) AS INT)"
        ),
        exp.TsOrDsAdd: _date_delta_to_binary_interval_op(),
        exp.TsOrDsDiff: lambda self, e: self.func(
            "DATE_DIFF",
            f"'{e.args.get('unit') or 'DAY'}'",
            exp.cast(e.expression, exp.DType.TIMESTAMP),
            exp.cast(e.this, exp.DType.TIMESTAMP),
        ),
        exp.UnixMicros: lambda self, e: self.func("EPOCH_US", _implicit_datetime_cast(e.this)),
        exp.UnixMillis: lambda self, e: self.func("EPOCH_MS", _implicit_datetime_cast(e.this)),
        exp.UnixSeconds: lambda self, e: self.sql(
            exp.cast(self.func("EPOCH", _implicit_datetime_cast(e.this)), exp.DType.BIGINT)
        ),
        exp.UnixToStr: lambda self, e: self.func(
            "STRFTIME", self.func("TO_TIMESTAMP", e.this), self.format_time(e)
        ),
        exp.DatetimeTrunc: lambda self, e: self.func(
            "DATE_TRUNC", unit_to_str(e), exp.cast(e.this, exp.DType.DATETIME)
        ),
        exp.UnixToTime: _unix_to_time_sql,
        exp.UnixToTimeStr: lambda self, e: f"CAST(TO_TIMESTAMP({self.sql(e, 'this')}) AS TEXT)",
        exp.VariancePop: rename_func("VAR_POP"),
        exp.WeekOfYear: rename_func("WEEKOFYEAR"),
        exp.YearOfWeek: lambda self, e: self.sql(
            exp.Extract(
                this=exp.Var(this="ISOYEAR"),
                expression=e.this,
            )
        ),
        exp.YearOfWeekIso: lambda self, e: self.sql(
            exp.Extract(
                this=exp.Var(this="ISOYEAR"),
                expression=e.this,
            )
        ),
        exp.Xor: _xor_sql,
        exp.JSONObjectAgg: rename_func("JSON_GROUP_OBJECT"),
        exp.JSONBObjectAgg: rename_func("JSON_GROUP_OBJECT"),
        exp.DateBin: rename_func("TIME_BUCKET"),
        exp.LastDay: _last_day_sql,
    }

    SUPPORTED_JSON_PATH_PARTS = {
        exp.JSONPathKey,
        exp.JSONPathRoot,
        exp.JSONPathSubscript,
        exp.JSONPathWildcard,
    }

    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        exp.DType.BINARY: "BLOB",
        exp.DType.BPCHAR: "TEXT",
        exp.DType.CHAR: "TEXT",
        exp.DType.DATETIME: "TIMESTAMP",
        exp.DType.DECFLOAT: "DECIMAL(38, 5)",
        exp.DType.FLOAT: "REAL",
        exp.DType.JSONB: "JSON",
        exp.DType.NCHAR: "TEXT",
        exp.DType.NVARCHAR: "TEXT",
        exp.DType.UINT: "UINTEGER",
        exp.DType.VARBINARY: "BLOB",
        exp.DType.ROWVERSION: "BLOB",
        exp.DType.VARCHAR: "TEXT",
        exp.DType.TIMESTAMPLTZ: "TIMESTAMPTZ",
        exp.DType.TIMESTAMPNTZ: "TIMESTAMP",
        exp.DType.TIMESTAMP_S: "TIMESTAMP_S",
        exp.DType.TIMESTAMP_MS: "TIMESTAMP_MS",
        exp.DType.TIMESTAMP_NS: "TIMESTAMP_NS",
        exp.DType.BIGDECIMAL: "DECIMAL(38, 5)",
    }

    # https://github.com/duckdb/duckdb/blob/ff7f24fd8e3128d94371827523dae85ebaf58713/third_party/libpg_query/grammar/keywords/reserved_keywords.list#L1-L77
    RESERVED_KEYWORDS = {
        "array",
        "analyse",
        "union",
        "all",
        "when",
        "in_p",
        "default",
        "create_p",
        "window",
        "asymmetric",
        "to",
        "else",
        "localtime",
        "from",
        "end_p",
        "select",
        "current_date",
        "foreign",
        "with",
        "grant",
        "session_user",
        "or",
        "except",
        "references",
        "fetch",
        "limit",
        "group_p",
        "leading",
        "into",
        "collate",
        "offset",
        "do",
        "then",
        "localtimestamp",
        "check_p",
        "lateral_p",
        "current_role",
        "where",
        "asc_p",
        "placing",
        "desc_p",
        "user",
        "unique",
        "initially",
        "column",
        "both",
        "some",
        "as",
        "any",
        "only",
        "deferrable",
        "null_p",
        "current_time",
        "true_p",
        "table",
        "case",
        "trailing",
        "variadic",
        "for",
        "on",
        "distinct",
        "false_p",
        "not",
        "constraint",
        "current_timestamp",
        "returning",
        "primary",
        "intersect",
        "having",
        "analyze",
        "current_user",
        "and",
        "cast",
        "symmetric",
        "using",
        "order",
        "current_catalog",
    }

    UNWRAPPED_INTERVAL_VALUES = (exp.Literal, exp.Paren)

    # DuckDB doesn't generally support CREATE TABLE .. properties
    # https://duckdb.org/docs/sql/statements/create_table.html
    # There are a few exceptions (e.g. temporary tables) which are supported or
    # can be transpiled to DuckDB, so we explicitly override them accordingly
    PROPERTIES_LOCATION = {
        **{
            prop: exp.Properties.Location.UNSUPPORTED
            for prop in generator.Generator.PROPERTIES_LOCATION
        },
        exp.LikeProperty: exp.Properties.Location.POST_SCHEMA,
        exp.TemporaryProperty: exp.Properties.Location.POST_CREATE,
        exp.ReturnsProperty: exp.Properties.Location.POST_ALIAS,
        exp.SequenceProperties: exp.Properties.Location.POST_EXPRESSION,
        exp.IcebergProperty: exp.Properties.Location.POST_CREATE,
    }

    IGNORE_RESPECT_NULLS_WINDOW_FUNCTIONS: t.ClassVar = _IGNORE_RESPECT_NULLS_WINDOW_FUNCTIONS

    # Template for ZIPF transpilation - placeholders get replaced with actual parameters
    ZIPF_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        WITH rand AS (SELECT :random_expr AS r),
        weights AS (
            SELECT i, 1.0 / POWER(i, :s) AS w
            FROM RANGE(1, :n + 1) AS t(i)
        ),
        cdf AS (
            SELECT i, SUM(w) OVER (ORDER BY i) / SUM(w) OVER () AS p
            FROM weights
        )
        SELECT MIN(i)
        FROM cdf
        WHERE p >= (SELECT r FROM rand)
        """
    )

    # Template for NORMAL transpilation using Box-Muller transform
    # mean + (stddev * sqrt(-2 * ln(u1)) * cos(2 * pi * u2))
    NORMAL_TEMPLATE: exp.Expr = exp.maybe_parse(
        ":mean + (:stddev * SQRT(-2 * LN(GREATEST(:u1, 1e-10))) * COS(2 * PI() * :u2))"
    )

    # Template for generating a seeded pseudo-random value in [0, 1) from a hash
    SEEDED_RANDOM_TEMPLATE: exp.Expr = exp.maybe_parse("(ABS(HASH(:seed)) % 1000000) / 1000000.0")

    # Template for generating signed and unsigned SEQ values within a specified range
    SEQ_UNSIGNED: exp.Expr = _SEQ_UNSIGNED
    SEQ_SIGNED: exp.Expr = _SEQ_SIGNED

    # Template for MAP_CAT transpilation - Snowflake semantics:
    # 1. Returns NULL if either input is NULL
    # 2. For duplicate keys, prefers non-NULL value (COALESCE(m2[k], m1[k]))
    # 3. Filters out entries with NULL values from the result
    MAPCAT_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        CASE
            WHEN :map1 IS NULL OR :map2 IS NULL THEN NULL
            ELSE MAP_FROM_ENTRIES(LIST_FILTER(LIST_TRANSFORM(
                LIST_DISTINCT(LIST_CONCAT(MAP_KEYS(:map1), MAP_KEYS(:map2))),
                __k -> STRUCT_PACK(key := __k, value := COALESCE(:map2[__k], :map1[__k]))
            ), __x -> __x.value IS NOT NULL))
        END
        """
    )

    # Mappings for EXTRACT/DATE_PART transpilation
    # Maps Snowflake specifiers unsupported in DuckDB to strftime format codes
    EXTRACT_STRFTIME_MAPPINGS: dict[str, tuple[str, str]] = {
        "WEEKISO": ("%V", "INTEGER"),
        "YEAROFWEEK": ("%G", "INTEGER"),
        "YEAROFWEEKISO": ("%G", "INTEGER"),
        "NANOSECOND": ("%n", "BIGINT"),
    }

    # Maps epoch-based specifiers to DuckDB epoch functions
    EXTRACT_EPOCH_MAPPINGS: dict[str, str] = {
        "EPOCH_SECOND": "EPOCH",
        "EPOCH_MILLISECOND": "EPOCH_MS",
        "EPOCH_MICROSECOND": "EPOCH_US",
        "EPOCH_NANOSECOND": "EPOCH_NS",
    }

    # Template for BITMAP_CONSTRUCT_AGG transpilation
    #
    # BACKGROUND:
    # Snowflake's BITMAP_CONSTRUCT_AGG aggregates integers into a compact binary bitmap.
    # Supports values in range 0-32767, this version returns NULL if any value is out of range
    # See: https://docs.snowflake.com/en/sql-reference/functions/bitmap_construct_agg
    # See: https://docs.snowflake.com/en/user-guide/querying-bitmaps-for-distinct-counts
    #
    # Snowflake uses two different formats based on the number of unique values:
    #
    # Format 1 - Small bitmap (< 5 unique values): Length of 10 bytes
    #   Bytes 0-1: Count of values as 2-byte big-endian integer (e.g., 3 values = 0x0003)
    #   Bytes 2-9: Up to 4 values, each as 2-byte little-endian integers, zero-padded to 8 bytes
    #   Example: Values [1, 2, 3] -> 0x0003 0100 0200 0300 0000 (hex)
    #                                count  v1   v2   v3   pad
    #
    # Format 2 - Large bitmap (>= 5 unique values): Length of 10 + (2 * count) bytes
    #   Bytes 0-9: Fixed header 0x08 followed by 9 zero bytes
    #   Bytes 10+: Each value as 2-byte little-endian integer (no padding)
    #   Example: Values [1,2,3,4,5] -> 0x08 00000000 00000000 00 0100 0200 0300 0400 0500
    #                                  hdr  ----9 zero bytes----  v1   v2   v3   v4   v5
    #
    # TEMPLATE STRUCTURE
    #
    # Phase 1 - Innermost subquery: Data preparation
    #   SELECT LIST_SORT(...) AS l
    #   - Aggregates all input values into a list, remove NULLs, duplicates and sorts
    #   Result: Clean, sorted list of unique non-null integers stored as 'l'
    #
    # Phase 2 - Middle subquery: Hex string construction
    #   LIST_TRANSFORM(...)
    #   - Converts each integer to 2-byte little-endian hex representation
    #   - & 255 extracts low byte, >> 8 extracts high byte
    #   - LIST_REDUCE: Concatenates all hex pairs into single string 'h'
    #   Result: Hex string of all values
    #
    # Phase 3 - Outer SELECT: Final bitmap assembly
    #   LENGTH(l) < 5:
    #   - Small format: 2-byte count (big-endian via %04X) + values + zero padding
    #   LENGTH(l) >= 5:
    #   - Large format: Fixed 10-byte header + values (no padding needed)
    #   Result: Complete binary bitmap as BLOB
    #
    BITMAP_CONSTRUCT_AGG_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        SELECT CASE
            WHEN l IS NULL OR LENGTH(l) = 0 THEN NULL
            WHEN LENGTH(l) != LENGTH(LIST_FILTER(l, __v -> __v BETWEEN 0 AND 32767)) THEN NULL
            WHEN LENGTH(l) < 5 THEN UNHEX(PRINTF('%04X', LENGTH(l)) || h || REPEAT('00', GREATEST(0, 4 - LENGTH(l)) * 2))
            ELSE UNHEX('08000000000000000000' || h)
        END
        FROM (
            SELECT l, COALESCE(LIST_REDUCE(
                LIST_TRANSFORM(l, __x -> PRINTF('%02X%02X', CAST(__x AS INT) & 255, (CAST(__x AS INT) >> 8) & 255)),
                (__a, __b) -> __a || __b, ''
            ), '') AS h
            FROM (SELECT LIST_SORT(LIST_DISTINCT(LIST(:arg) FILTER(NOT :arg IS NULL))) AS l)
        )
        """
    )

    # Template for RANDSTR transpilation - placeholders get replaced with actual parameters
    RANDSTR_TEMPLATE: exp.Expr = exp.maybe_parse(
        f"""
        SELECT LISTAGG(
            SUBSTRING(
                '{RANDSTR_CHAR_POOL}',
                1 + CAST(FLOOR(random_value * 62) AS INT),
                1
            ),
            ''
        )
        FROM (
            SELECT (ABS(HASH(i + :seed)) % 1000) / 1000.0 AS random_value
            FROM RANGE(:length) AS t(i)
        )
        """,
    )

    # Template for MINHASH transpilation
    # Computes k minimum hash values across aggregated data using DuckDB list functions
    # Returns JSON matching Snowflake format: {"state": [...], "type": "minhash", "version": 1}
    MINHASH_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        SELECT JSON_OBJECT('state', LIST(min_h ORDER BY seed), 'type', 'minhash', 'version', 1)
        FROM (
            SELECT seed, LIST_MIN(LIST_TRANSFORM(vals, __v -> HASH(CAST(__v AS VARCHAR) || CAST(seed AS VARCHAR)))) AS min_h
            FROM (SELECT LIST(:expr) AS vals), RANGE(0, :k) AS t(seed)
        )
        """,
    )

    # Template for MINHASH_COMBINE transpilation
    # Combines multiple minhash signatures by taking element-wise minimum
    MINHASH_COMBINE_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        SELECT JSON_OBJECT('state', LIST(min_h ORDER BY idx), 'type', 'minhash', 'version', 1)
        FROM (
            SELECT
                pos AS idx,
                MIN(val) AS min_h
            FROM
                UNNEST(LIST(:expr)) AS _(sig),
                UNNEST(CAST(sig -> 'state' AS UBIGINT[])) WITH ORDINALITY AS t(val, pos)
            GROUP BY pos
        )
        """,
    )

    # Template for APPROXIMATE_SIMILARITY transpilation
    # Computes multi-way Jaccard similarity: fraction of positions where ALL signatures agree
    APPROXIMATE_SIMILARITY_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        SELECT CAST(SUM(CASE WHEN num_distinct = 1 THEN 1 ELSE 0 END) AS DOUBLE) / COUNT(*)
        FROM (
            SELECT pos, COUNT(DISTINCT h) AS num_distinct
            FROM (
                SELECT h, pos
                FROM UNNEST(LIST(:expr)) AS _(sig),
                     UNNEST(CAST(sig -> 'state' AS UBIGINT[])) WITH ORDINALITY AS s(h, pos)
            )
            GROUP BY pos
        )
        """,
    )

    # Template for ARRAYS_ZIP transpilation
    # Snowflake pads to longest array; DuckDB LIST_ZIP truncates to shortest
    # Uses RANGE + indexing to match Snowflake behavior
    ARRAYS_ZIP_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        CASE WHEN :null_check THEN NULL
        WHEN :all_empty_check THEN [:empty_struct]
        ELSE LIST_TRANSFORM(RANGE(0, :max_len), __i -> :transform_struct)
        END
        """,
    )

    # Shared bag semantics outer frame for ARRAY_EXCEPT and ARRAY_INTERSECTION.
    # Each element is paired with its 1-based position via LIST_ZIP, then filtered
    # by a comparison operator (supplied via :cond) that determines the operation:
    #   EXCEPT (>):        keep the N-th occurrence only if N > count in arr2
    #                      e.g. [2,2,2] EXCEPT [2,2] -> [2]
    #   INTERSECTION (<=): keep the N-th occurrence only if N <= count in arr2
    #                      e.g. [2,2,2] INTERSECT [2,2] -> [2,2]
    # IS NOT DISTINCT FROM is used for NULL-safe element comparison.
    ARRAY_BAG_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        CASE
            WHEN :arr1 IS NULL OR :arr2 IS NULL THEN NULL
            ELSE LIST_TRANSFORM(
                LIST_FILTER(
                    LIST_ZIP(:arr1, GENERATE_SERIES(1, LEN(:arr1))),
                    pair -> :cond
                ),
                pair -> pair[0]
            )
        END
        """
    )

    ARRAY_EXCEPT_CONDITION: exp.Expr = exp.maybe_parse(
        "LEN(LIST_FILTER(:arr1[1:pair[1]], e -> e IS NOT DISTINCT FROM pair[0]))"
        " > LEN(LIST_FILTER(:arr2, e -> e IS NOT DISTINCT FROM pair[0]))"
    )

    ARRAY_INTERSECTION_CONDITION: exp.Expr = exp.maybe_parse(
        "LEN(LIST_FILTER(:arr1[1:pair[1]], e -> e IS NOT DISTINCT FROM pair[0]))"
        " <= LEN(LIST_FILTER(:arr2, e -> e IS NOT DISTINCT FROM pair[0]))"
    )

    # Set semantics for ARRAY_EXCEPT. Deduplicates arr1 via LIST_DISTINCT, then
    # filters out any element that appears at least once in arr2.
    #   e.g. [1,1,2,3] EXCEPT [1] -> [2,3]
    # IS NOT DISTINCT FROM is used for NULL-safe element comparison.
    ARRAY_EXCEPT_SET_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        CASE
            WHEN :arr1 IS NULL OR :arr2 IS NULL THEN NULL
            ELSE LIST_FILTER(
                LIST_DISTINCT(:arr1),
                e -> LEN(LIST_FILTER(:arr2, x -> x IS NOT DISTINCT FROM e)) = 0
            )
        END
        """
    )

    # Template for STRTOK function transpilation
    #
    # DuckDB itself doesn't have a strtok function. This handles the transpilation from Snowflake to DuckDB.
    # We may need to adjust this if we want to support transpilation from other dialects
    #
    # CASE
    #     -- Snowflake: empty delimiter + empty input string -> NULL
    #     WHEN delimiter = '' AND input_str = '' THEN NULL
    #
    #     -- Snowflake: empty delimiter + non-empty input string -> treats whole input as 1 token -> return input string if index is 1
    #     WHEN delimiter = '' AND index = 1 THEN input_str
    #
    #     -- Snowflake: empty delimiter + non-empty input string -> treats whole input as 1 token -> return NULL if index is not 1
    #     WHEN delimiter = '' THEN NULL
    #
    #     -- Snowflake: negative indices return NULL
    #     WHEN index < 0 THEN NULL
    #
    #     -- Snowflake: return NULL if any argument is NULL
    #     WHEN input_str IS NULL OR delimiter IS NULL OR index IS NULL THEN NULL
    #
    #
    #     ELSE LIST_FILTER(
    #         REGEXP_SPLIT_TO_ARRAY(
    #             input_str,
    #             CASE
    #                 -- if delimiter is '', we don't want to surround it with '[' and ']' as '[]' is invalid for DuckDB
    #                 WHEN delimiter = '' THEN ''
    #
    #                 -- handle problematic regex characters in delimiter with REGEXP_REPLACE
    #                 -- turn delimiter into a regex char set, otherwise DuckDB will match in order, which we don't want
    #                 ELSE '[' || REGEXP_REPLACE(delimiter, problematic_char_set, '\\\1', 'g') || ']'
    #             END
    #         ),
    #
    #         -- Snowflake: don't return empty strings
    #         x -> NOT x = ''
    #     )[index]
    # END
    STRTOK_TEMPLATE: exp.Expr = exp.maybe_parse(
        """
        CASE
            WHEN :delimiter = '' AND :string = '' THEN NULL
            WHEN :delimiter = '' AND :part_index = 1 THEN :string
            WHEN :delimiter = '' THEN NULL
            WHEN :part_index < 0 THEN NULL
            WHEN :string IS NULL OR :delimiter IS NULL OR :part_index IS NULL THEN NULL
            ELSE :base_func
        END
        """
    )

    def _array_bag_sql(self, condition: exp.Expr, arr1: exp.Expr, arr2: exp.Expr) -> str:
        pass

    def timeslice_sql(self, expression: exp.TimeSlice) -> str:
        """
        Transform Snowflake's TIME_SLICE to DuckDB's time_bucket.

        Snowflake: TIME_SLICE(date_expr, slice_length, 'UNIT' [, 'START'|'END'])
        DuckDB:    time_bucket(INTERVAL 'slice_length' UNIT, date_expr)

        For 'END' kind, add the interval to get the end of the slice.
        For DATE type with 'END', cast result back to DATE to preserve type.
        """
        pass

    def bitmapbucketnumber_sql(self, expression: exp.BitmapBucketNumber) -> str:
        """
        Transpile BITMAP_BUCKET_NUMBER function from Snowflake to DuckDB equivalent.

        Snowflake's BITMAP_BUCKET_NUMBER returns a 1-based bucket identifier where:
        - Each bucket covers 32,768 values
        - Bucket numbering starts at 1
        - Formula: ((value - 1) // 32768) + 1 for positive values

        For non-positive values (0 and negative), we use value // 32768 to avoid
        producing bucket 0 or positive bucket IDs for negative inputs.
        """
        pass

    def bitmapbitposition_sql(self, expression: exp.BitmapBitPosition) -> str:
        """
        Transpile Snowflake's BITMAP_BIT_POSITION to DuckDB CASE expression.

        Snowflake's BITMAP_BIT_POSITION behavior:
        - For n <= 0: returns ABS(n) % 32768
        - For n > 0: returns (n - 1) % 32768 (maximum return value is 32767)
        """
        pass

    def bitmapconstructagg_sql(self, expression: exp.BitmapConstructAgg) -> str:
        """
        Transpile Snowflake's BITMAP_CONSTRUCT_AGG to DuckDB equivalent.
        Uses a pre-parsed template with placeholders replaced by expression nodes.

        Snowflake bitmap format:
        - Small (< 5 unique values): 2-byte count (big-endian) + values (little-endian) + padding to 10 bytes
        - Large (>= 5 unique values): 10-byte header (0x08 + 9 zeros) + values (little-endian)
        """
        pass

    def compress_sql(self, expression: exp.Compress) -> str:
        pass

    def encrypt_sql(self, expression: exp.Encrypt) -> str:
        pass

    def decrypt_sql(self, expression: exp.Decrypt) -> str:
        pass

    def decryptraw_sql(self, expression: exp.DecryptRaw) -> str:
        pass

    def encryptraw_sql(self, expression: exp.EncryptRaw) -> str:
        pass

    def parseurl_sql(self, expression: exp.ParseUrl) -> str:
        pass

    def parseip_sql(self, expression: exp.ParseIp) -> str:
        pass

    def jarowinklersimilarity_sql(self, expression: exp.JarowinklerSimilarity) -> str:
        pass

    def nthvalue_sql(self, expression: exp.NthValue) -> str:
        pass

    def randstr_sql(self, expression: exp.Randstr) -> str:
        """
        Transpile Snowflake's RANDSTR to DuckDB equivalent using deterministic hash-based random.
        Uses a pre-parsed template with placeholders replaced by expression nodes.

        RANDSTR(length, generator) generates a random string of specified length.
        - With numeric seed: Use HASH(i + seed) for deterministic output (same seed = same result)
        - With RANDOM(): Use RANDOM() in the hash for non-deterministic output
        - No generator: Use default seed value
        """
        pass

    @unsupported_args("finish")
    def reduce_sql(self, expression: exp.Reduce) -> str:
        pass

    def zipf_sql(self, expression: exp.Zipf) -> str:
        """
        Transpile Snowflake's ZIPF to DuckDB using CDF-based inverse sampling.
        Uses a pre-parsed template with placeholders replaced by expression nodes.
        """
        pass

    def tobinary_sql(self, expression: exp.ToBinary) -> str:
        """
        TO_BINARY and TRY_TO_BINARY transpilation:
        - 'HEX': TO_BINARY('48454C50', 'HEX') -> UNHEX('48454C50')
        - 'UTF-8': TO_BINARY('TEST', 'UTF-8') -> ENCODE('TEST')
        - 'BASE64': TO_BINARY('SEVMUA==', 'BASE64') -> FROM_BASE64('SEVMUA==')

        For TRY_TO_BINARY (safe=True), wrap with TRY():
        - 'HEX': TRY_TO_BINARY('invalid', 'HEX') -> TRY(UNHEX('invalid'))
        """
        pass

    def tonumber_sql(self, expression: exp.ToNumber) -> str:
        pass

    def _greatest_least_sql(self, expression: exp.Greatest | exp.Least) -> str:
        """
        Handle GREATEST/LEAST functions with dialect-aware NULL behavior.

        - If ignore_nulls=False (BigQuery-style): return NULL if any argument is NULL
        - If ignore_nulls=True (DuckDB/PostgreSQL-style): ignore NULLs, return greatest/least non-NULL value
        """
        pass

    def generator_sql(self, expression: exp.Generator) -> str:
        # Transpile Snowflake GENERATOR to DuckDB range()
        pass

    def greatest_sql(self, expression: exp.Greatest) -> str:
        pass

    def least_sql(self, expression: exp.Least) -> str:
        pass

    def lambda_sql(self, expression: exp.Lambda, arrow_sep: str = "->", wrap: bool = True) -> str:
        pass

    def show_sql(self, expression: exp.Show) -> str:
        from_ = self.sql(expression, "from_")
        from_ = f" FROM {from_}" if from_ else ""
        return f"SHOW {expression.name}{from_}"

    def sortarray_sql(self, expression: exp.SortArray) -> str:
        pass

    def install_sql(self, expression: exp.Install) -> str:
        pass

    def approxtopk_sql(self, expression: exp.ApproxTopK) -> str:
        pass

    def fromiso8601timestamp_sql(self, expression: exp.FromISO8601Timestamp) -> str:
        pass

    def strposition_sql(self, expression: exp.StrPosition) -> str:
        this = expression.this
        substr = expression.args.get("substr")
        position = expression.args.get("position")

        # For BINARY/BLOB: DuckDB's STRPOS doesn't support BLOB types
        # Convert to HEX strings, use STRPOS, then convert hex position to byte position
        if _is_binary(this):
            # Build expression: STRPOS(HEX(haystack), HEX(needle))
            hex_strpos = exp.StrPosition(
                this=exp.Hex(this=this),
                substr=exp.Hex(this=substr),
            )

            return self.sql(exp.cast((hex_strpos + 1) / 2, exp.DType.INT))

        # For VARCHAR: handle clamp_position
        if expression.args.get("clamp_position") and position:
            expression = expression.copy()
            expression.set(
                "position",
                exp.If(
                    this=exp.LTE(this=position, expression=exp.Literal.number(0)),
                    true=exp.Literal.number(1),
                    false=position.copy(),
                ),
            )

        return strposition_sql(self, expression)

    def substring_sql(self, expression: exp.Substring) -> str:
        pass

    def strtotime_sql(self, expression: exp.StrToTime) -> str:
        # Check if target_type requires TIMESTAMPTZ (for LTZ/TZ variants)
        pass

    def strtodate_sql(self, expression: exp.StrToDate) -> str:
        pass

    def tsordstotime_sql(self, expression: exp.TsOrDsToTime) -> str:
        pass

    def currentdate_sql(self, expression: exp.CurrentDate) -> str:
        pass

    def checkjson_sql(self, expression: exp.CheckJson) -> str:
        pass

    def parsejson_sql(self, expression: exp.ParseJSON) -> str:
        pass

    def unicode_sql(self, expression: exp.Unicode) -> str:
        pass

    def stripnullvalue_sql(self, expression: exp.StripNullValue) -> str:
        pass

    def trunc_sql(self, expression: exp.Trunc) -> str:
        pass

    def normal_sql(self, expression: exp.Normal) -> str:
        """
        Transpile Snowflake's NORMAL(mean, stddev, gen) to DuckDB.

        Uses the Box-Muller transform via NORMAL_TEMPLATE.
        """
        pass

    def uniform_sql(self, expression: exp.Uniform) -> str:
        """
        Transpile Snowflake's UNIFORM(min, max, gen) to DuckDB.

        UNIFORM returns a random value in [min, max]:
        - Integer result if both min and max are integers
        - Float result if either min or max is a float
        """
        pass

    def timefromparts_sql(self, expression: exp.TimeFromParts) -> str:
        pass

    def extract_sql(self, expression: exp.Extract) -> str:
        """
        Transpile EXTRACT/DATE_PART for DuckDB, handling specifiers not natively supported.

        DuckDB doesn't support: WEEKISO, YEAROFWEEK, YEAROFWEEKISO, NANOSECOND,
        EPOCH_SECOND (as integer), EPOCH_MILLISECOND, EPOCH_MICROSECOND, EPOCH_NANOSECOND
        """
        pass

    def timestampfromparts_sql(self, expression: exp.TimestampFromParts) -> str:
        # Check if this is the date/time expression form: TIMESTAMP_FROM_PARTS(date_expr, time_expr)
        pass

    @unsupported_args("nano")
    def timestampltzfromparts_sql(self, expression: exp.TimestampLtzFromParts) -> str:
        # Pop nano so rename_func only passes args that MAKE_TIMESTAMP accepts
        pass

    @unsupported_args("nano")
    def timestamptzfromparts_sql(self, expression: exp.TimestampTzFromParts) -> str:
        # Extract zone before popping
        pass

    def tablesample_sql(
        self,
        expression: exp.TableSample,
        tablesample_keyword: str | None = None,
    ) -> str:
        if not isinstance(expression.parent, exp.Select):
            # This sample clause only applies to a single source, not the entire resulting relation
            tablesample_keyword = "TABLESAMPLE"

        if expression.args.get("size"):
            method = expression.args.get("method")
            if method and method.name.upper() != "RESERVOIR":
                self.unsupported(
                    f"Sampling method {method} is not supported with a discrete sample count, "
                    "defaulting to reservoir sampling"
                )
                expression.set("method", exp.var("RESERVOIR"))

        return super().tablesample_sql(expression, tablesample_keyword=tablesample_keyword)

    def join_sql(self, expression: exp.Join) -> str:
        pass

    def countif_sql(self, expression: exp.CountIf) -> str:
        pass

    def bracket_sql(self, expression: exp.Bracket) -> str:
        pass

    def withingroup_sql(self, expression: exp.WithinGroup) -> str:
        pass

    def length_sql(self, expression: exp.Length) -> str:
        pass

    def bitlength_sql(self, expression: exp.BitLength) -> str:
        pass

    def chr_sql(self, expression: exp.Chr, name: str = "CHR") -> str:
        arg = expression.expressions[0]
        if arg.is_type(*exp.DataType.REAL_TYPES):
            arg = exp.cast(arg, exp.DType.INT)
        return self.func("CHR", arg)

    def collation_sql(self, expression: exp.Collation) -> str:
        pass

    def collate_sql(self, expression: exp.Collate) -> str:
        pass

    def _validate_regexp_flags(self, flags: exp.Expr | None, supported_flags: str) -> str | None:
        """
        Validate and filter regexp flags for DuckDB compatibility.

        Args:
            flags: The flags expression to validate
            supported_flags: String of supported flags (e.g., "ims", "cims").
                            Only these flags will be returned.

        Returns:
            Validated/filtered flag string, or None if no valid flags remain
        """
        pass

    def regexpcount_sql(self, expression: exp.RegexpCount) -> str:
        pass

    def regexpreplace_sql(self, expression: exp.RegexpReplace) -> str:
        pass

    def regexplike_sql(self, expression: exp.RegexpLike) -> str:
        pass

    @unsupported_args("ins_cost", "del_cost", "sub_cost")
    def levenshtein_sql(self, expression: exp.Levenshtein) -> str:
        pass

    def pad_sql(self, expression: exp.Pad) -> str:
        """
        Handle RPAD/LPAD for VARCHAR and BINARY types.

        For VARCHAR: Delegate to parent class
        For BINARY: Lower to: input || REPEAT(pad, GREATEST(0, target_len - OCTET_LENGTH(input)))
        """
        pass

    def minhash_sql(self, expression: exp.Minhash) -> str:
        pass

    def minhashcombine_sql(self, expression: exp.MinhashCombine) -> str:
        pass

    def approximatesimilarity_sql(self, expression: exp.ApproximateSimilarity) -> str:
        pass

    def arrayuniqueagg_sql(self, expression: exp.ArrayUniqueAgg) -> str:
        pass

    def arrayunionagg_sql(self, expression: exp.ArrayUnionAgg) -> str:
        pass

    def arraydistinct_sql(self, expression: exp.ArrayDistinct) -> str:
        pass

    def arrayintersect_sql(self, expression: exp.ArrayIntersect) -> str:
        pass

    def arrayexcept_sql(self, expression: exp.ArrayExcept) -> str:
        pass

    def arrayslice_sql(self, expression: exp.ArraySlice) -> str:
        """
        Transpiles Snowflake's ARRAY_SLICE (0-indexed, exclusive end) to DuckDB's
        ARRAY_SLICE (1-indexed, inclusive end) by wrapping start and end in CASE
        expressions that adjust the index at query time:
          - start: CASE WHEN start >= 0 THEN start + 1 ELSE start END
          - end:   CASE WHEN end < 0 THEN end - 1 ELSE end END
        """
        pass

    def arrayszip_sql(self, expression: exp.ArraysZip) -> str:
        pass

    def lower_sql(self, expression: exp.Lower) -> str:
        pass

    def upper_sql(self, expression: exp.Upper) -> str:
        pass

    def reverse_sql(self, expression: exp.Reverse) -> str:
        pass

    def _left_right_sql(self, expression: exp.Left | exp.Right, func_name: str) -> str:
        pass

    def left_sql(self, expression: exp.Left) -> str:
        pass

    def right_sql(self, expression: exp.Right) -> str:
        pass

    def rtrimmedlength_sql(self, expression: exp.RtrimmedLength) -> str:
        pass

    def stuff_sql(self, expression: exp.Stuff) -> str:
        pass

    def rand_sql(self, expression: exp.Rand) -> str:
        pass

    def bytelength_sql(self, expression: exp.ByteLength) -> str:
        pass

    def base64encode_sql(self, expression: exp.Base64Encode) -> str:
        # DuckDB TO_BASE64 requires BLOB input
        # Snowflake BASE64_ENCODE accepts both VARCHAR and BINARY - for VARCHAR it implicitly
        # encodes UTF-8 bytes. We add ENCODE unless the input is a binary type.
        pass

    def replace_sql(self, expression: exp.Replace) -> str:
        pass

    def _bitwise_op(self, expression: exp.Binary, op: str) -> str:
        _prepare_binary_bitwise_args(expression)
        result_sql = self.binary(expression, op)
        return _gen_with_cast_to_blob(self, expression, result_sql)

    def bitwisexor_sql(self, expression: exp.BitwiseXor) -> str:
        pass

    def objectinsert_sql(self, expression: exp.ObjectInsert) -> str:
        pass

    def mapcat_sql(self, expression: exp.MapCat) -> str:
        pass

    def mapcontainskey_sql(self, expression: exp.MapContainsKey) -> str:
        pass

    def mapdelete_sql(self, expression: exp.MapDelete) -> str:
        pass

    def mappick_sql(self, expression: exp.MapPick) -> str:
        pass

    def mapsize_sql(self, expression: exp.MapSize) -> str:
        pass

    @unsupported_args("update_flag")
    def mapinsert_sql(self, expression: exp.MapInsert) -> str:
        pass

    def startswith_sql(self, expression: exp.StartsWith) -> str:
        pass

    def space_sql(self, expression: exp.Space) -> str:
        # DuckDB's REPEAT requires BIGINT for the count parameter
        pass

    def tablefromrows_sql(self, expression: exp.TableFromRows) -> str:
        # For GENERATOR, unwrap TABLE() - just emit the Generator (becomes RANGE)
        pass

    def unnest_sql(self, expression: exp.Unnest) -> str:
        pass

    def ignorenulls_sql(self, expression: exp.IgnoreNulls) -> str:
        pass

    def split_sql(self, expression: exp.Split) -> str:
        pass

    def splitpart_sql(self, expression: exp.SplitPart) -> str:
        pass

    def respectnulls_sql(self, expression: exp.RespectNulls) -> str:
        pass

    def arraytostring_sql(self, expression: exp.ArrayToString) -> str:
        pass

    def concatws_sql(self, expression: exp.ConcatWs) -> str:
        # DuckDB-specific: handle binary types using DPipe (||) operator
        pass

    def _regexp_extract_sql(self, expression: exp.RegexpExtract | exp.RegexpExtractAll) -> str:
        pass

    def regexpextract_sql(self, expression: exp.RegexpExtract) -> str:
        pass

    def regexpextractall_sql(self, expression: exp.RegexpExtractAll) -> str:
        pass

    def regexpinstr_sql(self, expression: exp.RegexpInstr) -> str:
        pass

    @unsupported_args("culture")
    def numbertostr_sql(self, expression: exp.NumberToStr) -> str:
        pass

    def autoincrementcolumnconstraint_sql(self, _) -> str:
        pass

    def aliases_sql(self, expression: exp.Aliases) -> str:
        pass

    def posexplode_sql(self, expression: exp.Posexplode) -> str:
        pass

    def addmonths_sql(self, expression: exp.AddMonths) -> str:
        """
        Handles three key issues:
        1. Float/decimal months: e.g., Snowflake rounds, whereas DuckDB INTERVAL requires integers
        2. End-of-month preservation: If input is last day of month, result is last day of result month
        3. Type preservation: Maintains DATE/TIMESTAMPTZ types (DuckDB defaults to TIMESTAMP)
        """
        pass

    def format_sql(self, expression: exp.Format) -> str:
        pass

    def hexstring_sql(
        self, expression: exp.HexString, binary_function_repr: str | None = None
    ) -> str:
        # UNHEX('FF') correctly produces blob \xFF in DuckDB
        return super().hexstring_sql(expression, binary_function_repr="UNHEX")

    def datetrunc_sql(self, expression: exp.DateTrunc) -> str:
        pass

    def timestamptrunc_sql(self, expression: exp.TimestampTrunc) -> str:
        unit = unit_to_str(expression)
        zone = expression.args.get("zone")
        timestamp = expression.this
        date_unit = is_date_unit(unit)

        if date_unit and zone:
            # BigQuery's TIMESTAMP_TRUNC with timezone truncates in the target timezone and returns as UTC.
            # Double AT TIME ZONE needed for BigQuery compatibility:
            # 1. First AT TIME ZONE: ensures truncation happens in the target timezone
            # 2. Second AT TIME ZONE: converts the DATE result back to TIMESTAMPTZ (preserving time component)
            timestamp = exp.AtTimeZone(this=timestamp, zone=zone)
            result_sql = self.func("DATE_TRUNC", unit, timestamp)
            return self.sql(exp.AtTimeZone(this=result_sql, zone=zone))

        result = self.func("DATE_TRUNC", unit, timestamp)
        if expression.args.get("input_type_preserved"):
            if timestamp.type and timestamp.is_type(exp.DType.TIME, exp.DType.TIMETZ):
                dummy_date = exp.Cast(
                    this=exp.Literal.string("1970-01-01"),
                    to=exp.DataType(this=exp.DType.DATE),
                )
                date_time = exp.Add(this=dummy_date, expression=timestamp)
                result = self.func("DATE_TRUNC", unit, date_time)
                return self.sql(exp.Cast(this=result, to=timestamp.type))

            if timestamp.is_type(*exp.DataType.TEMPORAL_TYPES) and not (
                date_unit and timestamp.is_type(exp.DType.DATE)
            ):
                return self.sql(exp.Cast(this=result, to=timestamp.type))

        return result

    def trim_sql(self, expression: exp.Trim) -> str:
        expression.this.replace(_cast_to_varchar(expression.this))
        if expression.expression:
            expression.expression.replace(_cast_to_varchar(expression.expression))

        result_sql = super().trim_sql(expression)
        return _gen_with_cast_to_blob(self, expression, result_sql)

    def round_sql(self, expression: exp.Round) -> str:
        pass

    def strtok_sql(self, expression: exp.Strtok) -> str:
        pass

    def approxquantile_sql(self, expression: exp.ApproxQuantile) -> str:
        pass

    def approxquantiles_sql(self, expression: exp.ApproxQuantiles) -> str:
        """
        BigQuery's APPROX_QUANTILES(expr, n) returns an array of n+1 approximate quantile values
        dividing the input distribution into n equal-sized buckets.

        Both BigQuery and DuckDB use approximate algorithms for quantile estimation, but BigQuery
        does not document the specific algorithm used so results may differ. DuckDB does not
        support RESPECT NULLS.
        """
        pass

    def jsonextractscalar_sql(self, expression: exp.JSONExtractScalar) -> str:
        pass

    def bitwisenot_sql(self, expression: exp.BitwiseNot) -> str:
        pass

    def window_sql(self, expression: exp.Window) -> str:
        this = expression.this
        if isinstance(this, exp.Corr) or (
            isinstance(this, exp.Filter) and isinstance(this.this, exp.Corr)
        ):
            return self._corr_sql(expression)

        return super().window_sql(expression)

    def filter_sql(self, expression: exp.Filter) -> str:
        if isinstance(expression.this, exp.Corr):
            return self._corr_sql(expression)

        return super().filter_sql(expression)

    def _corr_sql(
        self,
        expression: exp.Filter | exp.Window | exp.Corr,
    ) -> str:
        if isinstance(expression, exp.Corr) and not expression.args.get("null_on_zero_variance"):
            return self.func("CORR", expression.this, expression.expression)

        corr_expr = _maybe_corr_null_to_false(expression)
        if corr_expr is None:
            if isinstance(expression, exp.Window):
                return super().window_sql(expression)
            if isinstance(expression, exp.Filter):
                return super().filter_sql(expression)
            corr_expr = expression  # make mypy happy

        return self.sql(exp.case().when(exp.IsNan(this=corr_expr), exp.null()).else_(corr_expr))
