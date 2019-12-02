import json

import peewee

from . import config


class Link(peewee.Model):
    start_url = peewee.TextField()
    url = peewee.TextField()
    parent = peewee.TextField()
    duration = peewee.IntegerField(null=True)
    size = peewee.IntegerField(null=True)
    content_type = peewee.CharField(null=True)
    response_code = peewee.IntegerField(null=True)
    response_reason = peewee.TextField(null=True)
    date = peewee.DateTimeField(null=True)

    def json(self):
        r = {}
        for k in self.__data__.keys():
            try:
                r[k] = str(getattr(self, k))
            except:
                r[k] = json.dumps(getattr(self, k))
        return r

    class Meta:
        database = config.db

        indexes = (
            peewee.SQL("create index url_idx on link (url(256))"),
            peewee.SQL("create index parent_idx on link (parent(256))"),
            peewee.SQL(
                "create index response_code_start_url_idx on "
                "link (response_code, start_url(256))"
            ),
            peewee.SQL(
                "create index parent_start_url_idx on "
                "link (parent(256), start_url(256))"
            ),
        )


# Ensure that model's table exists.
try:
    config.db.connect()
    config.db.create_tables([Link])
finally:
    config.db.close()
