Ecache for sqlalchemy
=====================


Run test
--------

.. code:: bash

    make unittest


Installation / Rquirements
--------------------------

.. code::

    pip intall ecache


Usage
-----

With Flask Integrate
~~~~~~~~~~~~~~~~~~~~

.. code:: python

    from flask import Flask, jsonify
    from flask_sqlalchemy import SQLAlchemy

    from ecache.ext.flask_cache import CacheableMixin, query_callable, regions

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'
    app.debug = True
    db = SQLAlchemy(app)

    class User(db.Model, CacheableMixin):
        """Default backend is redis and expiration time is 1 hour, default
        region name is `default`, you can override this:

            cache_regions = your_regions
            cache_label = your_label
        """

        id = db.Column(db.Integer, primary_key=True)
        name = db.Column(db.String)

    @app.route('/users')
    def all_users():
        """Result will try to get from cache first. load from db if cache miss.
        """
        users = [user.to_dict() for user in User.cache.filter()]
        return jsonify(users=users)


    @app.route('/users/<int:user_id')
    def view_user(user_id):
        """Result will try to get from cache first. load from db if cache miss.
        """
        user = User.cache.get(user_id)
        return jsonify(user.to_dict())

More detail see `example`_

.. _`example`: https://github.com/MrKiven/ECache/blob/master/ecache/ext/example.py


With Pure SQLAlchemy model Integrate
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: python

    # -*- coding: utf-8 -*-

    import redis
    from sqlalchemy import (Column, Integer, String, SmallInteger)

    from ecache.core import cache_mixin
    from ecache.db import db_manager, model_base

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

        @classmethod
        def add(cls, title):
            todo = cls(title=title)
            s = DBSession()
            s.add(todo)
            s.commit()
