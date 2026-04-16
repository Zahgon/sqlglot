from __future__ import annotations

import abc
import typing as t

from sqlglot import expressions as exp
from sqlglot.dialects.dialect import Dialect
from sqlglot.errors import SchemaError
from sqlglot.helper import dict_depth, first
from sqlglot.trie import TrieResult, in_trie, new_trie

from sqlglot.helper import trait


if t.TYPE_CHECKING:
    from sqlglot._typing import SchemaArgs
    from sqlglot.dialects.dialect import DialectType
    from collections.abc import Sequence
    from typing_extensions import Unpack

    ColumnMapping = t.Union[dict, str, list]


@trait
class Schema(abc.ABC):
    """Abstract base class for database schemas"""

    @property
    def dialect(self) -> Dialect | None:
        """
        Returns None by default. Subclasses that require dialect-specific
        behavior should override this property.
        """
        return None

    @abc.abstractmethod
    def add_table(
        self,
        table: exp.Table | str,
        column_mapping: ColumnMapping | None = None,
        dialect: DialectType = None,
        normalize: bool | None = None,
        match_depth: bool = True,
    ) -> None:
        """
        Register or update a table. Some implementing classes may require column information to also be provided.
        The added table must have the necessary number of qualifiers in its path to match the schema's nesting level.

        Args:
            table: the `Table` expression instance or string representing the table.
            column_mapping: a column mapping that describes the structure of the table.
            dialect: the SQL dialect that will be used to parse `table` if it's a string.
            normalize: whether to normalize identifiers according to the dialect of interest.
            match_depth: whether to enforce that the table must match the schema's depth or not.
        """

    @abc.abstractmethod
    def column_names(
        self,
        table: exp.Table | str,
        only_visible: bool = False,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> Sequence[str]:
        """
        Get the column names for a table.

        Args:
            table: the `Table` expression instance.
            only_visible: whether to include invisible columns.
            dialect: the SQL dialect that will be used to parse `table` if it's a string.
            normalize: whether to normalize identifiers according to the dialect of interest.

        Returns:
            The sequence of column names.
        """

    @abc.abstractmethod
    def get_column_type(
        self,
        table: exp.Table | str,
        column: exp.Column | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> exp.DataType:
        """
        Get the `sqlglot.exp.DataType` type of a column in the schema.

        Args:
            table: the source table.
            column: the target column.
            dialect: the SQL dialect that will be used to parse `table` if it's a string.
            normalize: whether to normalize identifiers according to the dialect of interest.

        Returns:
            The resulting column type.
        """

    def has_column(
        self,
        table: exp.Table | str,
        column: exp.Column | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> bool:
        """
        Returns whether `column` appears in `table`'s schema.

        Args:
            table: the source table.
            column: the target column.
            dialect: the SQL dialect that will be used to parse `table` if it's a string.
            normalize: whether to normalize identifiers according to the dialect of interest.

        Returns:
            True if the column appears in the schema, False otherwise.
        """
        pass

    def get_udf_type(
        self,
        udf: exp.Anonymous | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> exp.DataType:
        """
        Get the return type of a UDF.

        Args:
            udf: the UDF expression or string.
            dialect: the SQL dialect for parsing string arguments.
            normalize: whether to normalize identifiers.

        Returns:
            The return type as a DataType, or UNKNOWN if not found.
        """
        return exp.DType.UNKNOWN.into_expr()

    @property
    @abc.abstractmethod
    def supported_table_args(self) -> tuple[str, ...]:
        """
        Table arguments this schema support, e.g. `("this", "db", "catalog")`
        """

    @property
    def empty(self) -> bool:
        """Returns whether the schema is empty."""
        pass


class AbstractMappingSchema:
    def __init__(
        self,
        mapping: dict[str, object] | None = None,
        udf_mapping: dict[str, object] | None = None,
    ) -> None:
        self.mapping: dict[str, object] = mapping or {}
        self.mapping_trie: dict[str, object] = new_trie(
            tuple(reversed(t)) for t in flatten_schema(self.mapping, depth=self.depth())
        )
        self.udf_mapping: dict[str, object] = udf_mapping or {}
        self.udf_trie: dict[str, object] = new_trie(
            tuple(reversed(t)) for t in flatten_schema(self.udf_mapping, depth=self.udf_depth())
        )

        self._supported_table_args: tuple[str, ...] = tuple()

    @property
    def empty(self) -> bool:
        pass

    def depth(self) -> int:
        pass

    def udf_depth(self) -> int:
        return dict_depth(self.udf_mapping)

    @property
    def supported_table_args(self) -> tuple[str, ...]:
        pass

    def table_parts(self, table: exp.Table) -> list[str]:
        return [p.name for p in reversed(table.parts)]

    def udf_parts(self, udf: exp.Anonymous) -> list[str]:
        # a.b.c(...) is represented as Dot(Dot(a, b), Anonymous(c, ...))
        parent = udf.parent
        parts = [p.name for p in parent.flatten()] if isinstance(parent, exp.Dot) else [udf.name]
        return list(reversed(parts))[0 : self.udf_depth()]

    def _find_in_trie(
        self,
        parts: list[str],
        trie: dict[str, object],
        raise_on_missing: bool,
    ) -> list[str] | None:
        value, trie = in_trie(trie, parts)

        if value == TrieResult.FAILED:
            return None

        if value == TrieResult.PREFIX:
            possibilities = flatten_schema(trie)

            if len(possibilities) == 1:
                parts.extend(possibilities[0])
            else:
                if raise_on_missing:
                    joined_parts = ".".join(parts)
                    message = ", ".join(".".join(p) for p in possibilities)
                    raise SchemaError(f"Ambiguous mapping for {joined_parts}: {message}.")

                return None

        return parts

    def find(
        self, table: exp.Table, raise_on_missing: bool = True, ensure_data_types: bool = False
    ) -> t.Any | None:
        """
        Returns the schema of a given table.

        Args:
            table: the target table.
            raise_on_missing: whether to raise in case the schema is not found.
            ensure_data_types: whether to convert `str` types to their `DataType` equivalents.

        Returns:
            The schema of the target table.
        """
        parts = self.table_parts(table)[0 : len(self.supported_table_args)]
        resolved_parts = self._find_in_trie(parts, self.mapping_trie, raise_on_missing)

        if resolved_parts is None:
            return None

        return self.nested_get(resolved_parts, raise_on_missing=raise_on_missing)

    def find_udf(self, udf: exp.Anonymous, raise_on_missing: bool = False) -> t.Any | None:
        """
        Returns the return type of a given UDF.

        Args:
            udf: the target UDF expression.
            raise_on_missing: whether to raise if the UDF is not found.

        Returns:
            The return type of the UDF, or None if not found.
        """
        pass

    def nested_get(
        self,
        parts: Sequence[str],
        d: dict[str, object] | None = None,
        raise_on_missing: bool = True,
    ) -> t.Any | None:
        return nested_get(
            d or self.mapping,
            *zip(self.supported_table_args, reversed(parts)),
            raise_on_missing=raise_on_missing,
        )


class MappingSchema(AbstractMappingSchema, Schema):
    """
    Schema based on a nested mapping.

    Args:
        schema: Mapping in one of the following forms:
            1. {table: {col: type}}
            2. {db: {table: {col: type}}}
            3. {catalog: {db: {table: {col: type}}}}
            4. None - Tables will be added later
        visible: Optional mapping of which columns in the schema are visible. If not provided, all columns
            are assumed to be visible. The nesting should mirror that of the schema:
            1. {table: set(*cols)}}
            2. {db: {table: set(*cols)}}}
            3. {catalog: {db: {table: set(*cols)}}}}
        dialect: The dialect to be used for custom type mappings & parsing string arguments.
        normalize: Whether to normalize identifier names according to the given dialect or not.
    """

    def __init__(
        self,
        schema: dict[str, object] | None = None,
        visible: dict[str, object] | None = None,
        dialect: DialectType = None,
        normalize: bool = True,
        udf_mapping: dict[str, object] | None = None,
    ) -> None:
        self.visible: dict[str, object] = {} if visible is None else visible
        self.normalize: bool = normalize
        self._dialect: Dialect = Dialect.get_or_raise(dialect)
        self._type_mapping_cache: dict[str, exp.DataType] = {}
        self._normalized_table_cache: dict[tuple[exp.Table, DialectType, bool], exp.Table] = {}
        self._normalized_name_cache: dict[tuple[str, DialectType, bool, bool], str] = {}
        self._depth: int = 0
        schema = {} if schema is None else schema
        udf_mapping = {} if udf_mapping is None else udf_mapping

        super().__init__(
            self._normalize(schema) if self.normalize else schema,
            self._normalize_udfs(udf_mapping) if self.normalize else udf_mapping,
        )

    @property
    def dialect(self) -> Dialect:
        """Returns the dialect for this mapping schema."""
        return self._dialect

    @classmethod
    def from_mapping_schema(cls, mapping_schema: MappingSchema) -> MappingSchema:
        pass

    def find(
        self, table: exp.Table, raise_on_missing: bool = True, ensure_data_types: bool = False
    ) -> t.Any | None:
        schema = super().find(
            table, raise_on_missing=raise_on_missing, ensure_data_types=ensure_data_types
        )
        if ensure_data_types and isinstance(schema, dict):
            schema = {
                col: self._to_data_type(dtype) if isinstance(dtype, str) else dtype
                for col, dtype in schema.items()
            }

        return schema

    def copy(
        self, schema: dict[str, object] | None = None, **kwargs: Unpack[SchemaArgs]
    ) -> MappingSchema:
        mapping_kwargs: SchemaArgs = {
            "visible": self.visible.copy(),
            "dialect": self.dialect,
            "normalize": self.normalize,
            "udf_mapping": self.udf_mapping.copy(),
            **kwargs,
        }
        return MappingSchema(self.mapping.copy() if schema is None else schema, **mapping_kwargs)

    def add_table(
        self,
        table: exp.Table | str,
        column_mapping: ColumnMapping | None = None,
        dialect: DialectType = None,
        normalize: bool | None = None,
        match_depth: bool = True,
    ) -> None:
        """
        Register or update a table. Updates are only performed if a new column mapping is provided.
        The added table must have the necessary number of qualifiers in its path to match the schema's nesting level.

        Args:
            table: the `Table` expression instance or string representing the table.
            column_mapping: a column mapping that describes the structure of the table.
            dialect: the SQL dialect that will be used to parse `table` if it's a string.
            normalize: whether to normalize identifiers according to the dialect of interest.
            match_depth: whether to enforce that the table must match the schema's depth or not.
        """
        pass

    def column_names(
        self,
        table: exp.Table | str,
        only_visible: bool = False,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> list[str]:
        normalized_table = self._normalize_table(table, dialect=dialect, normalize=normalize)

        schema = self.find(normalized_table)
        if schema is None:
            return []

        if not only_visible or not self.visible:
            return list(schema)

        visible = self.nested_get(self.table_parts(normalized_table), self.visible) or []
        return [col for col in schema if col in visible]

    def get_column_type(
        self,
        table: exp.Table | str,
        column: exp.Column | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> exp.DataType:
        normalized_table = self._normalize_table(table, dialect=dialect, normalize=normalize)

        normalized_column_name = self._normalize_name(
            column if isinstance(column, str) else column.this, dialect=dialect, normalize=normalize
        )

        table_schema = self.find(normalized_table, raise_on_missing=False)
        if table_schema:
            column_type = table_schema.get(normalized_column_name)

            if isinstance(column_type, exp.DataType):
                return column_type
            elif isinstance(column_type, str):
                return self._to_data_type(column_type, dialect=dialect)

        return exp.DType.UNKNOWN.into_expr()

    def get_udf_type(
        self,
        udf: exp.Anonymous | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> exp.DataType:
        """
        Get the return type of a UDF.

        Args:
            udf: the UDF expression or string (e.g., "db.my_func()").
            dialect: the SQL dialect for parsing string arguments.
            normalize: whether to normalize identifiers.

        Returns:
            The return type as a DataType, or UNKNOWN if not found.
        """
        parts = self._normalize_udf(udf, dialect=dialect, normalize=normalize)
        resolved_parts = self._find_in_trie(parts, self.udf_trie, raise_on_missing=False)

        if resolved_parts is None:
            return exp.DType.UNKNOWN.into_expr()

        udf_type = nested_get(
            self.udf_mapping,
            *zip(resolved_parts, reversed(resolved_parts)),
            raise_on_missing=False,
        )

        if isinstance(udf_type, exp.DataType):
            return udf_type
        elif isinstance(udf_type, str):
            return self._to_data_type(udf_type, dialect=dialect)

        return exp.DType.UNKNOWN.into_expr()

    def has_column(
        self,
        table: exp.Table | str,
        column: exp.Column | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> bool:
        pass

    def _normalize(self, schema: dict[str, object]) -> dict[str, object]:
        """
        Normalizes all identifiers in the schema.

        Args:
            schema: the schema to normalize.

        Returns:
            The normalized schema mapping.
        """
        pass

    def _normalize_udfs(self, udfs: dict[str, object]) -> dict[str, object]:
        """
        Normalizes all identifiers in the UDF mapping.

        Args:
            udfs: the UDF mapping to normalize.

        Returns:
            The normalized UDF mapping.
        """
        pass

    def _normalize_udf(
        self,
        udf: exp.Anonymous | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> list[str]:
        """
        Extract and normalize UDF parts for lookup.

        Args:
            udf: the UDF expression or qualified string (e.g., "db.my_func()").
            dialect: the SQL dialect for parsing.
            normalize: whether to normalize identifiers.

        Returns:
            A list of normalized UDF parts (reversed for trie lookup).
        """
        dialect = dialect or self.dialect
        normalize = self.normalize if normalize is None else normalize

        if isinstance(udf, str):
            parsed: exp.Expr = exp.maybe_parse(udf, dialect=dialect)

            if isinstance(parsed, exp.Anonymous):
                udf = parsed
            elif isinstance(parsed, exp.Dot) and isinstance(parsed.expression, exp.Anonymous):
                udf = parsed.expression
            else:
                raise SchemaError(f"Unable to parse UDF from: {udf!r}")
        parts = self.udf_parts(udf)

        if normalize:
            parts = [self._normalize_name(part, dialect=dialect, is_table=True) for part in parts]

        return parts

    def _normalize_table(
        self,
        table: exp.Table | str,
        dialect: DialectType = None,
        normalize: bool | None = None,
    ) -> exp.Table:
        dialect = dialect or self.dialect
        normalize = self.normalize if normalize is None else normalize

        # Cache normalized tables by object id for exp.Table inputs
        # This is effective when the same Table object is looked up multiple times
        if isinstance(table, exp.Table) and (
            cached := self._normalized_table_cache.get((table, dialect, normalize))
        ):
            return cached

        normalized_table = exp.maybe_parse(table, into=exp.Table, dialect=dialect, copy=normalize)

        if normalize:
            for part in normalized_table.parts:
                if isinstance(part, exp.Identifier):
                    part.replace(
                        normalize_name(part, dialect=dialect, is_table=True, normalize=normalize)
                    )

        self._normalized_table_cache[(normalized_table, dialect, normalize)] = normalized_table
        return normalized_table

    def _normalize_name(
        self,
        name: str | exp.Identifier,
        dialect: DialectType = None,
        is_table: bool = False,
        normalize: bool | None = None,
    ) -> str:
        normalize = self.normalize if normalize is None else normalize

        dialect = dialect or self.dialect
        name_str = name if isinstance(name, str) else name.name
        cache_key = (name_str, dialect, is_table, normalize)

        if cached := self._normalized_name_cache.get(cache_key):
            return cached

        result = normalize_name(
            name,
            dialect=dialect,
            is_table=is_table,
            normalize=normalize,
        ).name

        self._normalized_name_cache[cache_key] = result
        return result

    def depth(self) -> int:
        pass

    def _to_data_type(self, schema_type: str, dialect: DialectType = None) -> exp.DataType:
        """
        Convert a type represented as a string to the corresponding `sqlglot.exp.DataType` object.

        Args:
            schema_type: the type we want to convert.
            dialect: the SQL dialect that will be used to parse `schema_type`, if needed.

        Returns:
            The resulting expression type.
        """
        if schema_type not in self._type_mapping_cache:
            dialect = Dialect.get_or_raise(dialect) if dialect else self.dialect
            udt = dialect.SUPPORTS_USER_DEFINED_TYPES

            try:
                expression = exp.DataType.build(schema_type, dialect=dialect, udt=udt)
                expression.transform(dialect.normalize_identifier, copy=False)
                self._type_mapping_cache[schema_type] = expression
            except AttributeError:
                in_dialect = f" in dialect {dialect}" if dialect else ""
                raise SchemaError(f"Failed to build type '{schema_type}'{in_dialect}.")

        return self._type_mapping_cache[schema_type]


def normalize_name(
    identifier: str | exp.Identifier,
    dialect: DialectType = None,
    is_table: bool = False,
    normalize: bool | None = True,
) -> exp.Identifier:
    if isinstance(identifier, str):
        identifier = exp.parse_identifier(identifier, dialect=dialect)

    if not normalize:
        return identifier

    # this is used for normalize_identifier, bigquery has special rules pertaining tables
    identifier.meta["is_table"] = is_table
    return Dialect.get_or_raise(dialect).normalize_identifier(identifier)


def ensure_schema(
    schema: Schema | dict[str, object] | None, **kwargs: Unpack[SchemaArgs]
) -> Schema:
    if isinstance(schema, Schema):
        return schema

    return MappingSchema(schema, **kwargs)


def ensure_column_mapping(mapping: ColumnMapping | None) -> dict:
    pass


def flatten_schema(
    schema: dict[str, object], depth: int | None = None, keys: list[str] | None = None
) -> list[list[str]]:
    tables: list[list[str]] = []
    keys = keys or []
    depth = dict_depth(schema) - 1 if depth is None else depth

    for k, v in schema.items():
        if depth == 1 or not isinstance(v, dict):
            tables.append(keys + [k])
        elif depth >= 2:
            tables.extend(flatten_schema(v, depth - 1, keys + [k]))

    return tables


def nested_get(
    d: dict[str, object], *path: tuple[str, str], raise_on_missing: bool = True
) -> t.Any | None:
    """
    Get a value for a nested dictionary.

    Args:
        d: the dictionary to search.
        *path: tuples of (name, key), where:
            `key` is the key in the dictionary to get.
            `name` is a string to use in the error if `key` isn't found.

    Returns:
        The value or None if it doesn't exist.
    """
    result: t.Any = d
    for name, key in path:
        result = result.get(key)
        if result is None:
            if raise_on_missing:
                name = "table" if name == "this" else name
                raise ValueError(f"Unknown {name}: {key}")
            return None

    return result


def nested_set(d: dict[str, t.Any], keys: Sequence[str], value: t.Any) -> dict[str, t.Any]:
    """
    In-place set a value for a nested dictionary

    Example:
        >>> nested_set({}, ["top_key", "second_key"], "value")
        {'top_key': {'second_key': 'value'}}

        >>> nested_set({"top_key": {"third_key": "third_value"}}, ["top_key", "second_key"], "value")
        {'top_key': {'third_key': 'third_value', 'second_key': 'value'}}

    Args:
        d: dictionary to update.
        keys: the keys that makeup the path to `value`.
        value: the value to set in the dictionary for the given key path.

    Returns:
        The (possibly) updated dictionary.
    """
    if not keys:
        return d

    if len(keys) == 1:
        d[keys[0]] = value
        return d

    subd = d
    for key in keys[:-1]:
        if key not in subd:
            subd = subd.setdefault(key, {})
        else:
            subd = subd[key]

    subd[keys[-1]] = value
    return d
