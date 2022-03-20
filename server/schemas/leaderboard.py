import datetime
from peewee import *
from schemas.base import *
from schemas.mturk import Worker

class Username(BaseModel):
    username = TextField()
    worker = ForeignKeyField(Worker, backref='username')

class Leaderboard(BaseModel):
    time = DateTimeField(default=datetime.datetime.now)
    score = IntegerField()
    leader = ForeignKeyField(Worker, null=True, backref='leaderboard_entries')
    follower = ForeignKeyField(Worker, null=True, backref='leaderboard_entries')
