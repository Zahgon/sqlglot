from __future__ import annotations

import typing as t

from sqlglot import exp, generator, transforms
from sqlglot.dialects.dialect import (
    DATE_ADD_OR_SUB,
    groupconcat_sql,
    no_last_day_sql,
    rename_func,
    strposition_sql,
    timestrtotime_sql,
    timestamptrunc_sql,
)
from sqlglot.errors import UnsupportedError
from sqlglot.generator import unsupported_args
from sqlglot.optimizer.scope import build_scope
from sqlglot.parsers.exasol import DATE_UNITS


def _sha2_sql(self: ExasolGenerator, expression: exp.SHA2) -> str:
    pass


def _date_diff_sql(self: ExasolGenerator, expression: exp.DateDiff | exp.TsOrDsDiff) -> str:
    pass


# https://docs.exasol.com/db/latest/sql/select.htm#:~:text=If%20you%20have,local.x%3E10
def _add_local_prefix_for_aliases(expression: exp.Expr) -> exp.Expr:
    pass


def _trunc_sql(
    self: ExasolGenerator, kind: str, expression: exp.DateTrunc | exp.TimestampTrunc
) -> str:
    pass


def _date_trunc_sql(self: ExasolGenerator, expression: exp.DateTrunc) -> str:
    pass


def _timestamp_trunc_sql(
    self: ExasolGenerator, expression: exp.DateTrunc | exp.TimestampTrunc
) -> str:
    pass


def is_case_insensitive(node: exp.Expr) -> bool:
    pass


def _substring_index_sql(self: ExasolGenerator, expression: exp.SubstringIndex) -> str:
    pass


# https://docs.exasol.com/db/latest/sql/select.htm#:~:text=The%20select_list%20defines%20the%20columns%20of%20the%20result%20table.%20If%20*%20is%20used%2C%20all%20columns%20are%20listed.%20You%20can%20use%20an%20expression%20like%20t.*%20to%20list%20all%20columns%20of%20the%20table%20t%2C%20the%20view%20t%2C%20or%20the%20object%20with%20the%20table%20alias%20t.
def _qualify_unscoped_star(expression: exp.Expr) -> exp.Expr:
    """
    Exasol doesn't support a bare * alongside other select items, so we rewrite it
    Rewrite: SELECT *, <other> FROM <Table>
    Into: SELECT T.*, <other> FROM <Table> AS T
    """
    pass


def _add_date_sql(self: ExasolGenerator, expression: DATE_ADD_OR_SUB) -> str:
    pass


def _group_by_all(expression: exp.Expr) -> exp.Expr:
    pass


class ExasolGenerator(generator.Generator):
    SELECT_KINDS: tuple[str, ...] = ()
    TRY_SUPPORTED = False
    SUPPORTS_UESCAPE = False
    SUPPORTS_DECODE_CASE = False

    AFTER_HAVING_MODIFIER_TRANSFORMS = generator.AFTER_HAVING_MODIFIER_TRANSFORMS

    # https://docs.exasol.com/db/latest/sql_references/data_types/datatypedetails.htm#StringDataType
    STRING_TYPE_MAPPING: t.ClassVar = {
        exp.DType.BLOB: "VARCHAR",
        exp.DType.LONGBLOB: "VARCHAR",
        exp.DType.LONGTEXT: "VARCHAR",
        exp.DType.MEDIUMBLOB: "VARCHAR",
        exp.DType.MEDIUMTEXT: "VARCHAR",
        exp.DType.TINYBLOB: "VARCHAR",
        exp.DType.TINYTEXT: "VARCHAR",
        # https://docs.exasol.com/db/latest/sql_references/data_types/datatypealiases.htm
        exp.DType.TEXT: "LONG VARCHAR",
        exp.DType.VARBINARY: "VARCHAR",
    }

    # https://docs.exasol.com/db/latest/sql_references/data_types/datatypealiases.htm
    TYPE_MAPPING = {
        **generator.Generator.TYPE_MAPPING,
        **STRING_TYPE_MAPPING,
        exp.DType.TINYINT: "SMALLINT",
        exp.DType.MEDIUMINT: "INT",
        exp.DType.DECIMAL32: "DECIMAL",
        exp.DType.DECIMAL64: "DECIMAL",
        exp.DType.DECIMAL128: "DECIMAL",
        exp.DType.DECIMAL256: "DECIMAL",
        exp.DType.DATETIME: "TIMESTAMP",
        exp.DType.TIMESTAMPTZ: "TIMESTAMP",
        exp.DType.TIMESTAMPLTZ: "TIMESTAMP",
        exp.DType.TIMESTAMPNTZ: "TIMESTAMP",
    }

    def datatype_sql(self, expression: exp.DataType) -> str:
        # Exasol supports a fixed default precision of 3 for TIMESTAMP WITH LOCAL TIME ZONE
        # and does not allow specifying a different custom precision
        pass

    TRANSFORMS = {
        **generator.Generator.TRANSFORMS,
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/every.htm
        exp.All: rename_func("EVERY"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/bit_and.htm
        exp.BitwiseAnd: rename_func("BIT_AND"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/bit_or.htm
        exp.BitwiseOr: rename_func("BIT_OR"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/bit_not.htm
        exp.BitwiseNot: rename_func("BIT_NOT"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/bit_lshift.htm
        exp.BitwiseLeftShift: rename_func("BIT_LSHIFT"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/bit_rshift.htm
        exp.BitwiseRightShift: rename_func("BIT_RSHIFT"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/bit_xor.htm
        exp.BitwiseXor: rename_func("BIT_XOR"),
        exp.CurrentSchema: lambda *_: "CURRENT_SCHEMA",
        exp.DateDiff: _date_diff_sql,
        exp.DateAdd: _add_date_sql,
        exp.TsOrDsAdd: _add_date_sql,
        exp.DateSub: _add_date_sql,
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/div.htm#DIV
        exp.IntDiv: rename_func("DIV"),
        exp.TsOrDsDiff: _date_diff_sql,
        exp.DateTrunc: _date_trunc_sql,
        exp.DayOfWeek: lambda self, e: f"CAST(TO_CHAR({self.sql(e, 'this')}, 'D') AS INTEGER)",
        exp.DatetimeTrunc: timestamptrunc_sql(),
        exp.GroupConcat: lambda self, e: groupconcat_sql(
            self, e, func_name="LISTAGG", within_group=True
        ),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/edit_distance.htm#EDIT_DISTANCE
        exp.Levenshtein: unsupported_args("ins_cost", "del_cost", "sub_cost", "max_dist")(
            rename_func("EDIT_DISTANCE")
        ),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/mod.htm
        exp.Mod: rename_func("MOD"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/from_posix_time.htm
        exp.UnixToTime: lambda self, e: self.func("FROM_POSIX_TIME", e.this),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/rank.htm
        exp.Rank: unsupported_args("expressions")(lambda *_: "RANK()"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/dense_rank.htm
        exp.DenseRank: unsupported_args("expressions")(lambda *_: "DENSE_RANK()"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/regexp_substr.htm
        exp.RegexpExtract: unsupported_args("parameters", "group")(rename_func("REGEXP_SUBSTR")),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/regexp_replace.htm
        exp.RegexpReplace: unsupported_args("modifiers")(rename_func("REGEXP_REPLACE")),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/var_pop.htm
        exp.VariancePop: rename_func("VAR_POP"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/approximate_count_distinct.htm
        exp.ApproxDistinct: unsupported_args("accuracy")(rename_func("APPROXIMATE_COUNT_DISTINCT")),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/to_char%20(datetime).htm
        exp.TimeToStr: lambda self, e: self.func("TO_CHAR", e.this, self.format_time(e)),
        exp.ToChar: lambda self, e: self.func("TO_CHAR", e.this, self.format_time(e)),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/to_date.htm
        exp.TsOrDsToDate: lambda self, e: self.func("TO_DATE", e.this, self.format_time(e)),
        exp.TimeStrToTime: timestrtotime_sql,
        exp.TimestampTrunc: _timestamp_trunc_sql,
        exp.StrToTime: lambda self, e: self.func("TO_DATE", e.this, self.format_time(e)),
        exp.CurrentUser: lambda *_: "CURRENT_USER",
        exp.AtTimeZone: lambda self, e: self.func(
            "CONVERT_TZ",
            e.this,
            "'UTC'",
            e.args.get("zone"),
        ),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/instr.htm
        exp.StrPosition: lambda self, e: strposition_sql(
            self, e, func_name="INSTR", supports_position=True, supports_occurrence=True
        ),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/hash_sha%5B1%5D.htm#HASH_SHA%5B1%5D
        exp.SHA: rename_func("HASH_SHA"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/hash_sha256.htm
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/hash_sha512.htm
        exp.SHA2: _sha2_sql,
        exp.MD5: rename_func("HASH_MD5"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/hashtype_md5.htm
        exp.MD5Digest: rename_func("HASHTYPE_MD5"),
        # https://docs.exasol.com/db/latest/sql/create_view.htm
        exp.CommentColumnConstraint: lambda self, e: f"COMMENT IS {self.sql(e, 'this')}",
        exp.Select: transforms.preprocess(
            [
                _qualify_unscoped_star,
                _add_local_prefix_for_aliases,
                _group_by_all,
            ]
        ),
        exp.SubstringIndex: _substring_index_sql,
        exp.WeekOfYear: rename_func("WEEK"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/to_date.htm
        exp.Date: rename_func("TO_DATE"),
        # https://docs.exasol.com/db/latest/sql_references/functions/alphabeticallistfunctions/to_timestamp.htm
        exp.Timestamp: rename_func("TO_TIMESTAMP"),
        exp.Quarter: lambda self, e: f"CEIL(MONTH(TO_DATE({self.sql(e, 'this')}))/3)",
        exp.LastDay: no_last_day_sql,
    }

    # https://docs.exasol.com/db/7.1/sql_references/system_tables/metadata/exa_sql_keywords.htm
    RESERVED_KEYWORDS = {
        "absolute",
        "action",
        "add",
        "after",
        "all",
        "allocate",
        "alter",
        "and",
        "any",
        "append",
        "are",
        "array",
        "as",
        "asc",
        "asensitive",
        "assertion",
        "at",
        "attribute",
        "authid",
        "authorization",
        "before",
        "begin",
        "between",
        "bigint",
        "binary",
        "bit",
        "blob",
        "blocked",
        "bool",
        "boolean",
        "both",
        "by",
        "byte",
        "call",
        "called",
        "cardinality",
        "cascade",
        "cascaded",
        "case",
        "casespecific",
        "cast",
        "catalog",
        "chain",
        "char",
        "character",
        "character_set_catalog",
        "character_set_name",
        "character_set_schema",
        "characteristics",
        "check",
        "checked",
        "clob",
        "close",
        "coalesce",
        "collate",
        "collation",
        "collation_catalog",
        "collation_name",
        "collation_schema",
        "column",
        "commit",
        "condition",
        "connect_by_iscycle",
        "connect_by_isleaf",
        "connect_by_root",
        "connection",
        "constant",
        "constraint",
        "constraint_state_default",
        "constraints",
        "constructor",
        "contains",
        "continue",
        "control",
        "convert",
        "corresponding",
        "create",
        "cs",
        "csv",
        "cube",
        "current",
        "current_cluster",
        "current_cluster_uid",
        "current_date",
        "current_path",
        "current_role",
        "current_schema",
        "current_session",
        "current_statement",
        "current_time",
        "current_timestamp",
        "current_user",
        "cursor",
        "cycle",
        "data",
        "datalink",
        "datetime_interval_code",
        "datetime_interval_precision",
        "day",
        "dbtimezone",
        "deallocate",
        "dec",
        "decimal",
        "declare",
        "default",
        "default_like_escape_character",
        "deferrable",
        "deferred",
        "defined",
        "definer",
        "delete",
        "deref",
        "derived",
        "desc",
        "describe",
        "descriptor",
        "deterministic",
        "disable",
        "disabled",
        "disconnect",
        "dispatch",
        "distinct",
        "dlurlcomplete",
        "dlurlpath",
        "dlurlpathonly",
        "dlurlscheme",
        "dlurlserver",
        "dlvalue",
        "do",
        "domain",
        "double",
        "drop",
        "dynamic",
        "dynamic_function",
        "dynamic_function_code",
        "each",
        "else",
        "elseif",
        "elsif",
        "emits",
        "enable",
        "enabled",
        "end",
        "end-exec",
        "endif",
        "enforce",
        "equals",
        "errors",
        "escape",
        "except",
        "exception",
        "exec",
        "execute",
        "exists",
        "exit",
        "export",
        "external",
        "extract",
        "false",
        "fbv",
        "fetch",
        "file",
        "final",
        "first",
        "float",
        "following",
        "for",
        "forall",
        "force",
        "format",
        "found",
        "free",
        "from",
        "fs",
        "full",
        "function",
        "general",
        "generated",
        "geometry",
        "get",
        "global",
        "go",
        "goto",
        "grant",
        "granted",
        "group",
        "group_concat",
        "grouping",
        "groups",
        "hashtype",
        "hashtype_format",
        "having",
        "high",
        "hold",
        "hour",
        "identity",
        "if",
        "ifnull",
        "immediate",
        "impersonate",
        "implementation",
        "import",
        "in",
        "index",
        "indicator",
        "inner",
        "inout",
        "input",
        "insensitive",
        "insert",
        "instance",
        "instantiable",
        "int",
        "integer",
        "integrity",
        "intersect",
        "interval",
        "into",
        "inverse",
        "invoker",
        "is",
        "iterate",
        "join",
        "key_member",
        "key_type",
        "large",
        "last",
        "lateral",
        "ldap",
        "leading",
        "leave",
        "left",
        "level",
        "like",
        "limit",
        "listagg",
        "localtime",
        "localtimestamp",
        "locator",
        "log",
        "longvarchar",
        "loop",
        "low",
        "map",
        "match",
        "matched",
        "merge",
        "method",
        "minus",
        "minute",
        "mod",
        "modifies",
        "modify",
        "module",
        "month",
        "names",
        "national",
        "natural",
        "nchar",
        "nclob",
        "new",
        "next",
        "nls_date_format",
        "nls_date_language",
        "nls_first_day_of_week",
        "nls_numeric_characters",
        "nls_timestamp_format",
        "no",
        "nocycle",
        "nologging",
        "none",
        "not",
        "null",
        "nullif",
        "number",
        "numeric",
        "nvarchar",
        "nvarchar2",
        "object",
        "of",
        "off",
        "old",
        "on",
        "only",
        "open",
        "option",
        "options",
        "or",
        "order",
        "ordering",
        "ordinality",
        "others",
        "out",
        "outer",
        "output",
        "over",
        "overlaps",
        "overlay",
        "overriding",
        "pad",
        "parallel_enable",
        "parameter",
        "parameter_specific_catalog",
        "parameter_specific_name",
        "parameter_specific_schema",
        "parquet",
        "partial",
        "path",
        "permission",
        "placing",
        "plus",
        "preceding",
        "preferring",
        "prepare",
        "preserve",
        "prior",
        "privileges",
        "procedure",
        "profile",
        "qualify",
        "random",
        "range",
        "read",
        "reads",
        "real",
        "recovery",
        "recursive",
        "ref",
        "references",
        "referencing",
        "refresh",
        "regexp_like",
        "relative",
        "release",
        "rename",
        "repeat",
        "replace",
        "restore",
        "restrict",
        "result",
        "return",
        "returned_length",
        "returned_octet_length",
        "returns",
        "revoke",
        "right",
        "rollback",
        "rollup",
        "routine",
        "row",
        "rows",
        "rowtype",
        "savepoint",
        "schema",
        "scope",
        "scope_user",
        "script",
        "scroll",
        "search",
        "second",
        "section",
        "security",
        "select",
        "selective",
        "self",
        "sensitive",
        "separator",
        "sequence",
        "session",
        "session_user",
        "sessiontimezone",
        "set",
        "sets",
        "shortint",
        "similar",
        "smallint",
        "some",
        "source",
        "space",
        "specific",
        "specifictype",
        "sql",
        "sql_bigint",
        "sql_bit",
        "sql_char",
        "sql_date",
        "sql_decimal",
        "sql_double",
        "sql_float",
        "sql_integer",
        "sql_longvarchar",
        "sql_numeric",
        "sql_preprocessor_script",
        "sql_real",
        "sql_smallint",
        "sql_timestamp",
        "sql_tinyint",
        "sql_type_date",
        "sql_type_timestamp",
        "sql_varchar",
        "sqlexception",
        "sqlstate",
        "sqlwarning",
        "start",
        "state",
        "statement",
        "static",
        "structure",
        "style",
        "substring",
        "subtype",
        "sysdate",
        "system",
        "system_user",
        "systimestamp",
        "table",
        "temporary",
        "text",
        "then",
        "time",
        "timestamp",
        "timezone_hour",
        "timezone_minute",
        "tinyint",
        "to",
        "trailing",
        "transaction",
        "transform",
        "transforms",
        "translation",
        "treat",
        "trigger",
        "trim",
        "true",
        "truncate",
        "under",
        "union",
        "unique",
        "unknown",
        "unlink",
        "unnest",
        "until",
        "update",
        "usage",
        "user",
        "using",
        "value",
        "values",
        "varchar",
        "varchar2",
        "varray",
        "verify",
        "view",
        "when",
        "whenever",
        "where",
        "while",
        "window",
        "with",
        "within",
        "without",
        "work",
        "year",
        "yes",
        "zone",
    }

    def converttimezone_sql(self, expression: exp.ConvertTimezone) -> str:
        pass

    def if_sql(self, expression: exp.If) -> str:
        this = self.sql(expression, "this")
        true = self.sql(expression, "true")
        false = self.sql(expression, "false")
        return f"IF {this} THEN {true} ELSE {false} ENDIF"

    def collate_sql(self, expression: exp.Collate) -> str:
        pass

    def jsonextract_sql(self, expression: exp.JSONExtract) -> str:
        pass

    @unsupported_args("flag")
    def regexplike_sql(self, expression: exp.RegexpLike) -> str:
        pass
