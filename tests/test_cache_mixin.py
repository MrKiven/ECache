# -*- coding: utf-8 -*-

from redis import StrictRedis
import pytest
import mock
import sqlalchemy as sa

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker

from ecache.core import CacheMixinBase, make_transient_to_detached


from tests.conftest import engines


Base = declarative_base()


class MockSession(object):
    identity_map = []

    def __init__(self, return_value):
        self.return_value = return_value

    def all(self):
        return self.return_value

    def get(self, *args):
        return self.return_value

    def __getattr__(self, attr):
        return self

    def __call__(self, *args):
        return self


class CacheMixin(CacheMixinBase):
    _cache_client = StrictRedis()
    _db_session = None


class UserModel(object):

    def __init__(self, id=None, name=None):
        self.id = id
        self.name = name


@pytest.fixture
def DBSession():
    return scoped_session(sessionmaker(engines['master'], info={'name': 'test'}))


class User(Base, CacheMixin):
    __tablename__ = 'user'

    id = sa.Column(sa.Integer, primary_key=True)
    name = sa.Column(sa.String)


def test_set_raw():
    u = User(id=0, name='hello')

    with mock.patch.object(StrictRedis, 'set') as mock_set:
        User.set_raw(u.__rawdata__, expiration_time=900)

    mock_set.assert_called_with("user|0", {"id": 0, "name": "hello"}, 900)


def test_set(monkeypatch):
    u = User(id=0, name='hello')

    set_raw_mock = mock.Mock()

    monkeypatch.setattr(User, "set_raw", set_raw_mock)

    User.set(u, expiration_time=900)

    assert set_raw_mock.called


def test_mset(monkeypatch):
    u1 = User(id=0, name='hello')
    u2 = User(id=1, name='world')

    with mock.patch.object(StrictRedis, 'mset') as mock_mset:
        User.mset([u1, u2])

    mock_mset.assert_called_with(
        {"user|0": u1.__rawdata__, "user|1": u2.__rawdata__},
        expiration_time=User.TABLE_CACHE_EXPIRATION_TIME
    )


def test_get_from_session(monkeypatch, DBSession):
    session = DBSession()

    monkeypatch.setattr(CacheMixin, '_db_session', session)
    user = User(id=0, name="hello")
    make_transient_to_detached(user)
    session.add(user)
    u = User.get(0)
    assert u is user
    session.close()


def test_get_from_cache(monkeypatch, DBSession):
    monkeypatch.setattr(CacheMixin, "_db_session", DBSession)

    u = User(id=0, name="hello")
    with mock.patch.object(StrictRedis, "get", return_value=u.__rawdata__):
        m = User.get(0)
        assert m._cached


def test_get_from_db(monkeypatch):
    u = User(id=0, name="hello")
    mock_set = mock.Mock()

    monkeypatch.setattr(StrictRedis, "get", mock.Mock(return_value=None))
    monkeypatch.setattr(CacheMixin, "_db_session", MockSession(u))
    monkeypatch.setattr(StrictRedis, "set", mock_set)

    r = User.get(0)
    assert r is u

    mock_set.assert_called_with("user|0", {'id': 0, 'name': 'hello'}, None)
