# -*- coding: utf-8 -*-

from ecache.db import make_session, create_engine


MYSQL_SETTINGS = {
    "master": "mysql+pymysql://eleme:eleme@localhost:3306/test_ecache?charset=utf8",  # noqa
    "slave": "mysql+pymysql://eleme:eleme@localhost:3306/test_ecache?charset=utf8",  # noqa
}


engines = {
    role: create_engine(dsn, pool_size=10, max_overflow=-1, pool_recycle=1200)
    for role, dsn in MYSQL_SETTINGS.items()
}
engine = engines['master']

DBSession = make_session(engines, info={"name": "test"})
