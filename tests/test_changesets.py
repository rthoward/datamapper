from datetime import date

import pytest
import sqlalchemy as sa

from datamapper.changeset import Changeset
from datamapper.model import Associations, HasMany, HasOne, Model, Table
from tests.support import Home, User, metadata


class Person(Model):
    __table__ = Table(
        "people",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("name", sa.String(255)),
        sa.Column("age", sa.BigInteger),
    )

    __associations__ = Associations(
        HasOne("home", "tests.support.Home", "owner_id"),
        HasMany("pets", "tests.support.Pet", "owner_id"),
    )


def is_30(age):
    if age != 30:
        return "not 30"


class Book(Model):
    __table__ = sa.Table(
        "books",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(255)),
        sa.Column("isbn", sa.String(255)),
        sa.Column("publication_date", sa.Date()),
        sa.Column("slug", sa.String(255)),
    )


def test_cast_empty():
    changeset = Changeset(User()).cast({}, [])
    assert changeset.is_valid
    assert changeset.changes == {}


def test_cast():
    changeset = Changeset(User()).cast({"name": "Richard", "foo": "bar"}, ["name"])
    assert changeset.is_valid
    assert changeset.changes == {"name": "Richard"}


def test_cast_type_check():
    changeset = Changeset(User()).cast({"name": 1}, ["name"])
    assert changeset.errors == {"name": ["Not a valid string."]}


def test_put_assoc():
    user = User(id=1, name="Bear")
    changeset = (
        Changeset(Home())
        .cast({"name": "Big Blue House"}, ["name"])
        .put_assoc("owner", user)
    )
    assert changeset.changes == {"owner_id": 1, "name": "Big Blue House"}


def test_put_assoc_with_dict_data_is_invalid():
    user = User(id=1, name="Bear")
    with pytest.raises(ValueError):
        (
            Changeset(({}, {}))
            .cast({"name": "Big Blue House"}, ["name"])
            .put_assoc("owner", user)
        )


def test_put_assoc_works_only_for_belongs_to():
    with pytest.raises(NotImplementedError):
        Changeset(User()).put_assoc("home", Home())


def test_validate_required():
    changeset = Changeset(User()).cast({}, ["foo"]).validate_required(["foo", "bar"])
    assert changeset.errors == {
        "foo": ["Missing data for required field."],
        "bar": ["Missing data for required field."],
    }


def test_validate_change():
    changeset = (
        Changeset(Person())
        .cast({"name": "Richard", "age": 31}, ["name", "age"])
        .validate_change("age", is_30)
    )
    assert changeset.errors == {
        "age": ["not 30"],
    }


def test_validate_inclusion_valid():
    assert (
        Changeset(Person())
        .cast(
            {
                "name": "Richard",
                "age": 30,
                "favorite_animals": ["cat", "bat", "rat", "weasel"],
            },
            ["name", "age", "favorite_animals"],
        )
        .validate_inclusion("favorite_animals", "weasel")
    ).is_valid


def test_validate_inclusion_invalid():
    changeset = (
        Changeset(Person())
        .cast(
            {"name": "Richard", "age": 30, "favorite_animals": ["cat", "bat", "rat"]},
            ["name", "age", "favorite_animals"],
        )
        .validate_inclusion("favorite_animals", "ferret", "you love ferrets")
    )

    assert changeset.errors == {"favorite_animals": ["you love ferrets"]}


def test_validate_exclusion_valid():
    assert (
        Changeset(Person())
        .cast(
            {
                "name": "Richard",
                "age": 30,
                "favorite_animals": ["cat", "bat", "rat", "weasel"],
            },
            ["name", "age", "favorite_animals"],
        )
        .validate_exclusion("favorite_animals", "spider")
    ).is_valid


def test_validate_exclusion_invalid():
    changeset = (
        Changeset(Person())
        .cast(
            {
                "name": "Richard",
                "age": 30,
                "favorite_animals": ["cat", "bat", "rat", "spider"],
            },
            ["name", "age", "favorite_animals"],
        )
        .validate_exclusion("favorite_animals", "spider", "you hate spiders")
    )

    assert changeset.errors == {"favorite_animals": ["you hate spiders"]}


def test_validate_change_only_validates_if_field_is_changed():
    changeset = (
        Changeset(Person())
        .cast({"name": "Richard"}, ["name"])
        .validate_change("age", is_30)
    )
    assert changeset.is_valid


def test_change_allows_one_to_add_invalid_changes():
    changeset = (
        Changeset(Person())
        .cast({"name": "Richard"}, ["name"])
        .validate_change("age", is_30)
        .change({"id": "foo"})
    )

    assert changeset.changes["id"] == "foo"


def test_changes_with_valid_changeset():
    changeset = Changeset(User(name="foo")).cast({"name": "bar"}, ["name"])
    assert changeset.changes == {"name": "bar"}


def test_changes_with_invalid_changeset():
    changeset = Changeset(User(name="foo")).cast({"name": 42}, ["name"])
    assert changeset.changes == {}


def test_apply_changes_to_model():
    changeset = Changeset(User(name="foo")).cast({"name": "bar"}, ["name"])
    changed_user = changeset.apply_changes()
    assert changed_user.name == "bar"


def test_schemaless_invalid():
    cat = {"name": "Gordon"}
    types = {"name": str, "age": int, "color": str}
    permitted = types.keys()

    changeset = Changeset((cat, types)).cast(
        {"color": "brown", "age": "fourteen"}, permitted
    )
    assert changeset.errors == {"age": ["Not a valid integer."]}


def test_schemaless_valid():
    cat = {"name": "Gordon"}
    types = {"name": str, "age": int, "color": str}
    permitted = types.keys()

    changeset = Changeset((cat, types)).cast({"color": "brown", "age": 14}, permitted)
    assert changeset.is_valid


def test_schemaless_apply_changes():
    cat = {"name": "Gordon"}
    types = {"name": str, "age": int, "color": str}
    permitted = types.keys()

    changeset = Changeset((cat, types)).cast({"color": "brown", "age": 14}, permitted)
    assert changeset.apply_changes() == {"name": "Gordon", "age": 14, "color": "brown"}


def test_on_changed():
    def _slugify(changeset, title):
        return changeset.put_change("slug", title.lower().replace(" ", "-"))

    params = {
        "title": "Crime and Punishment",
        "publication_date": date(1866, 1, 1),
    }
    book = (
        Changeset(Book())
        .cast(params, ["title", "publication_date"])
        .on_changed("title", _slugify)
        .apply_changes()
    )

    assert book.slug == "crime-and-punishment"


def test_on_changed_with_no_change():
    def _slugify(changeset, title):
        return changeset.put_change("slug", title.lower().replace(" ", "-"))

    params = {
        "publication_date": date(1866, 1, 1),
    }
    changeset = (
        Changeset(Book(title="Crime and Punishment"))
        .cast(params, ["title", "publication_date"])
        .on_changed("title", _slugify)
    )
    assert changeset.changes.get("slug") is None


def test_fetch_change_from_changes():
    assert (
        Changeset(Book(title="Crime and Punishment"))
        .cast({"title": "The Brothers Karamazov"}, ["title"])
        .fetch_change("title")
    ) == "The Brothers Karamazov"


def test_fetch_change_from_data():
    assert (
        Changeset(Book(title="Crime and Punishment"))
        .cast({"isbn": "1234567890"}, ["isbn"])
        .fetch_change("title")
    ) is None


def test_fetch_field_from_changes():
    assert (
        Changeset(Book(title="Crime and Punishment"))
        .cast({"title": "The Brothers Karamazov"}, ["title"])
        .fetch_field("title")
    ) == "The Brothers Karamazov"


def test_fetch_field_from_data():
    assert (
        Changeset(Book(title="Crime and Punishment"))
        .cast({"isbn": "1234567890"}, ["isbn"])
        .fetch_field("title")
    ) == "Crime and Punishment"


def test_put_change():
    assert (
        Changeset(Book())
        .cast({"title": "The Idiot"}, ["title"])
        .put_change("isbn", "01234567890")
        .changes["isbn"]
    ) == "01234567890"


def test_invalid_data():
    with pytest.raises(AttributeError):
        Changeset("foo")
