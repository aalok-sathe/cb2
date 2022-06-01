from enum import Enum
from hex import HecsCoord

from dataclasses import dataclass, field, replace
from dataclasses_json import dataclass_json, config, LetterCase
from datetime import datetime
from marshmallow import fields

import dateutil.parser

class ActionType(Enum):
    INIT = 0
    INSTANT = 1
    ROTATE = 2
    TRANSLATE = 3
    OUTLINE = 4
    DEATH = 5

class AnimationType(Enum):
    NONE = 0
    IDLE = 1
    WALKING = 2
    INSTANT = 3
    TRANSLATE = 4
    ACCEL_DECEL = 5
    SKIPPING = 6
    ROTATE = 7

@dataclass_json
@dataclass(frozen=True)
class Color:
    r: float
    g: float
    b: float
    a: float

    def __eq__(self, rhs):
        return self.r == rhs.r and self.g == rhs.g and self.b == rhs.b and self.a == rhs.a


def CensorActionForFollower(action, follower):
    """ Censors actions to hide information that followers aren't supposed to see.
    
        For now, replaces red border colors with blue.
    """
    if action.border_color == Color(1, 0, 0, 1):
        action = replace(action, border_color=Color(0, 0, 1, 1))
        print(f"Censored action {action} for follower {follower}")
    return action

@dataclass_json
@dataclass(frozen=True)
class Action:
    id: int
    action_type: ActionType
    animation_type: AnimationType
    displacement: HecsCoord  # For TRANSLATE, INIT, and INSTANT actions.
    rotation: float  # For rotations. In Degrees.
    border_radius: float
    border_color: Color
    duration_s: float
    expiration: datetime = field(
        metadata=config(
            encoder=datetime.isoformat,
            decoder=dateutil.parser.isoparse,
            mm_field=fields.DateTime(format='iso')
        ))


def Turn(id, angle):
    return Action(
        id=id,
        action_type=ActionType.ROTATE,
        animation_type=AnimationType.ROTATE,
        displacement=HecsCoord(0, 0),
        rotation=angle,
        border_radius=0,
        border_color=Color(0, 0, 0, 0),
        duration_s=0,
        expiration=datetime.now() + datetime.timedelta(seconds=10)
    )

def Walk(id, displacement):
    return Action(
        id=id,
        action_type=ActionType.TRANSLATE,
        animation_type=AnimationType.WALKING,
        displacement=displacement,
        rotation=0,
        border_radius=0,
        border_color=Color(0, 0, 0, 0),
        duration_s=0,
        expiration=datetime.now() + datetime.timedelta(seconds=10)
    )