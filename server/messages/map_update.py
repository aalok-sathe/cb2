from mashumaro.mixins.json import DataClassJSONMixin
from dataclasses import dataclass, field
from dataclasses_json import dataclass_json, config, LetterCase
from datetime import datetime
from hex import HexCell, HecsCoord
from marshmallow import fields
from typing import List

import datetime
import dateutil.parser
import typing
import messages.prop


@dataclass(frozen=True)
class Tile(DataClassJSONMixin):
    asset_id: int
    cell: HexCell
    rotation_degrees: int

@dataclass
class MapMetadata(DataClassJSONMixin):
    num_cities: int = 0
    num_lakes: int = 0
    num_mountains: int = 0
    num_outposts: int = 0
    num_partitions: int = 0

@dataclass(frozen=True)
class MapUpdate(DataClassJSONMixin):
    rows: int
    cols: int
    tiles: List[Tile]
    props: List[messages.prop.Prop]
    metadata: MapMetadata = field(default_factory=MapMetadata)
