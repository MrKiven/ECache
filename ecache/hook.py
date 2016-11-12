# -*- coding: utf-8 -*-

import logging
import itertools

from meepo.signals import signal
from meepo.apps.eventsourcing import sqlalchemy_es_pub


class EventHook(sqlalchemy_es_pub):

    def __init__(self, cache_clients, session, tables=None):
        super(EventHook, self).__init__(session, tables)

        self.cache_clients = cache_clients
        self.logger = logging.getLogger(__name__)

    def add(self, model):
        tablename = model.__tablename__
        self.tables.add(tablename)

        self.install_cache_signal(tablename)

        self.logger.info("cache set hook enabled for table: {}".format(
            tablename))

    def install_cache_signal(self, table):
        rawdata_event = "{}_rawdata".format(table)
        delete_event = "{}_delete_raw".format(table)

        signal(rawdata_event).connect(self._rawdata_sub, weak=False)
        signal(delete_event).connect(self._delete_sub, weak=False)

    def _rawdata_sub(self, raw_obj, model):
        pk_name = model.pk_name()
        tablename = model.__tablename__
        pk = raw_obj[pk_name]

        model.set_raw(raw_obj)

        self.logger.info("set raw data cache for {} {}".format(tablename, pk))

    def _delete_sub(self, obj):
        obj.flush([obj.pk])

        self.logger.info("delete cache for {} {}".format(
            obj.__tablename__, obj.pk))

    def session_prepare(self, session, _):
        super(EventHook, self).session_prepare(session, _)

        if hasattr(session, 'pending_rawdata'):
            session.pending_rawdata = {}

        for obj in itertools.chain(session.pending_write,
                                   session.pending_update):
            if obj.__tablename__ not in self.tables:
                continue

            key = obj.pk, obj.__tablename__

            session.pending_rawdata[key] = obj.__rawdata__, obj.__class__

    def session_commit(self, session):
        if hasattr(session, 'pending_rawdata'):
            self._pub_cache_events("rawdata", session.pending_rawdata)

        super(EventHook, self).session_commit(session)

    def session_rollback(self, session):
        if hasattr(session, 'pending_rawdata'):
            del session.pending_rawdata

        super(EventHook, self).session_rollback(session)

    def _pub_cache_events(self, event_type, objs):
        if not objs:
            return

        for obj, model in objs.values():
            sg_name = "{}_{}".format(model.__tablename__, event_type)
            signal(sg_name).send(obj, model=model)
