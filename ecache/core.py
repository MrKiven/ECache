# -*- coding: utf-8 -*-

import logging
import itertools
import redis

import sqlalchemy.exc as sa_exc
from sqlalchemy.orm.util import identity_key
from sqlalchemy.orm import attributes

from ecache.hook import EventHook

logger = logging.getLogger(__name__)

_dict2list = lambda ids, os: [os[i] for i in ids if i in os]


def make_transient_to_detached(instance):
    '''
    Moved from sqlalchemy newer version
    '''
    state = attributes.instance_state(instance)
    if state.session_id or state.key:
        raise sa_exc.InvalidRequestError(
            "Given object must be transient")
    state.key = state.mapper._identity_key_from_state(state)
    if state.deleted:
        del state.deleted
    state._commit_all(state.dict)
    state._expire_attributes(state.dict, state.unloaded)


class _Failed(object):
    def __get__(self, obj, type=None):
        raise NotImplementedError


class CacheMixinBase(object):

    RAWDATA_VERSION = None

    TABLE_CACHE_EXPIRATION_TIME = None

    _cache_client = _Failed()
    _db_session = _Failed()
    _update_cache_fail_callback = set()

    def __repr__(self):
        return "<%s|%s %s>" % (self.__tablename__, self.pk, hex(id(self)))

    @property
    def __rawdata__(self):
        return {c.name: getattr(self, c.name)
                for c in self.__table__.columns}

    @classmethod
    def gen_raw_key(cls, pk):
        """Generate raw key without namespace"""

        if cls.RAWDATA_VERSION:
            return "{0}|{1}|{2}".format(
                cls.__tablename__, pk, cls.RAWDATA_VERSION)
        return "{0}|{1}".format(cls.__tablename__, pk)

    @classmethod
    def pk_name(cls):
        """Get object primary key name. e.g. `id`"""
        if cls.__mapper__.primary_key:
            return cls.__mapper__.primary_key[0].name

    @property
    def pk(self):
        """Get object primary key.

        return: primary key value
        """
        return getattr(self, self.pk_name())

    @classmethod
    def pk_attribute(cls):
        """Get object primary key attribute.

        :return: sqlalchemy ``Column`` object of the primary key
        """
        if cls.__mapper__.primary_key:
            return getattr(cls, cls.pk_name())

    @classmethod
    def register_update_fail_callback(cls, callback, raise_exc=False):
        """Reigister callback.

        :param callback: func to callback
        :param raise_exc: whether to raise exception if occur, default to false
        """
        assert callable(callback), 'callback should be callable!'
        cls._update_cache_fail_callback.add((callback, raise_exc))

    @classmethod
    def clear_update_fail_callback(cls):
        """Clear all callbacks"""
        cls._update_cache_fail_callback.clear()

    @classmethod
    def _call_update_fail_callback(cls, key, val):
        """Call callbakc after update cache fail internal.

        :param key: primary key
        :param val: primary key value
        """
        for func, raise_exc in cls._update_cache_fail_callback:
            try:
                func(key, val)
            except Exception as e:
                if raise_exc:
                    raise
                logger.error(e)

    @classmethod
    def _miss(cls, pks):
        msg = "{}_update {}".format(cls.__tablename__,
                                    ' '.join(str(pk) for pk in pks))
        logger.debug(msg)

    @classmethod
    def _statsd_incr(cls, key, val=1):
        pass

    @classmethod
    def flush(cls, ids):
        keys = itertools.chain(*[
            cls.gen_raw_key(i) for i in ids])
        cls._cache_client.delete(*keys)

    @classmethod
    def from_cache(cls, rawdata):
        obj = cls(**rawdata)
        obj._cached = True
        make_transient_to_detached(obj)
        cls._db_session.add(obj)
        return obj

    @classmethod
    def get(cls, pk, force=False):
        if not force:
            ident_key = identity_key(cls, pk)
            if cls._db_session.identity_map and \
                    ident_key in cls._db_session.identity_map:
                return cls._db_session.identity_map[ident_key]

            try:
                cached_val = cls._cache_client.get(cls.gen_raw_key(pk))
                if cached_val:
                    cls._statsd_incr('hit')
                    return cls.from_cache(cached_val)
            except redis.ConnectionError as e:
                logger.error(e)
            except TypeError as e:
                logger.error(e)

        cls._statsd_incr('miss')

        obj = cls._db_session().query(cls).get(pk)
        if obj is not None:
            cls.set_raw(obj.__rawdata__)
        return obj

    @classmethod
    def mget(cls, pks, force=False, as_dict=False):
        if not pks:
            return {} if as_dict else []

        objs = {}
        if not force:
            if cls._db_session.identity_map:
                for pk in pks:
                    ident_key = identity_key(cls, pk)
                    if ident_key in cls._db_session.identity_map:
                        objs[pk] = cls._db_session.identity_map[identity_key]

            if len(pks) > len(objs):
                missed_pks = list(set(pks) - set(objs))
                vals = cls._cache_client.mget(cls.gen_raw_key(pk)
                                              for pk in missed_pks)
                if vals:
                    cached = {
                        k: cls.from_cache(v)
                        for k, v in zip(missed_pks, vals)
                        if v is not None
                    }
                    _hit_counts = len(cached)
                    cls._statsd_incr('hit', _hit_counts)
                    objs.update(cached)

        lack_pks = set(pks) - set(objs)
        if lack_pks:
            pk = cls.pk_attribute()
            if pk:
                lack_objs = cls._db_session().query(cls).\
                    filter(pk.in_(lack_pks)).all()
                if lack_objs:
                    cls.mset(lack_objs)

                cls._statsd_incr('miss', len(lack_objs))

                objs.update({obj.pk: obj} for obj in lack_objs)
            else:
                logger.warn("No pk found for %s, skip %s" %
                            cls.__tablename__, lack_pks)
        return objs if as_dict else _dict2list(pks, objs)

    @classmethod
    def set(cls, val, expiration_time=None):
        assert isinstance(val, cls)

        cls.set_raw(val.__rawdata__, expiration_time)

    @classmethod
    def set_raw(cls, val, expiration_time=None):
        if not val:
            return

        pk_name = cls.pk_name()
        ttl = expiration_time or cls.TABLE_CACHE_EXPIRATION_TIME
        key = cls.gen_raw_key(val[pk_name])
        return cls._cache_client.set(key, val, ttl)

    @classmethod
    def mset(cls, vals):
        if not vals:
            return

        assert isinstance(vals[0], cls)

        ttl = cls.TABLE_CACHE_EXPIRATION_TIME
        objs = {
            cls.gen_raw_key(val.pk): val.__rawdata__ for val in vals
        }
        return cls._cache_client.mset(objs, expiration_time=ttl)


def cache_mixin(cache, session):
    """CacheMixin factory"""

    hook = EventHook([cache], session)

    class _Cache(CacheMixinBase):
        _hook = hook

        _cache_client = cache
        _db_session = session
    return _Cache
