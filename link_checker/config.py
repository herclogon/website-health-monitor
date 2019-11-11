import peewee

db = peewee.SqliteDatabase("history.sqlite", pragmas={"journal_mode": "off"})
db.connect()
