""" Various tests for the Model class """

import datetime

from bson.objectid import ObjectId
import mogo
from mogo.connection import connect
from mogo.model import PolyModel, Model, InvalidUpdateCall, UnknownField
from mogo.field import ReferenceField, Field, EmptyRequiredField
import unittest
import warnings

from typing import Any, cast
from typing import Dict, List, Sequence  # noqa: F401


class Ref(Model):
    pass


class Foo(Model):

    field = Field[Any]()
    required = Field[Any](required=True)
    default = Field[Any](default="default")
    callback = Field[Any](
        get_callback=lambda x, y: "foo", set_callback=lambda x, y: "bar")
    reference = ReferenceField(Ref)
    _private_field = Field[Any]()


class Bar(Model):

    uid = Field[str](str)


class ChildRef(Ref):
    pass


class Person(PolyModel):

    @classmethod
    def get_child_key(cls) -> str:
        return "role"

    role = Field[str](str, default="person")

    def walk(self) -> bool:
        """ Default method """
        return True


@Person.register
class Child(Person):
    role = Field[str](str, default="child")


@Person.register
class Adult(Person):
    role = Field[str](str, default="adult")
    age = Field[int](int, default=18)


@Person.register(name="infant")
class Infant(Person):
    age = Field[int](int, default=3)
    role = Field[str](str, default="infant")

    def crawl(self) -> bool:
        """ Example of a custom method """
        return True

    def walk(self) -> bool:
        """ Overwriting a method """
        return False


# Don't read too closely into these shape definitions... :)


class Polygon(PolyModel):

    sides = Field[int](int, default=0)

    @classmethod
    def get_child_key(cls) -> str:
        return "sides"

    def closed(self) -> bool:
        return False

    def tessellates(self) -> bool:
        return False


@Polygon.register(3)
class Triangle(Polygon):

    sides = Field[int](int, default=3)

    def closed(self) -> bool:
        return True


@Polygon.register(4)
class Rectangle(Polygon):

    sides = Field[int](int, default=4)

    def closed(self) -> bool:
        return True

    def tessellates(self) -> bool:
        return True


DBNAME = '_mogotest'


class TestModel(unittest.TestCase):
    def setUp(self) -> None:
        super().setUp()
        self._conn = connect(DBNAME)

    def tearDown(self) -> None:
        super().tearDown()
        self._conn.drop_database(DBNAME)

    def test_model_fields_initialize_properly(self) -> None:
        """ Test that the model properly retrieves the fields """
        foo = Foo()
        self.assertIn("field", foo._fields.values())
        self.assertIn("required", foo._fields.values())
        self.assertIn("callback", foo._fields.values())
        self.assertIn("reference", foo._fields.values())
        self.assertIn("default", foo._fields.values())
        self.assertIn("_private_field", foo._fields.values())

    def test_model_create_fields_inititialize_new_fields_with_autocreate(
            self) -> None:
        class Testing(Model):
            pass
        try:
            mogo.AUTO_CREATE_FIELDS = True
            schemaless = Testing(foo="bar")
            self.assertEqual(schemaless["foo"], "bar")
            self.assertEqual(schemaless.foo, "bar")  # type: ignore
            self.assertIn("foo", schemaless.copy())
            foo_field = getattr(Testing, "foo")
            self.assertIsNotNone(foo_field)
            self.assertIn(id(foo_field), schemaless._fields)
        finally:
            mogo.AUTO_CREATE_FIELDS = False

    def test_model_add_field_dynamically_registers_new_field(self) -> None:
        class Testing(Model):
            pass
        Testing.add_field(
            "foo", Field(str, set_callback=lambda x, y: "bar"))
        self.assertIsInstance(Testing.foo, Field)  # type: ignore
        testing = Testing(foo="whatever")
        self.assertEqual(testing["foo"], "bar")
        self.assertEqual(testing.foo, "bar")  # type: ignore
        testing2 = Testing()
        testing2.foo = "whatever"  # type: ignore
        self.assertEqual("bar", testing2.foo)  # type: ignore

    def test_model_rejects_unknown_field_values_by_default(self) -> None:
        class Testing(Model):
            pass
        with self.assertRaises(UnknownField):
            Testing(foo="bar")

    def test_default_field_value_sets_default_on_construction(self) -> None:
        foo = Foo()
        self.assertEqual(foo["default"], "default")
        self.assertEqual(foo.default, "default")

    def test_required_fields_raise_when_values_missing(self) -> None:
        foo = Foo()
        with self.assertRaises(EmptyRequiredField):
            foo.save()
        with self.assertRaises(EmptyRequiredField):
            getattr(foo, "required")
        with self.assertRaises(InvalidUpdateCall):
            foo.update(foo="bar")

    def test_count_documents_passes_through(self) -> None:
        expected = []  # type: List[Foo]
        limit = 15
        skip = 5

        for i in range(50):
            value = "b" if i % 2 == 1 else "a"
            foo = Foo.create(required=value)
            if i >= skip and foo.default == "b" and len(expected) < limit:
                expected.append(foo)

        query = {"required": "b"}

        actual_count = Person.count_documents(
            query, limit=limit, skip=skip)  # type: int
        self.assertEqual(actual_count, len(expected))

        results = list(Person.find(query).limit(limit).skip(skip))
        self.assertEqual(expected, results)

    def test_model_null_equality_comparison_is_false(self) -> None:
        foo = Foo()
        self.assertIsNotNone(foo)

    def test_model_comparison_with_other_objects_works(self) -> None:
        foo = Foo()
        self.assertNotEqual(foo, object())

    def test_null_reference_field_value_is_supported(self) -> None:
        foo = Foo()
        foo.reference = None
        self.assertEqual(foo.reference, None)

    def test_string_representation_calls__unicode__method(self) -> None:
        foo = Foo()
        foo["_id"] = 5
        self.assertEqual(str(foo), "<MogoModel:foo id:5>")

    def test_reference_field_accepts_instance_of_referred_model(self) -> None:
        foo = Foo()
        child_ref = ChildRef(_id="testing")  # hardcoding id
        foo.reference = child_ref
        self.assertEqual(foo["reference"].id, child_ref.id)

    def test_id_access_methods_return_id_value(self) -> None:
        foo = Foo(_id="whoop")
        self.assertEqual(foo.id, "whoop")
        self.assertEqual(foo._id, "whoop")
        self.assertEqual(foo['_id'], "whoop")

    def test_model_upserts_on_save_with_custom_id_value(self) -> None:
        custom_time = datetime.datetime.now() - datetime.timedelta(days=30)
        custom_id = ObjectId.from_datetime(custom_time)
        foo = Foo.new(required="foobar")
        foo["_id"] = custom_id
        foo.save()
        result = Foo.first()

        if not result:
            self.fail("Did not save Foo instance with custom _id.")

        idval = cast(ObjectId, result.id)
        self.assertEqual(idval, custom_id)

    def test_inheritance_constructs_proper_polymorphic_instances(self) -> None:
        self.assertEqual(Person._get_name(), Child._get_name())
        self.assertEqual(Person._get_name(), Infant._get_name())
        person = Person()
        self.assertIsInstance(person, Person)
        self.assertTrue(person.walk())
        self.assertEqual(person.role, "person")
        with self.assertRaises(AttributeError):
            person.crawl()  # type: ignore
        child = Person(role="child")
        self.assertIsInstance(child, Child)
        child2 = Child()
        self.assertTrue(child2.walk())
        self.assertEqual(child2.role, "child")
        child3 = Child(role="person")
        self.assertIsInstance(child3, Person)

        infant = Infant()
        self.assertIsInstance(infant, Infant)
        self.assertEqual(infant.age, 3)
        self.assertTrue(infant.crawl())
        self.assertFalse(infant.walk())
        infant2 = Person(age=3, role="infant")
        self.assertIsInstance(infant2, Infant)

    def test_distinct_returns_sequence_of_distinct_values(self) -> None:
        Infant.create(age=10)
        Infant.create(age=15)
        distinct = Infant.distinct("age")
        self.assertCountEqual([10, 15], distinct)

    def test_instances_equal_each_other(self) -> None:
        infant1 = Infant.create(age=10)
        infant2 = Infant.grab(infant1.id)
        self.assertEqual(infant1, infant2)

    def test_different_instances_not_equal_each_other(self) -> None:
        infant1 = Infant.create(age=10)
        infant2 = Infant.create(age=10)
        self.assertNotEqual(infant1, infant2)

    def test_remove_cannot_be_accessed_from_an_instance(self) -> None:
        person = Person()
        with self.assertRaises(TypeError):
            person.remove(role="person")

    def test_drop_cannot_be_accessed_from_an_instance(self) -> None:
        person = Person()
        with self.assertRaises(TypeError):
            person.drop()

    def test_make_ref_cannot_be_accessed_from_an_instance(self) -> None:
        person = Person()
        with self.assertRaises(TypeError):
            person.make_ref("idval")

    def test_aggregate_passes_call_to_underlying_collection(self) -> None:
        Adult.create(age=17)
        Adult.create(age=24)
        Infant.create(age=5)
        Infant.create(age=10)
        Infant.create(age=15)
        result = Infant.aggregate([
            {"$match": {"age": {"$lte": 10}}},
            {"$group": {"_id": "$role", "total_age": {"$sum": "$age"}}}
        ])  # type: Sequence[Dict[str, Any]]
        self.assertEqual([{"_id": "infant", "total_age": 15}], list(result))

    def test_parent_model_aggregates_across_submodels(self) -> None:
        Adult.create(age=24)
        Adult.create(age=50)
        Infant.create(age=5)
        Infant.create(age=1)
        result = Person.aggregate([
            {"$group": {"_id": "$role", "total_age": {"$sum": "$age"}}}
        ])  # type: Sequence[Dict[str, Any]]
        self.assertCountEqual(
            [
                {"_id": "adult", "total_age": 74},
                {"_id": "infant", "total_age": 6}
            ],
            list(result))

    def test_find_one_and_find_raise_warning_with_timeout(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with self.assertRaises(DeprecationWarning):
                Person.find({}, timeout=False)
            with self.assertRaises(DeprecationWarning):
                Person.find_one({}, timeout=False)

    def test_save_with_safe_raises_deprecation_warning(self) -> None:
        person = Person()
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            with self.assertRaises(DeprecationWarning):
                person.save(safe=True)

    def test_polymodel_registration_implicit_arguments(self) -> None:
        Polygon.create(sides=10)
        Polygon.create(sides=3)
        Polygon.create(sides=4)

        for model in Polygon.find():
            if model.sides == 3:
                self.assertFalse(model.tessellates())
                self.assertTrue(model.closed())
                self.assertTrue(isinstance(model, Triangle))
            elif model.sides == 4:
                self.assertTrue(model.tessellates())
                self.assertTrue(model.closed())
                self.assertTrue(isinstance(model, Rectangle))
            else:
                self.assertFalse(model.tessellates())
                self.assertFalse(model.closed())
                self.assertTrue(isinstance(model, Polygon))
