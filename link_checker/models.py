import peewee
import config
import json


class Link(peewee.Model):
    start_url = peewee.TextField(index=True)
    url = peewee.TextField(index=True)
    parent = peewee.TextField(index=True)
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
        database = config.db  # This model uses the "people.db" databas


config.db.create_tables([Link])
