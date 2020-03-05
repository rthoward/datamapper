from typing import Any, Type, Union, List, Optional, Protocol
from sqlalchemy import func
from databases import Database
from datamapper.query import Query
from datamapper.model import Model, Cardinality
from datamapper._utils import cast_list, expand_preloads, assert_one, collect_sql_values


class Queryable(Protocol):
    def to_query(self) -> Query:
        ...  # pragma: no cover


class Repo:
    def __init__(self, database: Database):
        self.database = database

    async def all(self, queryable: Queryable) -> List[Model]:
        query = queryable.to_query()
        rows = await self.database.fetch_all(query.to_sql())
        records = [query.deserialize(row) for row in rows]

        if query.preloads:
            await self.preload(records, query.preloads)

        return records

    async def first(self, queryable: Queryable) -> Optional[Model]:
        query = queryable.to_query().limit(1)
        records = await self.all(query)
        return records[0] if records else None

    async def one(self, queryable: Queryable) -> Model:
        records = await self.all(queryable)
        assert_one(records)
        return records[0]

    async def get_by(self, queryable: Queryable, **values: Any) -> Model:
        return await self.one(queryable.to_query().where(**values))

    async def get(self, queryable: Queryable, id: Union[str, int]) -> Model:
        return await self.one(queryable.to_query().where(id=id))

    async def count(self, queryable: Queryable) -> int:
        sql = queryable.to_query().to_sql()
        sql = sql.alias("subquery_for_count")
        sql = func.count().select().select_from(sql)
        return await self.database.fetch_val(sql)

    async def insert(self, model: Type[Model], **values: Any) -> Model:
        sql_values = collect_sql_values(model, values)
        sql = model.__table__.insert().values(**sql_values)
        record_id = await self.database.execute(sql)
        return model(id=record_id, **values)

    async def update(self, record: Model, **values: Any) -> Model:
        query = record.to_query()
        sql_values = collect_sql_values(record, values)
        sql = query.to_update_sql().values(**sql_values)
        await self.database.execute(sql)
        for key, value in values.items():
            setattr(record, key, value)
        return record

    async def delete(self, record: Model, **values: Any) -> Model:
        query = record.to_query()
        sql = query.to_delete_sql()
        await self.database.execute(sql)
        return record

    async def update_all(self, queryable: Queryable, **values: Any) -> None:
        query = queryable.to_query()
        sql = query.to_update_sql()
        sql = sql.values(**values)
        await self.database.execute(sql)

    async def delete_all(self, queryable: Queryable) -> None:
        query = queryable.to_query()
        sql = query.to_delete_sql()
        await self.database.execute(sql)

    async def preload(
        self, records: Union[Model, List[Model]], preloads: List[str]
    ) -> None:
        records = cast_list(records)
        preloads = expand_preloads(cast_list(preloads))
        await self.__preload(records, preloads)

    async def __preload(self, owners: List[Model], preloads: dict) -> None:
        for name, subpreloads in preloads.items():
            model = owners[0].__class__
            assoc = model.association(name)

            values = [getattr(r, assoc.owner_key) for r in owners]
            where = {assoc.related_key: values}
            query = Query(assoc.related).where(**where)
            relateds = await self.all(query)

            lookup: dict = {}
            for related in relateds:
                key = getattr(related, assoc.related_key)
                if assoc.cardinality == Cardinality.ONE:
                    lookup[key] = related
                elif key in lookup:
                    lookup[key].append(related)
                else:
                    lookup[key] = [related]
            for owner in owners:
                key = getattr(owner, assoc.owner_key)
                if assoc.cardinality == Cardinality.ONE:
                    setattr(owner, name, lookup.get(key, None))
                else:
                    setattr(owner, name, lookup.get(key, []))
            await self.__preload(relateds, subpreloads)
