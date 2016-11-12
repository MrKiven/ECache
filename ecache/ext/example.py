# -*- coding: utf-8 -*-

import random

from flask import Flask, jsonify
from flask_sqlalchemy import SQLAlchemy

from caching import CacheableMixin, query_callable, regions


app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:////tmp/test.db'
app.debug = True
db = SQLAlchemy(app)

FIRST_NAMES = (
    "JAMES", "JOHN", "ROBERT", "MICHAEL", "WILLIAM", "DAVID", "RICHARD", "CHARLES", "JOSEPH",
    "THOMAS", "CHRISTOPHER", "DANIEL", "PAUL", "MARK", "DONALD", "GEORGE", "KENNETH",
    "STEVEN", "EDWARD", "BRIAN", "RONALD", "ANTHONY", "KEVIN", "JASON", "MATTHEW", "GARY",
    "TIMOTHY", "JOSE", "LARRY", "JEFFREY", "FRANK", "SCOTT", "ERIC", "STEPHEN", "ANDREW",
    "RAYMOND", "GREGORY", "JOSHUA", "JERRY", "DENNIS", "WALTER", "PATRICK", "PETER", "HAROLD")

LAST_NAMES = (
    "SMITH", "JOHNSON", "WILLIAMS", "JONES", "BROWN", "DAVIS", "MILLER", "WILSON", "MOORE",
    "TAYLOR", "ANDERSON", "THOMAS", "JACKSON", "WHITE", "HARRIS", "MARTIN", "THOMPSON",
    "GARCIA", "MARTINEZ", "ROBINSON", "CLARK", "RODRIGUEZ", "LEWIS", "LEE", "WALKER", "HALL",
    "ALLEN", "YOUNG", "HERNANDEZ", "KING", "WRIGHT", "LOPEZ", "HILL", "SCOTT", "GREEN")

DOMAINS = ['gmail.com', 'yahoo.com', 'msn.com', 'facebook.com', 'aol.com', 'att.com']


class User(db.Model, CacheableMixin):
    cache_label = 'default'  # region's label to use
    cache_regions = regions
    query_class = query_callable(regions)

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80))
    email = db.Column(db.String(120))
    views = db.Column(db.Integer, default=0)

    def __init__(self, username, email):
        self.username = username
        self.email= email

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'views': self.views
        }

    def __repr__(self):
        return '<User %r>' % self.username

    __str__ = __repr__


@app.route('/users')
def all_users():
    users = [user.to_dict() for user in User.cache.filter()]
    return jsonify(users=users)


@app.route('/users/<int:user_id>')
def view_user(user_id):
    user = User.cache.get(user_id)
    return jsonify(user.to_dict())


@app.route('/update/<int:user_id>')
def update_user(user_id):
    user = User.cache.get(user_id)
    user.views += 1
    db.session.add(user)
    db.session.commit()
    return jsonify(user.to_dict())


def random_user():
    first_name = random.choice(FIRST_NAMES)
    last_name = random.choice(LAST_NAMES)
    email = '%s.%s@%s' % (first_name, last_name, random.choice(DOMAINS))
    return User(username='%s_%s' % (first_name, last_name), email=email)


@app.route('/init_db')
def init_db():
    db.drop_all()
    db.create_all()
    for i in range(50):
        db.session.add(random_user())
    db.session.commit()
    return 'DB initialized'


if __name__ == '__main__':
    app.run()
