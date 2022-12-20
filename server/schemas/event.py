import datetime
import uuid
from enum import IntEnum

from peewee import DateTimeField, ForeignKeyField, IntegerField, TextField, UUIDField

from server.schemas.base import BaseModel
from server.schemas.game import Game
from server.schemas.util import HecsCoordField


class EventOrigin(IntEnum):
    NONE = 0
    LEADER = 1
    FOLLOWER = 1
    SERVER = 2


class EventType(IntEnum):
    NONE = 0
    MAP_UPDATE = 1
    INITIAL_STATE = 2
    TURN_STATE = 3
    PROP_UPDATE = 4
    CARD_SPAWN = 5
    CARD_SELECT = 6
    CARD_SET = 7
    INSTRUCTION_SENT = 8
    INSTRUCTION_ACTIVATED = 9
    INSTRUCTION_DONE = 10
    INSTRUCTION_CANCELLED = 11
    MOVE = 12
    LIVE_FEEDBACK = 13


class Event(BaseModel):
    id = UUIDField(primary_key=True, default=uuid.uuid4, unique=True)
    game = ForeignKeyField(Game, backref="events")
    type = IntegerField(default=EventType.NONE)
    tick = IntegerField()
    server_time = DateTimeField(default=datetime.datetime.utcnow)
    # Determined by packet transmissions time. Nullable.
    client_time = DateTimeField(null=True)
    # Who triggered the event.
    origin = IntegerField(default=EventOrigin.NONE)
    # Who's turn it is, currently.
    role = TextField(default="")  # 'Leader' or 'Follower'
    # If an event references a previous event, it is linked here.
    # Moves may have an instruction as their parent.
    # Live feedbacks may have a move as their parent.
    # For instruction-related events, it always points to the initial INSTRUCTION_SENT event for that instruction.
    parent_event = ForeignKeyField("self", backref="children", null=True)
    data = TextField(null=True)
    # If the event has a brief/compressed representation, include it here. For
    # moves, this is the action code (MF/MB/TL/TR).
    # If this is an instruction-related event, it's the instruction's UUID.
    short_code = TextField(null=True)
    # If applicable, the "location" of an event. For moves, this is the location *before* the action occurred.
    # For live feedback, this is the follower location during the live feedback.
    location = HecsCoordField(null=True)
    # If applicable, the "orientation" of the agent. For moves, this is the location *before* the action occurred.
    # For live feedback, this is the follower orientation during the live feedback.
    orientation = IntegerField(null=True)
