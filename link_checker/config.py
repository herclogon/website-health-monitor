import peewee

# Turn off journaling temporary to prevent 'peewee.OperationalError: database is locked'
# error in `web-access.py`.
db = peewee.SqliteDatabase("history.sqlite", pragmas={"journal_mode": "off"})
db.connect()
