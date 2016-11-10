## Ecache for sqlalchemy

### Usage

```python
# -*- coding: utf-8 -*-

import redis
from sqlalchemy import (Column, Integer, String, SmallInteger)

from ecache import cache_mixin, db_manager, model_base

# alsosee :class:`ecache.db.DBManager`
DBSession = db_manager.get_session('test')
cache_client = redis.StrictRedis()
CacheMixin = cache_mixin()
DeclarativeBase = model_base()


class TodoListModel(DeclarativeBase, CacheMixin):
    __tablename__ == 'todo_list'
    TABLE_CACHE_EXPIRATION_TIME = 3600

    id = Column(Integer, primary_key=True)
    title = Column(String, default='')
    is_done = Column(SmallInteger, default=0)

    @classmethod
    def get_todo(cls, todo_id):
        todo = cls.get(todo_id)  # `cls.get` inherited from `CacheMixin`
        return todo

    @classmehod
    def add(cls, title):
        todo = cls(title=title)
        s = DBSession()
        s.add(todo)
        s.commit()
```
