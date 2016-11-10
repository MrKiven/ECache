# -*- coding: utf-8 -*-

from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta


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
