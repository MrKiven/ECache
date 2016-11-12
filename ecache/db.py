# -*- coding: utf-8 -*-

import logging
import uuid
import random
import threading
import contextlib
import os
import time
import sha
import gevent

from sqlalchemy import event
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.orm import Session, scoped_session, sessionmaker


db_ctx = threading.local()
logger = logging.getLogger(__name__)


class RoutingSession(Session):
    _name = None

    def __init__(self, engines, *args, **kwargs):
        super(RoutingSession, self).__init__(*args, **kwargs)
        self.engines = engines
        self.slave_engines = [e for role, e in engines.iteritems()
                              if role != 'master']
        assert self.slave_engines, ValueError('DB slave config is wrong!')
        self._id = self.gen_id()

    def get_bind(self, mapper=None, clause=None):
        if self._name:
            return self.engines[self._name]
        elif self._flushing:
            return self.engines['master']
        else:
            return random.choice(self.slave_engines)

    def using_bind(self, name):
        self._name = name
        return self

    def gen_id(self):
        pid = os.getpid()
        tid = threading.current_thread().ident
        clock = time.time() * 1000
        address = id(self)
        hash_key = self.hash_key
        return sha.new('{0}\0{1}\0{2}\0{3}\0{4}'.format(
            pid, tid, clock, address, hash_key)).hexdigest()[:20]

    def rollback(self):
        with gevent.Timeout(5):
            super(RoutingSession, self).rollback()

    def close(self):
        current_transactions = tuple()
        if self.transaction is not None:
            current_transactions = self.transaction._iterate_parents()
        try:
            with gevent.Timeout(5):
                super(RoutingSession, self).close()
        # pylint: disable=E0712
        except gevent.Timeout:
            # pylint: enable=E0712
            close_connections(self.engines.itervalues(), current_transactions)
            raise


class RecycleField(object):
    def __get__(self, instance, klass):
        if instance is not None:
            return int(random.uniform(0.75, 1) * instance._origin_recyle)
        raise AttributeError


class ModelMeta(DeclarativeMeta):
    def __new__(self, name, bases, attrs):
        cls = DeclarativeMeta.__new__(self, name, bases, attrs)

        from core import CacheMixinBase
        for base in bases:
            if issubclass(base, CacheMixinBase) and hasattr(cls, "_hook"):
                cls._hook.add(cls)
                break
        return cls


def model_base():
    """Construct a base class for declarative class definitions"""
    return declarative_base(metaclass=ModelMeta)


def patch_engine(engine):
    pool = engine.pool
    pool._origin_recyle = pool._recycle
    del pool._recycle
    setattr(pool.__class__, '_recycle', RecycleField())
    return engine


def scope_func():
    if not hasattr(db_ctx, 'session_stack'):
        db_ctx.session_stack = 0
    return (threading.current_thread().ident, db_ctx.session_stack)


def make_session(engines, force_scope=False, info=None):
    if force_scope:
        scopefunc = scope_func
    else:
        scopefunc = None

    session = scoped_session(
        sessionmaker(
            class_=RoutingSession,
            expire_on_commit=False,
            engines=engines,
            info=info or {"name": uuid.uuid4().hex},
        ),
        scopefunc=scopefunc
    )
    return session


def create_engine(*args, **kwds):
    engine = patch_engine(sqlalchemy_create_engine(*args, **kwds))
    event.listen(engine, 'before_cursor_execute', sql_commenter,
                 retval=True)
    return engine


@contextlib.contextmanager
def session_stack():
    if not hasattr(db_ctx, 'session_stack'):
        db_ctx.session_stack = 0

    try:
        db_ctx.session_stack += 1
        yield
    finally:
        db_ctx.session_stack -= 1


def close_connections(engines, transactions):
    if engines and transactions:
        for engine in engines:
            for parent in transactions:
                conn = parent._connections.get(engine)
                if conn:
                    conn = conn[0]
                    conn.invalidate()


def sql_commenter(conn, cursor, statement, params, context, executemany):
    pass


class DBManager(object):
    def __init__(self):
        self.session_map = {}

    def create_sessions(self, settings):
        """settings example
DB_SETTINGS = {
    'test': {
        'urls': {
            'master': mysql+pymysql://root@localhost:3306/test?charset=utf8,
            'slave': mysql+pymysql://root@localhost:3306/test?charset=utf8
        },
        'max_overflow': -1,
        'pool_size': 10,
        'pool_recycle': 1200
    }
}
        """
        if not settings.DB_SETTINGS:
            raise ValueError('DB_SETTINGS is empty, check it')
        for db, db_configs in settings.DB_SETTINGS.iteritems():
            self.add_session(db, db_configs)

    def get_session(self, name):
        try:
            return self.session_map[name]
        except KeyError:
            raise KeyError(
                '`%s` session not created, check `DB_SETTINGS`' % name)

    def add_session(self, name, config):
        if name in self.session_map:
            raise ValueError("Duplicate session name {},"
                             "please check your config".format(name))
        session = self._make_session(name, config)
        self.session_map[name] = session
        return session

    @classmethod
    def _make_session(cls, db, config):
        urls = config['urls']
        for name, url in urls.iteritems():
            assert url, "Url configured not properly for %s:%s" % (db, name)
        pool_size = config.get('pool_size', 10)
        max_overflow = config.get('max_overflow', 1)
        pool_recycle = 300
        engines = {
            role: cls.create_engine(dsn,
                                    pool_size=pool_size,
                                    max_overflow=max_overflow,
                                    pool_recycle=pool_recycle,
                                    execution_options={'role': role})
            for role, dsn in urls.iteritems()
        }
        return make_session(engines, info={"name": db})

    def close_sessions(self, should_close_connection=False):
        dbsessions = self.session_map
        for dbsession in dbsessions.itervalues():
            if should_close_connection:
                session = dbsession()
                if session.transaction is not None:
                    close_connections(session.engines.itervalues(),
                                      session.transaction._iterate_parents())
            try:
                dbsession.remove()
            except:
                logger.exception("Error closing session")

    @classmethod
    def create_engine(cls, *args, **kwds):
        engine = patch_engine(sqlalchemy_create_engine(*args, **kwds))
        event.listen(engine, 'before_cursor_execute', sql_commenter,
                     retval=True)
        return engine


db_manager = DBManager()
