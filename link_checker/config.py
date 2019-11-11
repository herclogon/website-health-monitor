import peewee

db = peewee.SqliteDatabase("history.sqlite")
db.connect()
