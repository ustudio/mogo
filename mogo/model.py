"""
This is the core of the library. It is a dict subclass with a few wrapper
methods. The idea is that you can access everything like normal in pymongo if
you want to, with keys aplenty, or you can access values with attribute-style
syntax.

Most importantly you can add methods to the model. This is desired when
following the Information Expert pattern of placing behavior with the data to
support it.

Specifying fields is optional, although it is recommended for
external references.

Usage example:

    from mogo import Model
    import hashlib
    from datetime import datetime

    class UserAccount(Model):

        name = Field(str)
        email = Field(str)
        company = ReferenceField(Company)
        created_at = Field(datetime, datetime.now)

        # Custom method example
        def set_password(self, password):
            self.password = hashlib.md5(password).hexdigest()
            self.save()

"""

import mogo
from mogo.connection import Connection
from mogo.cursor import Cursor
from mogo.field import Field, EmptyRequiredField
from pymongo.dbref import DBRef
from pymongo.objectid import ObjectId
from mogo.decorators import notinstancemethod
import logging


class BiContextual(object):
    """ Probably a terrible, terrible idea. """

    def __init__(self, name):
        self.name = name

    def __get__(self, obj, type=None):
        """ Return a properly named method. """
        if obj is None:
            return getattr(type, "_class_" + self.name)
        return getattr(obj, "_instance_" + self.name)


class InvalidUpdateCall(Exception):
    """ Raised whenever update is called on a new model """
    pass


class UnknownField(Exception):
    """ Raised whenever an invalid field is accessed and the
    AUTO_CREATE_FIELDS is False.
    """
    pass


class NewModelClass(type):
    """ Metaclass for inheriting field lists """

    def __new__(cls, name, bases, attributes):
        # Emptying fields by default
        attributes["__fields"] = {}
        new_model = super(NewModelClass, cls).__new__(
            cls, name, bases, attributes)
        # pre-populate fields
        new_model._update_fields()
        return new_model

    def __setattr__(cls, name, value):
        super(NewModelClass, cls).__setattr__(name, value)
        if isinstance(value, Field):
            # Update the fields, because they have changed
            cls._update_fields()


class Model(dict):
    """Subclass this class to create your documents. Basic usage
    is really simple:

    class Foo(Model):
        pass

    foo = Foo(user='admin', password='cheese')
    foo.save()
    for result in Foo.find({'user':'admin'}):
        print result.password

    """
    __metaclass__ = NewModelClass

    _id_field = '_id'
    _id_type = ObjectId
    _name = None
    _collection = None
    _init_okay = False
    __fields = None

    # DEPRECATED
    @classmethod
    def new(cls, **kwargs):
        """ Overwrite in each model for custom instantiaion logic """
        instance = cls(**kwargs)
        return instance

    @classmethod
    def create(cls, *args, **kwargs):
        """ Create a new model and save it. """
        if hasattr(cls, "new"):
            model = cls.new(*args, **kwargs)
        else:
            model = cls(*args, **kwargs)
        model.save()
        return model

    def __init__(self, **kwargs):
        """ Just initializes the fields. This should ONLY be called
        from .new() or the Cursor.
        """
        super(Model, self).__init__()
        is_new_instance = "_id" not in kwargs
        for field, value in kwargs.iteritems():
            private_field = field.startswith("_")
            if private_field:
                # Setting it in the dict, but leaving it alone
                self[field] = value
            elif is_new_instance:
                if field in self._fields.values():
                    # Running validation, if the field exists
                    setattr(self, field, value)
                else:
                    if not mogo.AUTO_CREATE_FIELDS:
                        raise UnknownField("Unknown field %s" % field)
                    self.add_field(field, Field())
                    setattr(self, field, value)
            else:
                self[field] = value

        for field_name in self._fields.values():
            attr = getattr(self.__class__, field_name)
            if not isinstance(attr, Field):
                continue
            self._fields[attr.id] = field_name

            # set the default
            if attr.default is not None and not field_name in self:
                self[field_name] = attr._get_default()

    @property
    def _fields(self):
        """ Property wrapper for class fields """
        return self.__class__.__fields

    @classmethod
    def _update_fields(cls):
        """ (Re)update the list of fields """
        cls.__fields = {}
        for attr_key in dir(cls):
            if attr_key.startswith('_'):
                continue
            attr = getattr(cls, attr_key)
            if not isinstance(attr, Field):
                continue
            cls.__fields[attr.id] = attr_key

    @classmethod
    def add_field(cls, field_name, new_field_descriptor):
        """ Adds a new field to the class """
        assert(isinstance(new_field_descriptor, Field))
        setattr(cls, field_name, new_field_descriptor)
        cls._update_fields()

    def _get_id(self):
        """
        This is the internal id retrieval.
        The .id property is the public method for getting
        an id, but we use this so the user can overwrite
        'id' if desired.
        """
        return self.get(self._id_field)

    def save(self, *args, **kwargs):
        """ Passthru to PyMongo's save after checking values """
        coll = self._get_collection()
        self._check_required()
        new_object_id = coll.save(self.copy(), *args, **kwargs)
        if not self._get_id():
            super(Model, self).__setitem__(self._id_field, new_object_id)
        return new_object_id

    @classmethod
    def _class_update(cls, *args, **kwargs):
        """ Direct passthru to PyMongo's update. """
        coll = cls._get_collection()
        # Maybe should do something 'clever' with the query?
        # E.g. transform Model instances to DBRefs automatically?
        return coll.update(*args, **kwargs)

    def _instance_update(self, **kwargs):
        """ Wraps keyword arguments with setattr and then uses PyMongo's
        update call.
         """
        object_id = self._get_id()
        if not object_id:
            raise InvalidUpdateCall("Cannot call update on an unsaved model")
        spec = {self._id_field: object_id}
        # Currently the only argument we "pass on" is "safe"
        pass_kwargs = {}
        if "safe" in kwargs:
            pass_kwargs["safe"] = kwargs.pop("safe")
        body = {}
        checks = []
        for key, value in kwargs.iteritems():
            if key in self._fields.values():
                setattr(self, key, value)
            else:
                logging.warning("No field for %s" % key)
                self[key] = value
            # Attribute names to check.
            checks.append(key)
            # Field names in collection.
            field = getattr(self.__class__, key)
            field_name = field._get_field_name(self)
            # PyMongo value
            body[field_name] = self[field_name]
        logging.debug("Checking fields (%s).", checks)
        self._check_required(*checks)
        coll = self._get_collection()
        logging.debug("Setting body (%s)", body)
        return coll.update(spec, {"$set":  body}, **pass_kwargs)

    update = BiContextual("update")

    def _check_required(self, *field_names):
        """ Ensures that all required fields are set. """
        if not field_names:
            field_names = self._fields.values()
        for field_name in field_names:
            # check that required attributes have been set before,
            # or are currently being set
            field = getattr(self.__class__, field_name)
            storage_name = field._get_field_name(self)
            if storage_name not in self:
                if field.required:
                    raise EmptyRequiredField("'%s' is required but empty"
                                             % field_name)

    def delete(self, *args, **kwargs):
        """
        Uses the id in the collection.remove method.
        Allows all the same arguments (except the spec/id).
        """
        if not self._get_id():
            raise ValueError('No id has been set, so removal is impossible.')
        coll = self._get_collection()
        return coll.remove(self._get_id(), *args, **kwargs)

    # Using notinstancemethod for classmethods which would
    # have dire, unintended consequences if used on an
    # instance. (Like, wiping a collection by trying to "remove"
    # a single document.)
    @notinstancemethod
    def remove(cls, *args, **kwargs):
        """ Just a wrapper around the collection's remove. """
        coll = cls._get_collection()
        return coll.remove(*args, **kwargs)

    @notinstancemethod
    def drop(cls, *args, **kwargs):
        """ Just a wrapper around the collection's drop. """
        coll = cls._get_collection()
        return coll.drop(*args, **kwargs)

    # This is designed so that the end user can still use 'id' as a Field
    # if desired. All internal use should use model._get_id()
    @property
    def id(self):
        """
        Returns the id. This is designed so that a subclass can still
        overwrite 'id' if desired... internal use should only use
        self._get_id(). May remove in the future if it's more annoying
        than helpful.
        """
        return self._get_id()

    @classmethod
    def find_one(cls, *args, **kwargs):
        """
        Just a wrapper for collection.find_one(). Uses all
        the same arguments.
        """
        coll = cls._get_collection()
        result = coll.find_one(*args, **kwargs)
        if result:
            result = cls(**result)
        return result

    @classmethod
    def find(cls, *args, **kwargs):
        """
        A wrapper for the pymongo cursor. Uses all the
        same arguments.
        """
        return Cursor(cls, *args, **kwargs)

    @classmethod
    def group(cls, *args, **kwargs):
        """
        A quick wrapper for the pymongo collection map / reduce grouping.
        Will do more with this later.
        """
        return cls._get_collection().group(*args, **kwargs)

    @classmethod
    def search(cls, **kwargs):
        """
        Helper method that wraps keywords to dict and automatically
        turns instances into DBRefs.
        """
        query = {}
        for key, value in kwargs.iteritems():
            if isinstance(value, Model):
                value = value.get_ref()
            field = getattr(cls, key)

            # Try using custom field name in field.
            if field._field_name:
                key = field._field_name

            query[key] = value
        return cls.find(query)

    @classmethod
    def first(cls, **kwargs):
        """ Helper for returning Blah.search(foo=bar).first(). """
        result = cls.search(**kwargs)
        return result.first()

    @classmethod
    def grab(cls, object_id):
        """ A shortcut to retrieve one object by its id. """
        if type(object_id) != cls._id_type:
            object_id = cls._id_type(object_id)
        return cls.find_one({cls._id_field: object_id})

    @classmethod
    def create_index(cls, *args, **kwargs):
        """ Wrapper for collection create_index() """
        return cls._get_collection().create_index(*args, **kwargs)

    @classmethod
    def ensure_index(cls, *args, **kwargs):
        """ Wrapper for collection ensure_index() """
        return cls._get_collection().ensure_index(*args, **kwargs)

    @classmethod
    def drop_indexes(cls, *args, **kwargs):
        """ Wrapper for collection drop_indexes() """
        return cls._get_collection().drop_indexes(*args, **kwargs)

    @classmethod
    def distinct(cls, key):
        """ Wrapper for collection distinct() """
        return cls.find().distinct(key)

    # Map Reduce and Group methods eventually go here.

    @classmethod
    def _get_collection(cls):
        """ Connects and caches the collection connection object. """
        if not cls._collection:
            conn = Connection.instance()
            coll = conn.get_collection(cls._get_name())
            cls._collection = coll
        return cls._collection

    @classmethod
    def _get_name(cls):
        """
        Retrieves the collection name.
        Overwrite _name to set it manually.
        """
        if cls._name:
            return cls._name
        return cls.__name__.lower()

    def __eq__(self, other):
        """
        This method compares two objects names and id values.
        If they match, they are "equal".
        """
        if not isinstance(other, Model):
            return False
        this_id = self._get_id()
        other_id = other._get_id()
        if self.__class__.__name__ == other.__class__.__name__ and \
            this_id and other_id and \
            this_id == other_id:
            return True
        return False

    def __ne__(self, other):
        """ Returns the inverse of __eq__ ."""
        return not self.__eq__(other)

    # Friendly wrappers around collection
    @classmethod
    def count(cls):
        """ Just a wrapper for the collection.count() method. """
        return cls.find().count()

    @notinstancemethod
    def make_ref(cls, idval):
        """ Generates a DBRef for a given id. """
        if type(idval) != cls._id_type:
            # Casting to ObjectId (or str, or whatever is configured)
            idval = cls._id_type(idval)
        return DBRef(cls._get_name(), idval)

    def get_ref(self):
        """ Returns a DBRef for an document. """
        return DBRef(self._get_name(), self._get_id())

    def __repr__(self):
        return "<MogoModel:%s id:%s>" % (self._get_name(), self._get_id())
