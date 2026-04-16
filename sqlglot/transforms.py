from __future__ import annotations

import typing as t

from sqlglot import expressions as exp
from sqlglot.errors import UnsupportedError
from sqlglot.helper import find_new_name, name_sequence, seq_get


if t.TYPE_CHECKING:
    from sqlglot._typing import E
    from sqlglot.generator import Generator


def preprocess(
    transforms: list[t.Callable[[exp.Expr], exp.Expr]],
    generator: t.Callable[[Generator, exp.Expr], str] | None = None,
) -> t.Callable[[Generator, exp.Expr], str]:
    """
    Creates a new transform by chaining a sequence of transformations and converts the resulting
    expression to SQL, using either the "_sql" method corresponding to the resulting expression,
    or the appropriate `Generator.TRANSFORMS` function (when applicable -- see below).

    Args:
        transforms: sequence of transform functions. These will be called in order.

    Returns:
        Function that can be used as a generator transform.
    """

    def _to_sql(self, expression: exp.Expr) -> str:
        pass

    return _to_sql


def unnest_generate_date_array_using_recursive_cte(expression: exp.Expr) -> exp.Expr:
    pass


def unnest_generate_series(expression: exp.Expr) -> exp.Expr:
    """Unnests GENERATE_SERIES or SEQUENCE table references."""
    pass


def eliminate_distinct_on(expression: exp.Expr) -> exp.Expr:
    """
    Convert SELECT DISTINCT ON statements to a subquery with a window function.

    This is useful for dialects that don't support SELECT DISTINCT ON but support window functions.

    Args:
        expression: the expression that will be transformed.

    Returns:
        The transformed expression.
    """
    if (
        isinstance(expression, exp.Select)
        and expression.args.get("distinct")
        and isinstance(expression.args["distinct"].args.get("on"), exp.Tuple)
    ):
        row_number_window_alias = find_new_name(expression.named_selects, "_row_number")

        distinct_cols = expression.args["distinct"].pop().args["on"].expressions
        window = exp.Window(this=exp.RowNumber(), partition_by=distinct_cols)

        order = expression.args.get("order")
        if order:
            window.set("order", order.pop())
        else:
            window.set("order", exp.Order(expressions=[c.copy() for c in distinct_cols]))

        expression.select(exp.alias_(window, row_number_window_alias), copy=False)

        # We add aliases to the projections so that we can safely reference them in the outer query
        new_selects = []
        taken_names = {row_number_window_alias}
        for select in expression.selects[:-1]:
            if select.is_star:
                new_selects = [exp.Star()]
                break

            if not isinstance(select, exp.Alias):
                alias = find_new_name(taken_names, select.output_name or "_col")
                quoted = select.this.args.get("quoted") if isinstance(select, exp.Column) else None
                select = select.replace(exp.alias_(select, alias, quoted=quoted))

            taken_names.add(select.output_name)
            new_selects.append(select.args["alias"])

        return (
            exp.select(*new_selects, copy=False)
            .from_(expression.subquery("_t", copy=False), copy=False)
            .where(exp.column(row_number_window_alias).eq(1), copy=False)
        )

    return expression


def eliminate_qualify(expression: exp.Expr) -> exp.Expr:
    """
    Convert SELECT statements that contain the QUALIFY clause into subqueries, filtered equivalently.

    The idea behind this transformation can be seen in Snowflake's documentation for QUALIFY:
    https://docs.snowflake.com/en/sql-reference/constructs/qualify

    Some dialects don't support window functions in the WHERE clause, so we need to include them as
    projections in the subquery, in order to refer to them in the outer filter using aliases. Also,
    if a column is referenced in the QUALIFY clause but is not selected, we need to include it too,
    otherwise we won't be able to refer to it in the outer query's WHERE clause. Finally, if a
    newly aliased projection is referenced in the QUALIFY clause, it will be replaced by the
    corresponding expression to avoid creating invalid column references.
    """
    if isinstance(expression, exp.Select) and expression.args.get("qualify"):
        taken = set(expression.named_selects)
        for select in expression.selects:
            if not select.alias_or_name:
                alias = find_new_name(taken, "_c")
                select.replace(exp.alias_(select, alias))
                taken.add(alias)

        def _select_alias_or_name(select: exp.Expr) -> str | exp.Column:
            pass

        outer_selects = exp.select(*list(map(_select_alias_or_name, expression.selects)))
        qualify_filters = expression.args["qualify"].pop().this
        expression_by_alias = {
            select.alias: select.this
            for select in expression.selects
            if isinstance(select, exp.Alias)
        }

        select_candidates = exp.Window if expression.is_star else (exp.Window, exp.Column)
        for select_candidate in list(qualify_filters.find_all(select_candidates)):
            if isinstance(select_candidate, exp.Window):
                if expression_by_alias:
                    for column in select_candidate.find_all(exp.Column):
                        expr = expression_by_alias.get(column.name)
                        if expr:
                            column.replace(expr)

                alias = find_new_name(expression.named_selects, "_w")
                expression.select(exp.alias_(select_candidate, alias), copy=False)
                column = exp.column(alias)

                if isinstance(select_candidate.parent, exp.Qualify):
                    qualify_filters = column
                else:
                    select_candidate.replace(column)
            elif select_candidate.name not in expression.named_selects:
                expression.select(select_candidate.copy(), copy=False)

        return outer_selects.from_(expression.subquery(alias="_t", copy=False), copy=False).where(
            qualify_filters, copy=False
        )

    return expression


def remove_precision_parameterized_types(expression: exp.Expr) -> exp.Expr:
    """
    Some dialects only allow the precision for parameterized types to be defined in the DDL and not in
    other expressions. This transforms removes the precision from parameterized types in expressions.
    """
    for node in expression.find_all(exp.DataType):
        node.set(
            "expressions", [e for e in node.expressions if not isinstance(e, exp.DataTypeParam)]
        )

    return expression


def unqualify_unnest(expression: exp.Expr) -> exp.Expr:
    """Remove references to unnest table aliases, added by the optimizer's qualify_columns step."""
    pass


def unnest_to_explode(
    expression: exp.Expr,
    unnest_using_arrays_zip: bool = True,
) -> exp.Expr:
    """Convert cross join unnest into lateral view explode."""
    pass


def explode_projection_to_unnest(
    index_offset: int = 0,
) -> t.Callable[[exp.Expr], exp.Expr]:
    """Convert explode/posexplode projections into unnests."""

    def _explode_projection_to_unnest(expression: exp.Expr) -> exp.Expr:
        pass

    return _explode_projection_to_unnest


def add_within_group_for_percentiles(expression: exp.Expr) -> exp.Expr:
    """Transforms percentiles by adding a WITHIN GROUP clause to them."""
    pass


def remove_within_group_for_percentiles(expression: exp.Expr) -> exp.Expr:
    """Transforms percentiles by getting rid of their corresponding WITHIN GROUP clause."""
    pass


def add_recursive_cte_column_names(expression: exp.Expr) -> exp.Expr:
    """Uses projection output names in recursive CTE definitions to define the CTEs' columns."""
    pass


def epoch_cast_to_ts(expression: exp.Expr) -> exp.Expr:
    """Replace 'epoch' in casts by the equivalent date literal."""
    pass


def eliminate_semi_and_anti_joins(expression: exp.Expr) -> exp.Expr:
    """Convert SEMI and ANTI joins into equivalent forms that use EXIST instead."""
    if isinstance(expression, exp.Select):
        for join in list(expression.args.get("joins") or []):
            on = join.args.get("on")
            if on and join.kind in ("SEMI", "ANTI"):
                subquery = exp.select("1").from_(join.this).where(on)
                exists: exp.Exists | exp.Not = exp.Exists(this=subquery)
                if join.kind == "ANTI":
                    exists = exists.not_(copy=False)

                join.pop()
                expression.where(exists, copy=False)

    return expression


def eliminate_full_outer_join(expression: exp.Expr) -> exp.Expr:
    """
    Converts a query with a FULL OUTER join to a union of identical queries that
    use LEFT/RIGHT OUTER joins instead. This transformation currently only works
    for queries that have a single FULL OUTER join.
    """
    pass


def move_ctes_to_top_level(expression: E) -> E:
    """
    Some dialects (e.g. Hive, T-SQL, Spark prior to version 3) only allow CTEs to be
    defined at the top-level, so for example queries like:

        SELECT * FROM (WITH t(c) AS (SELECT 1) SELECT * FROM t) AS subq

    are invalid in those dialects. This transformation can be used to ensure all CTEs are
    moved to the top level so that the final SQL code is valid from a syntax standpoint.

    TODO: handle name clashes whilst moving CTEs (it can get quite tricky & costly).
    """
    top_level_with = expression.args.get("with_")
    for inner_with in expression.find_all(exp.With):
        if inner_with.parent is expression:
            continue

        if not top_level_with:
            top_level_with = inner_with.pop()
            expression.set("with_", top_level_with)
        else:
            if inner_with.recursive:
                top_level_with.set("recursive", True)

            parent_cte = inner_with.find_ancestor(exp.CTE)
            inner_with.pop()

            if parent_cte:
                i = top_level_with.expressions.index(parent_cte)
                top_level_with.expressions[i:i] = inner_with.expressions
                top_level_with.set("expressions", top_level_with.expressions)
            else:
                top_level_with.set(
                    "expressions", top_level_with.expressions + inner_with.expressions
                )

    return expression


def ensure_bools(expression: exp.Expr) -> exp.Expr:
    """Converts numeric values used in conditions into explicit boolean expressions."""
    from sqlglot.optimizer.canonicalize import ensure_bools

    def _ensure_bool(node: exp.Expr) -> None:
        pass

    for node in expression.walk():
        ensure_bools(node, _ensure_bool)

    return expression


def unqualify_columns(expression: exp.Expr) -> exp.Expr:
    for column in expression.find_all(exp.Column):
        # We only wanna pop off the table, db, catalog args
        for part in column.parts[:-1]:
            part.pop()

    return expression


def remove_unique_constraints(expression: exp.Expr) -> exp.Expr:
    assert isinstance(expression, exp.Create)
    for constraint in expression.find_all(exp.UniqueColumnConstraint):
        if constraint.parent:
            constraint.parent.pop()

    return expression


def ctas_with_tmp_tables_to_create_tmp_view(
    expression: exp.Expr,
    tmp_storage_provider: t.Callable[[exp.Expr], exp.Expr] = lambda e: e,
) -> exp.Expr:
    assert isinstance(expression, exp.Create)
    properties = expression.args.get("properties")
    temporary = any(
        isinstance(prop, exp.TemporaryProperty)
        for prop in (properties.expressions if properties else [])
    )

    # CTAS with temp tables map to CREATE TEMPORARY VIEW
    if expression.kind == "TABLE" and temporary:
        if expression.expression:
            return exp.Create(
                kind="TEMPORARY VIEW",
                this=expression.this,
                expression=expression.expression,
            )
        return tmp_storage_provider(expression)

    return expression


def move_schema_columns_to_partitioned_by(expression: exp.Expr) -> exp.Expr:
    """
    In Hive, the PARTITIONED BY property acts as an extension of a table's schema. When the
    PARTITIONED BY value is an array of column names, they are transformed into a schema.
    The corresponding columns are removed from the create statement.
    """
    assert isinstance(expression, exp.Create)
    has_schema = isinstance(expression.this, exp.Schema)
    is_partitionable = expression.kind in {"TABLE", "VIEW"}

    if has_schema and is_partitionable:
        prop = expression.find(exp.PartitionedByProperty)
        if prop and prop.this and not isinstance(prop.this, exp.Schema):
            schema = expression.this
            columns = {v.name.upper() for v in prop.this.expressions}
            partitions = [col for col in schema.expressions if col.name.upper() in columns]
            schema.set("expressions", [e for e in schema.expressions if e not in partitions])
            prop.replace(exp.PartitionedByProperty(this=exp.Schema(expressions=partitions)))
            expression.set("this", schema)

    return expression


def move_partitioned_by_to_schema_columns(expression: exp.Expr) -> exp.Expr:
    """
    Spark 3 supports both "HIVEFORMAT" and "DATASOURCE" formats for CREATE TABLE.

    Currently, SQLGlot uses the DATASOURCE format for Spark 3.
    """
    assert isinstance(expression, exp.Create)
    prop = expression.find(exp.PartitionedByProperty)
    if (
        prop
        and prop.this
        and isinstance(prop.this, exp.Schema)
        and all(isinstance(e, exp.ColumnDef) and e.kind for e in prop.this.expressions)
    ):
        prop_this = exp.Tuple(
            expressions=[exp.to_identifier(e.this) for e in prop.this.expressions]
        )
        schema = expression.this
        for e in prop.this.expressions:
            schema.append("expressions", e)
        prop.set("this", prop_this)

    return expression


def struct_kv_to_alias(expression: exp.Expr) -> exp.Expr:
    """Converts struct arguments to aliases, e.g. STRUCT(1 AS y)."""
    pass


def eliminate_join_marks(expression: exp.Expr) -> exp.Expr:
    """https://docs.oracle.com/cd/B19306_01/server.102/b14200/queries006.htm#sthref3178

    1. You cannot specify the (+) operator in a query block that also contains FROM clause join syntax.

    2. The (+) operator can appear only in the WHERE clause or, in the context of left-correlation (that is, when specifying the TABLE clause) in the FROM clause, and can be applied only to a column of a table or view.

    The (+) operator does not produce an outer join if you specify one table in the outer query and the other table in an inner query.

    You cannot use the (+) operator to outer-join a table to itself, although self joins are valid.

    The (+) operator can be applied only to a column, not to an arbitrary expression. However, an arbitrary expression can contain one or more columns marked with the (+) operator.

    A WHERE condition containing the (+) operator cannot be combined with another condition using the OR logical operator.

    A WHERE condition cannot use the IN comparison condition to compare a column marked with the (+) operator with an expression.

    A WHERE condition cannot compare any column marked with the (+) operator with a subquery.

    -- example with WHERE
    SELECT d.department_name, sum(e.salary) as total_salary
    FROM departments d, employees e
    WHERE e.department_id(+) = d.department_id
    group by department_name

    -- example of left correlation in select
    SELECT d.department_name, (
        SELECT SUM(e.salary)
            FROM employees e
            WHERE e.department_id(+) = d.department_id) AS total_salary
    FROM departments d;

    -- example of left correlation in from
    SELECT d.department_name, t.total_salary
    FROM departments d, (
            SELECT SUM(e.salary) AS total_salary
            FROM employees e
            WHERE e.department_id(+) = d.department_id
        ) t
    """

    from sqlglot.optimizer.scope import traverse_scope
    from sqlglot.optimizer.normalize import normalize, normalized
    from collections import defaultdict

    # we go in reverse to check the main query for left correlation
    for scope in reversed(traverse_scope(expression)):
        query = scope.expression

        where = query.args.get("where")
        joins = query.args.get("joins", [])

        if not where or not any(c.args.get("join_mark") for c in where.find_all(exp.Column)):
            continue

        # knockout: we do not support left correlation (see point 2)
        assert not scope.is_correlated_subquery, "Correlated queries are not supported"

        # make sure we have AND of ORs to have clear join terms
        where = normalize(where.this)
        assert normalized(where), "Cannot normalize JOIN predicates"

        joins_ons = defaultdict(list)  # dict of {name: list of join AND conditions}
        for cond in [where] if not isinstance(where, exp.And) else where.flatten():
            join_cols = [col for col in cond.find_all(exp.Column) if col.args.get("join_mark")]

            left_join_table = set(col.table for col in join_cols)
            if not left_join_table:
                continue

            assert not (len(left_join_table) > 1), (
                "Cannot combine JOIN predicates from different tables"
            )

            for col in join_cols:
                col.set("join_mark", False)

            joins_ons[left_join_table.pop()].append(cond)

        old_joins = {join.alias_or_name: join for join in joins}
        new_joins = {}
        query_from = query.args["from_"]

        for table, predicates in joins_ons.items():
            join_what = old_joins.get(table, query_from).this.copy()
            new_joins[join_what.alias_or_name] = exp.Join(
                this=join_what, on=exp.and_(*predicates), kind="LEFT"
            )

            for p in predicates:
                while isinstance(p.parent, exp.Paren):
                    p.parent.replace(p)

                parent = p.parent
                p.pop()
                if isinstance(parent, exp.Binary):
                    left = parent.args.get("this")
                    parent.replace(parent.right if left is None else left)
                elif isinstance(parent, exp.Where):
                    parent.pop()

        if query_from.alias_or_name in new_joins:
            only_old_joins = old_joins.keys() - new_joins.keys()
            assert len(only_old_joins) >= 1, (
                "Cannot determine which table to use in the new FROM clause"
            )

            new_from_name = list(only_old_joins)[0]
            query.set("from_", exp.From(this=old_joins[new_from_name].this))

        if new_joins:
            for n, j in old_joins.items():  # preserve any other joins
                if n not in new_joins and n != query.args["from_"].name:
                    if not j.kind:
                        j.set("kind", "CROSS")
                    new_joins[n] = j
            query.set("joins", list(new_joins.values()))

    return expression


def any_to_exists(expression: exp.Expr) -> exp.Expr:
    """
    Transform ANY operator to Spark's EXISTS

    For example,
        - Postgres: SELECT * FROM tbl WHERE 5 > ANY(tbl.col)
        - Spark: SELECT * FROM tbl WHERE EXISTS(tbl.col, x -> x < 5)

    Both ANY and EXISTS accept queries but currently only array expressions are supported for this
    transformation
    """
    pass


def eliminate_window_clause(expression: exp.Expr) -> exp.Expr:
    """Eliminates the `WINDOW` query clause by inling each named window."""
    if isinstance(expression, exp.Select) and expression.args.get("windows"):
        from sqlglot.optimizer.scope import find_all_in_scope

        windows = expression.args["windows"]
        expression.set("windows", None)

        window_expression: dict[str, exp.Expr] = {}

        def _inline_inherited_window(window: exp.Expr) -> None:
            inherited_window = window_expression.get(window.alias.lower())
            if not inherited_window:
                return

            window.set("alias", None)
            for key in ("partition_by", "order", "spec"):
                arg = inherited_window.args.get(key)
                if arg:
                    window.set(key, arg.copy())

        for window in windows:
            _inline_inherited_window(window)
            window_expression[window.name.lower()] = window

        for window in find_all_in_scope(expression, exp.Window):
            _inline_inherited_window(window)

    return expression


def inherit_struct_field_names(expression: exp.Expr) -> exp.Expr:
    """
    Inherit field names from the first struct in an array.

    BigQuery supports implicitly inheriting names from the first STRUCT in an array:

    Example:
        ARRAY[
          STRUCT('Alice' AS name, 85 AS score),  -- defines names
          STRUCT('Bob', 92),                     -- inherits names
          STRUCT('Diana', 95)                    -- inherits names
        ]

    This transformation makes the field names explicit on all structs by adding
    PropertyEQ nodes, in order to facilitate transpilation to other dialects.

    Args:
        expression: The expression tree to transform

    Returns:
        The modified expression with field names inherited in all structs
    """
    if (
        isinstance(expression, exp.Array)
        and expression.args.get("struct_name_inheritance")
        and isinstance(first_item := seq_get(expression.expressions, 0), exp.Struct)
        and all(isinstance(fld, exp.PropertyEQ) for fld in first_item.expressions)
    ):
        field_names = [fld.this for fld in first_item.expressions]

        # Apply field names to subsequent structs that don't have them
        for struct in expression.expressions[1:]:
            if not isinstance(struct, exp.Struct) or len(struct.expressions) != len(field_names):
                continue

            # Convert unnamed expressions to PropertyEQ with inherited names
            new_expressions = []
            for i, expr in enumerate(struct.expressions):
                if not isinstance(expr, exp.PropertyEQ):
                    # Create PropertyEQ: field_name := value, preserving the type from the inner expression
                    property_eq = exp.PropertyEQ(
                        this=field_names[i].copy(),
                        expression=expr,
                    )
                    property_eq.type = expr.type
                    new_expressions.append(property_eq)
                else:
                    new_expressions.append(expr)

            struct.set("expressions", new_expressions)

    return expression
