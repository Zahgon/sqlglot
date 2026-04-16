from __future__ import annotations

import typing as t

from sqlglot import exp
from sqlglot.typing import EXPRESSION_METADATA, TIMESTAMP_EXPRESSIONS

if t.TYPE_CHECKING:
    from sqlglot.optimizer.annotate_types import TypeAnnotator


def _annotate_math_functions(self: TypeAnnotator, expression: exp.Expr) -> exp.Expr:
    """
    Many BigQuery math functions such as CEIL, FLOOR etc follow this return type convention:
    +---------+---------+---------+------------+---------+
    |  INPUT  | INT64   | NUMERIC | BIGNUMERIC | FLOAT64 |
    +---------+---------+---------+------------+---------+
    |  OUTPUT | FLOAT64 | NUMERIC | BIGNUMERIC | FLOAT64 |
    +---------+---------+---------+------------+---------+
    """
    this: exp.Expr = expression.this

    self._set_type(
        expression,
        exp.DType.DOUBLE if this.is_type(*exp.DataType.INTEGER_TYPES) else this.type,
    )
    return expression


def _annotate_safe_divide(self: TypeAnnotator, expression: exp.SafeDivide) -> exp.Expr:
    """
    +------------+------------+------------+-------------+---------+
    | INPUT      | INT64      | NUMERIC    | BIGNUMERIC  | FLOAT64 |
    +------------+------------+------------+-------------+---------+
    | INT64      | FLOAT64    | NUMERIC    | BIGNUMERIC  | FLOAT64 |
    | NUMERIC    | NUMERIC    | NUMERIC    | BIGNUMERIC  | FLOAT64 |
    | BIGNUMERIC | BIGNUMERIC | BIGNUMERIC | BIGNUMERIC  | FLOAT64 |
    | FLOAT64    | FLOAT64    | FLOAT64    | FLOAT64     | FLOAT64 |
    +------------+------------+------------+-------------+---------+
    """
    if expression.this.is_type(*exp.DataType.INTEGER_TYPES) and expression.expression.is_type(
        *exp.DataType.INTEGER_TYPES
    ):
        return self._set_type(expression, exp.DType.DOUBLE)

    return _annotate_by_args_with_coerce(self, expression)


def _annotate_by_args_with_coerce(self: TypeAnnotator, expression: exp.Expr) -> exp.Expr:
    """
    +------------+------------+------------+-------------+---------+
    | INPUT      | INT64      | NUMERIC    | BIGNUMERIC  | FLOAT64 |
    +------------+------------+------------+-------------+---------+
    | INT64      | INT64      | NUMERIC    | BIGNUMERIC  | FLOAT64 |
    | NUMERIC    | NUMERIC    | NUMERIC    | BIGNUMERIC  | FLOAT64 |
    | BIGNUMERIC | BIGNUMERIC | BIGNUMERIC | BIGNUMERIC  | FLOAT64 |
    | FLOAT64    | FLOAT64    | FLOAT64    | FLOAT64     | FLOAT64 |
    +------------+------------+------------+-------------+---------+
    """
    self._set_type(expression, self._maybe_coerce(expression.this.type, expression.expression.type))
    return expression


def _annotate_by_args_approx_top(self: TypeAnnotator, expression: exp.ApproxTopK) -> exp.ApproxTopK:
    struct_type = exp.DataType(
        this=exp.DType.STRUCT,
        expressions=[expression.this.type, exp.DataType(this=exp.DType.BIGINT)],
        nested=True,
    )
    self._set_type(
        expression,
        exp.DataType(this=exp.DType.ARRAY, expressions=[struct_type], nested=True),
    )

    return expression


def _annotate_concat(self: TypeAnnotator, expression: exp.Concat) -> exp.Concat:
    pass


def _annotate_array(self: TypeAnnotator, expression: exp.Array) -> exp.Array:
    pass


EXPRESSION_METADATA = {
    **EXPRESSION_METADATA,
    **{
        expr_type: {"annotator": lambda self, e: _annotate_math_functions(self, e)}
        for expr_type in {
            exp.Avg,
            exp.Ceil,
            exp.Exp,
            exp.Floor,
            exp.Ln,
            exp.Log,
            exp.Round,
            exp.Sqrt,
        }
    },
    **{
        expr_type: {"annotator": lambda self, e: self._annotate_by_args(e, "this")}
        for expr_type in {
            exp.ArgMax,
            exp.ArgMin,
            exp.DateAdd,
            exp.DateTrunc,
            exp.DatetimeTrunc,
            exp.FirstValue,
            exp.GroupConcat,
            exp.IgnoreNulls,
            exp.JSONExtract,
            exp.Lead,
            exp.Left,
            exp.Lower,
            exp.NetFunc,
            exp.NthValue,
            exp.Pad,
            exp.PercentileDisc,
            exp.RegexpExtract,
            exp.RegexpReplace,
            exp.Repeat,
            exp.Replace,
            exp.RespectNulls,
            exp.Reverse,
            exp.Right,
            exp.SafeFunc,
            exp.SafeNegate,
            exp.Sign,
            exp.Substring,
            exp.TimestampTrunc,
            exp.Translate,
            exp.Trim,
            exp.Upper,
        }
    },
    **{
        expr_type: {"returns": exp.DType.BIGINT}
        for expr_type in {
            exp.BitwiseAndAgg,
            exp.BitwiseCount,
            exp.BitwiseOrAgg,
            exp.BitwiseXorAgg,
            exp.ByteLength,
            exp.DenseRank,
            exp.FarmFingerprint,
            exp.Grouping,
            exp.LaxInt64,
            exp.Length,
            exp.Ntile,
            exp.Rank,
            exp.RangeBucket,
            exp.RegexpInstr,
            exp.RowNumber,
            exp.UnixDate,
        }
    },
    **{
        expr_type: {"returns": exp.DType.BINARY}
        for expr_type in {
            exp.ByteString,
            exp.CodePointsToBytes,
            exp.MD5Digest,
            exp.SHA,
            exp.SHA2,
            exp.SHA1Digest,
            exp.SHA2Digest,
            exp.Unhex,
        }
    },
    **{
        expr_type: {"returns": exp.DType.BOOLEAN}
        for expr_type in {
            exp.JSONBool,
            exp.LaxBool,
        }
    },
    **{
        expr_type: {"returns": exp.DType.DATETIME}
        for expr_type in {
            exp.ParseDatetime,
            exp.TimestampFromParts,
        }
    },
    **{
        expr_type: {"returns": exp.DType.DOUBLE}
        for expr_type in {
            exp.Atan2,
            exp.Corr,
            exp.CosineDistance,
            exp.Coth,
            exp.CovarPop,
            exp.CovarSamp,
            exp.Csc,
            exp.Csch,
            exp.CumeDist,
            exp.EuclideanDistance,
            exp.Float64,
            exp.LaxFloat64,
            exp.PercentRank,
            exp.Sec,
            exp.Sech,
        }
    },
    **{
        expr_type: {"returns": exp.DType.JSON}
        for expr_type in {
            exp.JSONArray,
            exp.JSONArrayAppend,
            exp.JSONArrayInsert,
            exp.JSONObject,
            exp.JSONRemove,
            exp.JSONSet,
            exp.JSONStripNulls,
        }
    },
    **{
        expr_type: {"returns": exp.DType.TIME}
        for expr_type in {
            exp.ParseTime,
            exp.TimeFromParts,
            exp.TimeTrunc,
            exp.TsOrDsToTime,
        }
    },
    **{
        expr_type: {"returns": exp.DType.VARCHAR}
        for expr_type in {
            exp.CodePointsToString,
            exp.Format,
            exp.Host,
            exp.JSONExtractScalar,
            exp.JSONType,
            exp.LaxString,
            exp.LowerHex,
            exp.Normalize,
            exp.RegDomain,
            exp.SafeConvertBytesToString,
            exp.Soundex,
            exp.Uuid,
        }
    },
    **{
        expr_type: {"annotator": lambda self, e: _annotate_by_args_with_coerce(self, e)}
        for expr_type in {
            exp.PercentileCont,
            exp.SafeAdd,
            exp.SafeDivide,
            exp.SafeMultiply,
            exp.SafeSubtract,
        }
    },
    **{
        expr_type: {"annotator": lambda self, e: self._annotate_by_args(e, "this", array=True)}
        for expr_type in {
            exp.ApproxQuantiles,
            exp.JSONExtractArray,
            exp.RegexpExtractAll,
            exp.Split,
        }
    },
    **{expr_type: {"returns": exp.DType.TIMESTAMPTZ} for expr_type in TIMESTAMP_EXPRESSIONS},
    exp.ApproxTopK: {"annotator": lambda self, e: _annotate_by_args_approx_top(self, e)},
    exp.ApproxTopSum: {"annotator": lambda self, e: _annotate_by_args_approx_top(self, e)},
    exp.Array: {"annotator": _annotate_array},
    exp.Concat: {"annotator": _annotate_concat},
    exp.DateFromUnixDate: {"returns": exp.DType.DATE},
    exp.GenerateTimestampArray: {
        "annotator": lambda self, e: self._set_type(
            e, exp.DataType.build("ARRAY<TIMESTAMP>", dialect="bigquery")
        )
    },
    exp.JSONFormat: {
        "annotator": lambda self, e: self._set_type(
            e, exp.DType.JSON if e.args.get("to_json") else exp.DType.VARCHAR
        )
    },
    exp.JSONKeysAtDepth: {
        "annotator": lambda self, e: self._set_type(
            e, exp.DataType.build("ARRAY<VARCHAR>", dialect="bigquery")
        )
    },
    exp.JSONValueArray: {
        "annotator": lambda self, e: self._set_type(
            e, exp.DataType.build("ARRAY<VARCHAR>", dialect="bigquery")
        )
    },
    exp.Lag: {"annotator": lambda self, e: self._annotate_by_args(e, "this", "default")},
    exp.ParseBignumeric: {"returns": exp.DType.BIGDECIMAL},
    exp.ParseNumeric: {"returns": exp.DType.DECIMAL},
    exp.SafeDivide: {"annotator": lambda self, e: _annotate_safe_divide(self, e)},
    exp.ToCodePoints: {
        "annotator": lambda self, e: self._set_type(
            e, exp.DataType.build("ARRAY<BIGINT>", dialect="bigquery")
        )
    },
}
