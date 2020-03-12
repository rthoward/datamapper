from __future__ import annotations

from typing import Any, List, Mapping, Optional, Type, Union

from sqlalchemy import Table
from sqlalchemy.sql.expression import ClauseElement, Delete, FromClause, Select, Update

import datamapper.model as model
from datamapper._utils import get_column
from datamapper.query.alias_tracker import AliasTracker
from datamapper.query.join import Join, to_join_tree
from datamapper.query.parser import parse_order, parse_where

WhereClause = Union[ClauseElement, dict]
OrderClause = Union[ClauseElement, str]


class Query:
    __slots__ = [
        "_model",
        "_wheres",
        "_order_bys",
        "_limit",
        "_offset",
        "_joins",
        "_preloads",
    ]

    _model: Type[model.Model]
    _wheres: List[WhereClause]
    _order_bys: List[OrderClause]
    _joins: List[Join]
    _limit: Optional[int]
    _offset: Optional[int]
    _preloads: List[str]

    def __init__(self, model: Type[model.Model]):
        self._model = model
        self._wheres = []
        self._order_bys = []
        self._joins = []
        self._limit = None
        self._offset = None
        self._preloads = []

    def to_query(self) -> Query:
        return self

    def to_sql(self) -> Select:
        return self.__compile(self._model.__table__.select())

    def to_update_sql(self) -> Update:
        return self.__compile(self._model.__table__.update())

    def to_delete_sql(self) -> Delete:
        return self.__compile(self._model.__table__.delete())

    def deserialize(self, row: Mapping) -> model.Model:
        return self._model.deserialize(row)

    def limit(self, value: int) -> Query:
        """
        Add a `LIMIT` clause to the query.

        Examples::

            Query(User).limit(1)
            # SELECT * FROM users LIMIT 1
        """
        return self.__update(_limit=value)

    def offset(self, value: int) -> Query:
        """
        Add an `OFFSET` clause to the query.

        Examples::

            Query(User).offset(1)
            # SELECT * FROM users OFFSET 1
        """
        return self.__update(_offset=value)

    def where(self, *args: ClauseElement, **kwargs: Any) -> Query:
        """
        Add a `WHERE` clause to the query.

        Examples::

            Query(Pet).where(name="Fido")
            # SELECT * FROM pets WHERE pets.name = 'Fido'

            Query(Pet).where(name__eq="Sue")
            # SELECT * FROM pets WHERE pets.name = 'Sue'

            Query(Pet).where(name__not_eq="Sue")
            # SELECT * FROM pets WHERE pets.name != 'Sue'

            Query(Pet).where(name__like="Sue")
            # SELECT * FROM pets WHERE pets.name LIKE 'Sue'

            Query(Pet).where(name__not_like="Sue")
            # SELECT * FROM pets WHERE pets.name NOT LIKE 'Sue'

            Query(Pet).where(name__ilike="sue")
            # SELECT * FROM pets WHERE pets.name ILIKE 'sue'

            Query(Pet).where(name__not_ilike="sue")
            # SELECT * FROM pets WHERE pets.name NOT ILIKE 'sue'

            Query(Pet).where(name__contains="u")
            # SELECT * FROM pets WHERE (pets.name LIKE '%%' || 'u' || '%%')

            Query(Pet).where(name__startswith="S")
            # SELECT * FROM pets WHERE (pets.name LIKE 'S' || '%%')

            Query(Pet).where(name__endswith="e")
            # SELECT * FROM pets WHERE (pets.name LIKE '%%' || 'e')

            Query(Pet).where(id__in=[1, 2])
            # SELECT * FROM pets WHERE pets.id in (1, 2)

            Query(Pet).where(age__gt=1)
            # SELECT * FROM pets WHERE pets.age > 1

            Query(Pet).where(age__gte=1)
            # SELECT * FROM pets WHERE pets.age >= 1

            Query(Pet).where(age__lt=1)
            # SELECT * FROM pets WHERE pets.age < 1

            Query(Pet).where(age__lte=1)
            # SELECT * FROM pets WHERE pets.age <= 1

        You can query a joined table by it's alias.::

            Query(Pet).join("owner", "o").where(o__name="Fred")
            # SELECT * FROM pets
            # JOIN owner AS o ON o.id = pets.owner_id
            # WHERE o.name = 'Fred'

            Query(Pet).outerjoin("owner", "o").where(o__id__in=[1, 2])
            # SELECT * FROM pets
            # LEFT JOIN owner AS o ON o.id = pets.owner_id
            # WHERE o.id IN (1, 2)

        You can also provide a SQLAlchemy clause::

            Query(User).where(sqlalchemy.text("1 = 1"))
            # SELECT * FROM users WHERE 1 = 1

            Query(User).where(User.__table__.c.id == 9)
            # SELECT * FROM users WHERE users.id = 9
        """
        return self.__update(_wheres=self._wheres + list(args) + [kwargs])

    def order_by(self, *args: Union[str, ClauseElement]) -> Query:
        """
        Add an `ORDER BY` clause to the query.

        Examples::

            Query(User).order_by("name")
            # SELECT * FROM users ORDER BY users.name ASC

            Query(User).order_by("-name")
            # SELECT * FROM users ORDER BY users.name DESC

        You can order by a joined column by it's alias::

            Query(User).join("pets", "p").order_by("p__name__desc")
            # SELECT * FROM users
            # JOIN pets AS p ON pets.owner_id = users.id
            # ORDER BY p.name DESC

        You can also provide a SQLAlchemy clause::

            Query(User).order_by(User.__table__.c.id.asc())
            # SELECT * FROM users ORDER BY users.id ASC

        """
        return self.__update(_order_bys=self._order_bys + list(args))

    def preload(self, preload: str) -> Query:
        """
        Load records that are associated with this query's results.

        Examples::

            query = User(Author).preload("posts.comments")
            authors = await repo.all(query)
            authors[0].posts[0].comments
        """
        return self.__update(_preloads=self._preloads + [preload])

    def join(self, name: str, alias: Optional[str] = None) -> Query:
        """
        Add a `JOIN` clause to the query.

        Examples::

            Query(Author).join("posts").join("posts.comments")
            # SELECT * FROM authors
            # JOIN posts AS p0 ON p0.author_id = authors.id
            # JOIN comments AS c0 ON c0.post_id = posts.id

        You can also specify an alias for the join::

            Query(Author).join("posts", "my_posts")
            # SELECT * FROM authors
            # JOIN posts AS my_posts ON my_posts.author_id = authors.id
        """
        join = Join(self._model, name.split("."), alias=alias)
        return self.__update(_joins=self._joins + [join])

    def outerjoin(self, name: str, alias: Optional[str] = None) -> Query:
        """
        Add a `JOIN` clause to the query.

        Examples::

            Query(Author).join("posts").outerjoin("posts.comments")
            # SELECT * FROM authors
            # JOIN posts AS p0 ON p0.author_id = authors.id
            # LEFT JOIN comments AS c0 ON c0.post_id = posts.id

        You can also specify an alias for the join::

            Query(Author).outerjoin("posts", "my_posts")
            # SELECT * FROM authors
            # LEFT JOIN posts AS my_posts ON my_posts.author_id = authors.id
        """
        join = Join(self._model, name.split("."), alias=alias, outer=True)
        return self.__update(_joins=self._joins + [join])

    def __compile(self, sql: ClauseElement) -> ClauseElement:
        tracker = AliasTracker()

        if self._joins:
            sql = self.__build_joins(sql, tracker)

        if self._wheres:
            sql = self.__build_where(sql, tracker)

        if self._order_bys:
            sql = self.__build_order(sql, tracker)

        if self._limit is not None:
            sql = sql.limit(self._limit)

        if self._offset is not None:
            sql = sql.offset(self._offset)

        return sql

    def __build_where(self, sql: ClauseElement, tracker: AliasTracker) -> ClauseElement:
        for where in self._wheres:
            if isinstance(where, dict):
                for name, value in where.items():
                    name, op, alias_name = parse_where(name)

                    if alias_name:
                        table = tracker.fetch(alias_name)
                    else:
                        table = self._model.__table__

                    column = get_column(table, name)
                    clause = getattr(column, op)(value)
                    sql = sql.where(clause)

            else:
                sql = sql.where(where)

        return sql

    def __build_joins(self, sql: ClauseElement, tracker: AliasTracker) -> ClauseElement:
        table = self._model.__table__
        join_tree = to_join_tree(self._joins)
        clause = _walk_joins(table, table, join_tree, tracker)
        return sql.select_from(clause)

    def __build_order(self, sql: ClauseElement, tracker: AliasTracker) -> ClauseElement:
        clauses = []

        for order_by in self._order_bys:
            if isinstance(order_by, str):
                name, direction, alias_name = parse_order(order_by)

                if alias_name:
                    table = tracker.fetch(alias_name)
                else:
                    table = self._model.__table__

                column = get_column(table, name)
                clause = getattr(column, direction)()
                clauses.append(clause)

            else:
                clauses.append(order_by)

        return sql.order_by(*clauses)

    def __update(self, **kwargs: Any) -> Query:
        query = self.__class__(self._model)
        for key in self.__class__.__slots__:
            if key in kwargs:
                setattr(query, key, kwargs[key])
            else:
                setattr(query, key, getattr(self, key))
        return query


def _walk_joins(
    clause: FromClause, owner_table: Table, tree: dict, tracker: AliasTracker,
) -> ClauseElement:
    for join, subjoins in tree.items():
        assoc = join.find_association()

        related_table = assoc.related.__table__
        related_table = tracker.put(related_table, alias_name=join.alias)

        related_column = getattr(related_table.c, assoc.related_key)
        owner_column = getattr(owner_table.c, assoc.owner_key)

        on_clause = related_column == owner_column
        clause = clause.join(related_table, on_clause, isouter=join.is_outer)
        clause = _walk_joins(clause, related_table, subjoins, tracker)

    return clause
