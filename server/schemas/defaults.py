from server.schemas.base import *
from server.schemas.cards import *
from server.schemas.clients import *
from server.schemas.game import *
from server.schemas.map import *
from server.schemas.mturk import *
from server.schemas.leaderboard import *
from server.schemas.prop import *

TABLES = [
    CardSets, Card, CardSelections,
    Remote, ConnectionEvents,
    Game, Turn, Instruction, Move, LiveFeedback,
    MapUpdate, PropUpdate,
    Worker, Assignment, WorkerExperience,
    Leaderboard, Username
]

def ListDefaultTables():
    return TABLES