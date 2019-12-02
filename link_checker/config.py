import peewee

# Turn off journaling temporary to prevent 'peewee.OperationalError: database is locked'
# error in `web-access.py`.

# db = peewee.SqliteDatabase("history.sqlite", pragmas={"journal_mode": "off"})
# Connect to a MySQL database on network.
db = peewee.MySQLDatabase(
    "link_checker",
    user="link_checker",
    password="link_checker",
    host="localhost",
    port=3306,
    autoconnect=False,
)
