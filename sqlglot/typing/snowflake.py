from __future__ import annotations

import typing as t

from sqlglot import exp
from sqlglot.helper import seq_get
from sqlglot.typing import EXPRESSION_METADATA

if t.TYPE_CHECKING:
    from sqlglot.optimizer.annotate_types import TypeAnnotator

DATE_PARTS = {"DAY", "WEEK", "MONTH", "QUARTER", "YEAR"}

MAX_PRECISION = 38

MAX_SCALE = 37


def _annotate_reverse(self: TypeAnnotator, expression: exp.Reverse) -> exp.Reverse:
    pass


def _annotate_timestamp_from_parts(
    self: TypeAnnotator, expression: exp.TimestampFromParts
) -> exp.TimestampFromParts:
    """Annotate TimestampFromParts with correct type based on arguments.
    TIMESTAMP_FROM_PARTS with time_zone -> TIMESTAMPTZ
    TIMESTAMP_FROM_PARTS without time_zone -> TIMESTAMP (defaults to TIMESTAMP_NTZ)
    """
    pass


def _annotate_date_or_time_add(self: TypeAnnotator, expression: exp.Expr) -> exp.Expr:
    pass


def _annotate_decode_case(self: TypeAnnotator, expression: exp.DecodeCase) -> exp.DecodeCase:
    """Annotate DecodeCase with the type inferred from return values only.

    DECODE uses the format: DECODE(expr, val1, ret1, val2, ret2, ..., default)
    We only look at the return values (ret1, ret2, ..., default) to determine the type,
    not the comparison values (val1, val2, ...) or the expression being compared.
    """
    pass


def _annotate_arg_max_min(self, expression):
    pass


def _annotate_within_group(self: TypeAnnotator, expression: exp.WithinGroup) -> exp.WithinGroup:
    """Annotate WithinGroup with correct type based on the inner function.

    1) Annotate args first
    2) Check if this is PercentileDisc/PercentileCont and if so, re-annotate its type to match the ordered expression's type
    """
    pass


def _annotate_median(self: TypeAnnotator, expression: exp.Median) -> exp.Median:
    """Annotate MEDIAN function with correct return type.

    Based on Snowflake documentation:
    - If the expr is FLOAT/DOUBLE -> annotate as DOUBLE (FLOAT is a synonym for DOUBLE)
    - If the expr is NUMBER(p, s) -> annotate as NUMBER(min(p+3, 38), min(s+3, 37))
    """
    pass


def _annotate_variance(self: TypeAnnotator, expression: exp.Expr) -> exp.Expr:
    """Annotate variance functions (VAR_POP, VAR_SAMP, VARIANCE, VARIANCE_POP) with correct return type.

    Based on Snowflake behavior:
    - DECFLOAT -> DECFLOAT(38)
    - FLOAT/DOUBLE -> FLOAT
    - INT, NUMBER(p, 0) -> NUMBER(38, 6)
    - NUMBER(p, s) -> NUMBER(38, max(12, s))
    """
    pass


def _annotate_kurtosis(self: TypeAnnotator, expression: exp.Kurtosis) -> exp.Kurtosis:
    """Annotate KURTOSIS with correct return type.

    Based on Snowflake behavior:
    - DECFLOAT input -> DECFLOAT
    - DOUBLE or FLOAT input -> DOUBLE
    - Other numeric types (INT, NUMBER) -> NUMBER(38, 12)
    """
    pass


def _annotate_math_with_float_decfloat(self: TypeAnnotator, expression: exp.Expr) -> exp.Expr:
    """Annotate math functions that preserve  DECFLOAT but return DOUBLE for others.

    In Snowflake, trigonometric and exponential math functions:
    - If input is DECFLOAT -> return DECFLOAT
    - For integer types (INT, BIGINT, etc.) -> return DOUBLE
    - For other numeric types (NUMBER, DECIMAL, DOUBLE) -> return DOUBLE
    """
    pass


def _annotate_str_to_time(self: TypeAnnotator, expression: exp.StrToTime) -> exp.StrToTime:
    # target_type is stored as a DataType instance
    pass


EXPRESSION_METADATA = {
    **EXPRESSION_METADATA,
    **{
        expr_type: {"annotator": lambda self, e: self._annotate_by_args(e, "this")}
        for expr_type in {
            exp.AddMonths,
            exp.Ceil,
            exp.DateTrunc,
            exp.Floor,
            exp.Left,
            exp.Mode,
            exp.Pad,
            exp.Right,
            exp.Round,
            exp.Stuff,
            exp.Substring,
            exp.TimeSlice,
            exp.TimestampTrunc,
        }
    },
    **{
        expr_type: {"returns": exp.DType.ARRAY}
        for expr_type in (
            exp.ApproxTopK,
            exp.ApproxTopKEstimate,
            exp.Array,
            exp.ArrayAgg,
            exp.ArrayAppend,
            exp.ArrayCompact,
            exp.ArrayConcat,
            exp.ArrayConstructCompact,
            exp.ArrayPrepend,
            exp.ArrayRemove,
            exp.ArraysZip,
            exp.ArrayUniqueAgg,
            exp.ArrayUnionAgg,
            exp.MapKeys,
            exp.RegexpExtractAll,
            exp.Split,
            exp.StringToArray,
        )
    },
    **{
        expr_type: {"returns": exp.DType.BIGINT}
        for expr_type in {
            exp.BitmapBitPosition,
            exp.BitmapBucketNumber,
            exp.BitmapCount,
            exp.Factorial,
            exp.GroupingId,
            exp.MD5NumberLower64,
            exp.MD5NumberUpper64,
            exp.Rand,
            exp.Seq8,
            exp.Zipf,
        }
    },
    **{
        expr_type: {"returns": exp.DType.BINARY}
        for expr_type in {
            exp.Base64DecodeBinary,
            exp.BitmapConstructAgg,
            exp.BitmapOrAgg,
            exp.Compress,
            exp.DecompressBinary,
            exp.Decrypt,
            exp.DecryptRaw,
            exp.Encrypt,
            exp.EncryptRaw,
            exp.HexString,
            exp.MD5Digest,
            exp.SHA1Digest,
            exp.SHA2Digest,
            exp.ToBinary,
            exp.TryBase64DecodeBinary,
            exp.TryHexDecodeBinary,
            exp.Unhex,
        }
    },
    **{
        expr_type: {"returns": exp.DType.BOOLEAN}
        for expr_type in {
            exp.Booland,
            exp.Boolnot,
            exp.Boolor,
            exp.BoolxorAgg,
            exp.EqualNull,
            exp.IsNullValue,
            exp.MapContainsKey,
            exp.Search,
            exp.SearchIp,
            exp.ToBoolean,
        }
    },
    **{
        expr_type: {"returns": exp.DType.DATE}
        for expr_type in {
            exp.NextDay,
            exp.PreviousDay,
        }
    },
    **{
        expr_type: {
            "annotator": lambda self, e: self._set_type(
                e, exp.DataType.build("NUMBER", dialect="snowflake")
            )
        }
        for expr_type in (
            exp.BitwiseAndAgg,
            exp.BitwiseOrAgg,
            exp.BitwiseXorAgg,
            exp.RegexpCount,
            exp.RegexpInstr,
            exp.ToNumber,
        )
    },
    **{
        expr_type: {"returns": exp.DType.DOUBLE}
        for expr_type in {
            exp.ApproxPercentileEstimate,
            exp.ApproximateSimilarity,
            exp.CosineDistance,
            exp.CovarPop,
            exp.CovarSamp,
            exp.DotProduct,
            exp.EuclideanDistance,
            exp.ManhattanDistance,
            exp.MonthsBetween,
            exp.Normal,
        }
    },
    exp.Kurtosis: {"annotator": _annotate_kurtosis},
    **{
        expr_type: {"returns": exp.DType.DECFLOAT}
        for expr_type in {
            exp.ToDecfloat,
            exp.TryToDecfloat,
        }
    },
    **{
        expr_type: {"annotator": _annotate_math_with_float_decfloat}
        for expr_type in {
            exp.Acos,
            exp.Asin,
            exp.Atan,
            exp.Atan2,
            exp.Cbrt,
            exp.Cos,
            exp.Cot,
            exp.Degrees,
            exp.Exp,
            exp.Ln,
            exp.Log,
            exp.Pow,
            exp.Radians,
            exp.RegrAvgx,
            exp.RegrAvgy,
            exp.RegrCount,
            exp.RegrIntercept,
            exp.RegrR2,
            exp.RegrSlope,
            exp.RegrSxx,
            exp.RegrSxy,
            exp.RegrSyy,
            exp.RegrValx,
            exp.RegrValy,
            exp.Sin,
            exp.Sqrt,
            exp.Tan,
            exp.Tanh,
        }
    },
    **{
        expr_type: {"returns": exp.DType.INT}
        for expr_type in {
            exp.ByteLength,
            exp.Grouping,
            exp.JarowinklerSimilarity,
            exp.MapSize,
            exp.Minute,
            exp.RtrimmedLength,
            exp.Second,
            exp.Seq1,
            exp.Seq2,
            exp.Seq4,
            exp.WidthBucket,
        }
    },
    **{
        expr_type: {"returns": exp.DType.OBJECT}
        for expr_type in {
            exp.ApproxPercentileAccumulate,
            exp.ApproxPercentileCombine,
            exp.ApproxTopKAccumulate,
            exp.ApproxTopKCombine,
            exp.ObjectAgg,
            exp.ParseIp,
            exp.ParseUrl,
            exp.XMLGet,
        }
    },
    **{
        expr_type: {"returns": exp.DType.MAP}
        for expr_type in {
            exp.MapCat,
            exp.MapDelete,
            exp.MapInsert,
            exp.MapPick,
        }
    },
    **{
        expr_type: {"returns": exp.DType.FILE}
        for expr_type in {
            exp.ToFile,
        }
    },
    **{
        expr_type: {"returns": exp.DType.TIME}
        for expr_type in {
            exp.TimeFromParts,
            exp.TsOrDsToTime,
        }
    },
    **{
        expr_type: {"returns": exp.DType.TIMESTAMPLTZ}
        for expr_type in {
            exp.CurrentTimestamp,
            exp.Localtimestamp,
        }
    },
    **{
        expr_type: {"returns": exp.DType.TINYINT}
        for expr_type in {
            exp.DayOfMonth,
            exp.DayOfWeek,
            exp.DayOfYear,
            exp.Quarter,
        }
    },
    **{
        expr_type: {"returns": exp.DType.VARCHAR}
        for expr_type in {
            exp.AIAgg,
            exp.AIClassify,
            exp.AISummarizeAgg,
            exp.Base64DecodeString,
            exp.Base64Encode,
            exp.CheckJson,
            exp.CheckXml,
            exp.Collate,
            exp.Collation,
            exp.CurrentAccount,
            exp.CurrentAccountName,
            exp.CurrentAvailableRoles,
            exp.CurrentClient,
            exp.CurrentDatabase,
            exp.CurrentIpAddress,
            exp.CurrentSchemas,
            exp.CurrentSecondaryRoles,
            exp.CurrentSession,
            exp.CurrentStatement,
            exp.CurrentTransaction,
            exp.CurrentWarehouse,
            exp.CurrentOrganizationUser,
            exp.CurrentRegion,
            exp.CurrentRole,
            exp.CurrentRoleType,
            exp.CurrentOrganizationName,
            exp.DecompressString,
            exp.HexDecodeString,
            exp.HexEncode,
            exp.Randstr,
            exp.RegexpExtract,
            exp.RegexpReplace,
            exp.Repeat,
            exp.Replace,
            exp.Soundex,
            exp.SoundexP123,
            exp.SplitPart,
            exp.Strtok,
            exp.TryBase64DecodeString,
            exp.TryHexDecodeString,
            exp.Uuid,
        }
    },
    **{
        expr_type: {"returns": exp.DType.VARIANT}
        for expr_type in {
            exp.Minhash,
            exp.MinhashCombine,
        }
    },
    **{
        expr_type: {"annotator": _annotate_variance}
        for expr_type in (
            exp.Variance,
            exp.VariancePop,
        )
    },
    exp.ArgMax: {"annotator": _annotate_arg_max_min},
    exp.ArgMin: {"annotator": _annotate_arg_max_min},
    exp.ConcatWs: {"annotator": lambda self, e: self._annotate_by_args(e, "expressions")},
    exp.ConvertTimezone: {
        "annotator": lambda self, e: self._set_type(
            e,
            exp.DType.TIMESTAMPNTZ if e.args.get("source_tz") else exp.DType.TIMESTAMPTZ,
        )
    },
    exp.DateAdd: {"annotator": _annotate_date_or_time_add},
    exp.DecodeCase: {"annotator": _annotate_decode_case},
    exp.HashAgg: {
        "annotator": lambda self, e: self._set_type(
            e, exp.DataType.build("NUMBER(19, 0)", dialect="snowflake")
        )
    },
    exp.Median: {"annotator": _annotate_median},
    exp.Reverse: {"annotator": _annotate_reverse},
    exp.StrToTime: {"annotator": _annotate_str_to_time},
    exp.TimeAdd: {"annotator": _annotate_date_or_time_add},
    exp.TimestampFromParts: {"annotator": _annotate_timestamp_from_parts},
    exp.WithinGroup: {"annotator": _annotate_within_group},
}
