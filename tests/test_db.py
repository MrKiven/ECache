# -*- coding: utf-8 -*-

import ecache.db as db
from tests.conftest import engines


def test_session_stack():
    DBSession = db.make_session(engines, force_scope=True)
    session1 = DBSession()

    with db.session_stack():
        session2 = DBSession()
        session2.close()
        with db.session_stack():
            session3 = DBSession()
            session3.close()
        session1.close()

    assert not (session1 is session2 is session3)
