# -*- coding: utf-8 -*-

import functools
import hashlib

from flask_sqlalchemy import BaseQuery
from sqlalchemy import event
from sqlalchemy.orm.interfaces import MapperOption
from sqlalchemy.orm.attributes import get_history
from sqlalchemy.ext.declarative import declared_attr
from dogpile.cache.region import make_region
from dogpile.cache.api import NO_VALUE


def md5_key_mangler(key):
    if key.startswith('SELECT '):
        key = hashlib.md5(key.encode('ascii')).hexdigest()
    return key


def memoize(obj):
    cache = obj.cache = {}

    @functools.wraps(obj)
    def memoizer(*args, **kwargs):
        key = str(args) + str(kwargs)
        if key not in cache:
            cache[key] = obj(*args, **kwargs)
        return cache[key]
    return memoizer


cache_config = {
    'backend': 'dogpile.cache.redis',
    'expiration_time': 3600  # 1 hour
}

regions = dict(
    default=make_region(key_mangler=md5_key_mangler).configure(**cache_config)
)


class CachingQuery(BaseQuery):

    def __init__(self, regions, entities, *args, **kwargs):
        self.cache_regions = regions
        super(CachingQuery, self).__init__(entities=entities, *args, **kwargs)

    def __iter__(self):
        if hasattr(self, '_cache_region'):
            return self.get_value(
                createfunc=lambda: list(super(CachingQuery, self).__iter__()))
        else:
            return super(CachingQuery, self).__iter__()

    def _get_cache_plus_key(self):
        dogpile_region = self.cache_regions[self._cache_region.region]
        if self._cache_region.cache_key:
            key = self._cache_region.cache_key
        else:
            key = _key_from_query(self)
        return dogpile_region, key

    def invalidated(self):
        dogpile_region, cache_key = self._get_cache_plus_key()
        dogpile_region.delete(cache_key)

    def get_value(self, merge=True, createfunc=None, expiration_time=None,
                  ignore_expiration=False):
        dogpile_region, cache_key = self._get_cache_plus_key()

        assert not ignore_expiration or not createfunc, \
            "Can't ignore expiration and also provide createfunc"

        if ignore_expiration or not createfunc:
            cached_value = dogpile_region.get(
                cache_key, expiration_time=expiration_time,
                ignore_expiration=ignore_expiration)
        else:
            cached_value = dogpile_region.get_or_create(
                cache_key, createfunc, expiration_time=expiration_time)

        if cached_value is NO_VALUE:
            raise KeyError(cache_key)
        if merge:
            cached_value = self.merge_result(cached_value, load=False)

        return cached_value

    def set_value(self, value):
        dogpile_region, cache_key = self._get_cache_plus_key()
        dogpile_region.set(cache_key, value)


def query_callable(regions, query_cls=CachingQuery):
    return functools.partial(query_cls, regions)


def _key_from_query(query, qualifier=None):
    stmt = query.with_labels().statement
    compiled = stmt.compile()
    params = compiled.params

    return ' '.join(
        [str(compiled)] + [str(params[k]) for k in sorted(params)]
    )


class FromCache(MapperOption):

    propagate_to_loaders = False

    def __init__(self, region='default', cache_key=None):
        self.region = region
        self.cache_key = cache_key

    def process_query(self, query):
        query._cache_region = self


class Cache(object):
    def __init__(self, model, regions, label):
        self.model = model
        self.regions = regions
        self.label = label
        self.pk = getattr(model, 'cache_pk', 'id')

    def get(self, pk):
        return self.model.query.options(self.from_cache(pk=pk)).get(pk)

    def filter(self, order_by='asc', offset=None, limit=None, **kwargs):
        query_kwargs = {}
        if kwargs:
            if len(kwargs) > 1:
                raise TypeError(
                    'filter accept only one attribute for filtering')
            key, value = kwargs.items()[0]
            if key not in self._columns():
                raise TypeError(
                    '%s does not have an attribute %s' % (self, key))
            query_kwargs[key] = value

        cache_key = self._cache_key(**kwargs)
        pks = self.regions[self.label].get(cache_key)

        if pks is NO_VALUE:
            pks = [
                o.id for o in self.model.query.filter_by(
                    **kwargs).with_entities(getattr(self.model, self.pk))]

        if order_by == 'desc':
            pks.reverse()

        if offset is not None:
            pks = pks[pks:]

        if limit is not None:
            pks = pks[:limit]

        keys = [self._cache_key(pk) for pk in pks]
        for pos, obj in enumerate(self.regions[self.label].get_multi(keys)):
            if obj is NO_VALUE:
                yield self.get(pks[pos])
            else:
                yield obj[0]

    def flush(self, key):
        self.regions[self.label].delete(key)

    @memoize
    def _columns(self):
        return [
            c.name for c in self.model.__table__.columns if c.name != self.pk]

    @memoize
    def from_cache(self, cachel_key=None, pk=None):
        if pk:
            cache_key = self._cache_key(pk)
        return FromCache(self.label, cache_key)

    @memoize
    def _cache_key(self, pk='all', **kwargs):
        q_filter = ''.join('%s=%s' % (k, v) for k, v in kwargs.items()) \
            or self.pk
        return "%s.%s[%s]" % (self.model.__table__, q_filter, pk)

    def _flush_all(self, obj):
        for column in self._columns():
            added, unchanged, deleted = get_history(obj, column)
            for value in list(deleted) + list(added):
                self.flush(self._cache_key(**{column: value}))
        self.flush(self._cache_key())
        self.flush(self._cache_key(getattr(obj, self.pk)))


class CacheableMixin(object):

    @declared_attr
    def cache(cls):
        return Cache(cls, cls.cache_regions, cls.cache_label)

    @staticmethod
    def _flush_event(mapper, connection, target):
        target.cache._flush_all(target)

    @classmethod
    def __declare_last__(cls):
        event.listen(cls, 'before_delete', cls._flush_event)
        event.listen(cls, 'before_update', cls._flush_event)
        event.listen(cls, 'before_insert', cls._flush_event)
