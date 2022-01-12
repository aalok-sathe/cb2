from actor import Actor
from assets import AssetId
from messages.action import Action, Color, ActionType
from messages.rooms import Role
from messages import message_from_server
from messages import message_to_server
from messages import objective, state_sync
from hex import HecsCoord
from queue import Queue
from map_provider import MapProvider, MapType
from card import CardSelectAction
from util import IdAssigner
from datetime import datetime, timedelta
from messages.turn_state import TurnState, GameOverMessage, TurnUpdate

import aiohttp
import asyncio
import dataclasses
import logging
import math
import random
import time
import uuid

LEADER_MOVES_PER_TURN = 5
FOLLOWER_MOVES_PER_TURN = 10

logger = logging.getLogger()

class State(object):
    def __init__(self, room_id):
        self._room_id = room_id
        self._id_assigner = IdAssigner()

        # Logging init.
        self._recvd_log = logging.getLogger(f'room_{room_id}.recv')
        self._record_log = logging.getLogger(f'room_{room_id}.log')
        self._sent_log = logging.getLogger(f'room_{room_id}.sent')
        self._recvd_log.info("State created.")
        self._record_log.info("State created.")
        self._sent_log.info("State created.")

        # Maps from actor_id (prop id) to actor object (see definition below).
        self._actors = {}

        # Map props and actors share IDs from the same pool, so the ID assigner
        # is shared to prevent overlap.
        self._map_provider = MapProvider(MapType.RANDOM, self._id_assigner)
        
        self._objectives = []
        self._objectives_stale = {}  # Maps from player_id -> bool if their objective list is stale.

        self._map_update = self._map_provider.map()
        self._map_stale = {} # Maps from player_id -> bool if their map is stale.

        self._synced = {}
        self._action_history = {}
        self._last_tick = datetime.now() # Used to time 1s ticks for turn state updates.
        initial_turn = TurnUpdate(
            Role.LEADER, LEADER_MOVES_PER_TURN, 6,
            datetime.now() + self.turn_duration(Role.LEADER),
            datetime.now(), 0, 0)
        self._turn_history = {}
        self.record_turn_state(initial_turn)

        self._spawn_points = self._map_provider.spawn_points()
        random.shuffle(self._spawn_points)
        self._done = False

    def turn_duration(self, role):
        return timedelta(seconds=60) if role == Role.LEADER else timedelta(seconds=45)

    def record_turn_state(self, turn_state):
        # Record a copy of the current turn state.
        self._record_log.info(turn_state)
        self._turn_state = turn_state
        for actor_id in self._actors:
            if not actor_id in self._turn_history:
                self._turn_history[actor_id] = Queue()
            self._turn_history[actor_id].put(
                dataclasses.replace(turn_state))

    def drain_turn_state(self, actor_id):
        if not actor_id in self._turn_history:
            self._turn_history[actor_id] = Queue()
        if self._turn_history[actor_id].empty():
            return None
        turn = self._turn_history[actor_id].get()
        self._sent_log.info(f"to: {actor_id} turn_state: {turn}")
        return turn

    def end_game(self):
        logging.info(f"Game ending.")
        self._done = True

    def record_action(self, action):
        # Marks an action as validated (i.e. it did not conflict with other actions).
        # Queues this action to be sent to each user.
        self._record_log.info(action)
        for id in self._actors:
            actor = self._actors[id]
            self._action_history[actor.actor_id()].append(action)

    def map(self):
        return self._map_provider.map()

    def cards(self):
        self._map_provider.cards()
    
    def done(self):
        return self._done

    async def update(self):
        last_loop = time.time()
        current_set_invalid = False
        while not self._done:
            await asyncio.sleep(0.001)
            poll_period = time.time() - last_loop
            if (poll_period) > 0.1:
                logging.warn(
                    f"Game {self._room_id} slow poll period of {poll_period}s")
            last_loop = time.time()

            # Check to see if the game is out of time.
            if self._turn_state.turns_left == -1:
                logging.info(
                    f"Game {self._room_id} is out of turns. Game over!")
                game_over_message = GameOverMessage(
                    self._turn_state.game_start, self._turn_state.sets_collected, self._turn_state.score)
                self.record_turn_state(game_over_message)
                self.end_game()
                continue

            # Recalculate the turn state with the remaining game time.
            if datetime.now() > self._last_tick + timedelta(milliseconds=1000):
                self._last_tick = datetime.now()
                turn_update = TurnUpdate(self._turn_state.turn,
                                         self._turn_state.moves_remaining,
                                         self._turn_state.turns_left,
                                         self._turn_state.turn_end,
                                         self._turn_state.game_start,
                                         self._turn_state.sets_collected,
                                         self._turn_state.score)
                self.record_turn_state(turn_update)
            
            if datetime.now() >= self._turn_state.turn_end:
                self.end_turn_if_over()

            # Handle actor actions.
            for actor_id in self._actors:
                actor = self._actors[actor_id]
                if actor.has_actions():
                    logger.info(f"Actor {actor_id} has pending actions.")
                    proposed_action = actor.peek()
                    if not self._turn_state.turn == actor.role():
                        actor.drop()
                        self.desync(actor_id)
                        logger.info(
                            f"Actor {actor_id} is not the current role. Dropping pending action.")
                        continue
                    if self._turn_state.moves_remaining == 0:
                        actor.drop()
                        self.desync(actor_id)
                        logger.info(
                            f"Actor {actor_id} is out of moves. Dropping pending action.")
                        continue
                    if self.valid_action(actor_id, proposed_action):
                        actor.step()
                        self.record_action(proposed_action)
                        color = Color(0, 0, 1, 1) if not current_set_invalid else Color(1, 0, 0, 1)
                        self.check_for_stepped_on_cards(actor_id, proposed_action, color)
                        self.end_turn_if_over()
                    else:
                        actor.drop()
                        self.desync(actor_id)
                        self._record_log.error(f"Resyncing {actor_id} after invalid action.")
                        continue

            selected_cards = list(self._map_provider.selected_cards())
            cards_changed = False
            if self._map_provider.selected_cards_collide() and not current_set_invalid:
                current_set_invalid = True
                self._record_log.info("Invalid set detected.")
                cards_changed = True
                # Indicate invalid set.
                for card in selected_cards:
                    # Outline the cards in red.
                    card_select_action = CardSelectAction(card.id, True, Color(1, 0, 0, 1))
                    self.record_action(card_select_action)
            
            if not self._map_provider.selected_cards_collide() and current_set_invalid:
                logger.info("Marking set as clear (not invalid) because it is smaller than 3.")
                current_set_invalid = False
                cards_changed = True
                for card in selected_cards:
                    # Outline the cards in blue.
                    card_select_action = CardSelectAction(card.id, True, Color(0, 0, 1, 1))
                    self.record_action(card_select_action)

            if self._map_provider.selected_valid_set():
                self._record_log.info("Unique set collected. Awarding points.")
                current_set_invalid = False
                added_turns = 0
                cards_changed = True
                if self._turn_state.sets_collected == 0:
                    added_turns = 5
                elif self._turn_state.sets_collected in [1, 2]:
                    added_turns = 4
                elif self._turn_state.sets_collected in [3, 4]:
                    added_turns = 3
                new_turn_state = TurnUpdate(
                    self._turn_state.turn,
                    self._turn_state.moves_remaining,
                    self._turn_state.turns_left + added_turns,
                    self._turn_state.turn_end,
                    self._turn_state.game_start,
                    self._turn_state.sets_collected + 1,
                    self._turn_state.score + 1)
                self.record_turn_state(new_turn_state)
                # Clear card state and remove the cards in the winning set.
                logging.info("Clearing selected cards")
                for card in selected_cards:
                    self._map_provider.set_selected(card.id, False)
                    card_select_action = CardSelectAction(card.id, False)
                    self.record_action(card_select_action)
                    self._map_provider.remove_card(card.id)
                self._map_provider.add_random_cards(3)

            if cards_changed:
                # We've changed cards, so we need to mark the map as stale for all players.
                self._map_update = self._map_provider.map()
                for actor_id in self._actors:
                    self._map_stale[actor_id] = True

    def end_turn_if_over(self, force_turn_end=False):
        opposite_role = Role.LEADER if self._turn_state.turn == Role.FOLLOWER else Role.FOLLOWER
        end_of_turn = (datetime.now() >= self._turn_state.turn_end) or force_turn_end
        next_role = opposite_role if end_of_turn else self._turn_state.turn
        moves_remaining = self.moves_per_turn(
            next_role) if end_of_turn else max(self._turn_state.moves_remaining - 1, 0)
        turns_left = self._turn_state.turns_left - 1 if end_of_turn else self._turn_state.turns_left
        turn_end = datetime.now() + self.turn_duration(next_role) if end_of_turn else self._turn_state.turn_end
        turn_update = TurnUpdate(
            next_role,
            moves_remaining,
            turns_left,
            turn_end,
            self._turn_state.game_start,
            self._turn_state.sets_collected,
            self._turn_state.score)
        self.record_turn_state(turn_update)

    def moves_per_turn(self, role):
        return LEADER_MOVES_PER_TURN if role == Role.LEADER else FOLLOWER_MOVES_PER_TURN
    
    def turn_state(self):
        return self._turn_state

    def calculate_score(self):
        self._turn_state.score = self._turn_state.sets_collected * 100
    
    def selected_cards(self):
        return list(self._map_provider.selected_cards())

    def check_for_stepped_on_cards(self, actor_id, action, color):
        actor = self._actors[actor_id]
        stepped_on_card = self._map_provider.card_by_location(
            actor.location())
        # If the actor just moved and stepped on a card, mark it as selected.
        if (action.action_type == ActionType.TRANSLATE) and (stepped_on_card is not None):
            logger.info(
                f"Player {actor.actor_id()} stepped on card {str(stepped_on_card)}.")
            selected = not stepped_on_card.selected
            self._map_provider.set_selected(
                stepped_on_card.id, selected)
            card_select_action = CardSelectAction(stepped_on_card.id, selected, color)
            self.record_action(card_select_action)

    def handle_packet(self, id, message):
        if message.type == message_to_server.MessageType.ACTIONS:
            logger.info(f'Actions received. Room: {self._room_id}')
            for action in message.actions:
                logger.info(f'{action.id}:{action.displacement}')
                self.handle_action(id, action)
        elif message.type == message_to_server.MessageType.OBJECTIVE:
            logger.info(
                f'Objective received. Room: {self._room_id}, Text: {message.objective.text}')
            self.handle_objective(id, message.objective)
        elif message.type == message_to_server.MessageType.OBJECTIVE_COMPLETED:
            logger.info(
                f'Objective Compl received. Room: {self._room_id}, Text: {message.objective_complete.uuid}')
            self.handle_objective_complete(id, message.objective_complete)
        elif message.type == message_to_server.MessageType.TURN_COMPLETE:
            logger.info(f'Turn Complete received. Room: {self._room_id}')
            self.handle_turn_complete(id, message.turn_complete)
        elif message.type == message_to_server.MessageType.STATE_SYNC_REQUEST:
            logger.info(
                f'Sync request recvd. Room: {self._room_id}, Player: {id}')
            self.desync(id)
        else:
            logger.warn(f'Received unknown packet type: {message.type}')

    def handle_action(self, actor_id, action):
        if (action.id != actor_id):
            self.desync(actor_id)
            return
        self._recvd_log.info(action)
        self._actors[actor_id].add_action(action)

    def handle_objective(self, id, objective):
        if self._actors[id].role() != Role.LEADER:
            logger.warn(
                f'Warning, objective received from non-leader ID: {str(id)}')
            return
        # TODO: Make UUID and non-UUID'd objectives separate message types.
        objective.uuid = uuid.uuid4().hex
        self._recvd_log.info(objective)
        self._objectives.append(objective)
        for actor_id in self._actors:
            self._objectives_stale[actor_id] = True

    def handle_objective_complete(self, id, objective_complete):
        if self._actors[id].role() != Role.FOLLOWER:
            logger.warn(
                f'Warning, obj complete received from non-follower ID: {str(id)}')
            return
        self._recvd_log.info(objective_complete)
        for i, objective in enumerate(self._objectives):
            if objective.uuid == objective_complete.uuid:
                self._record_log.info(objective_complete)
                self._objectives[i].completed = True
                break
        for actor_id in self._actors:
            self._objectives_stale[actor_id] = True
    
    def handle_turn_complete(self, id, turn_complete):
        if self._actors[id].role() != self._turn_state.turn:
            logger.warn(
                f"Warning, turn complete received from ID: {str(id)} when it isn't their turn!")
            return
        self._recvd_log.info(f"player_id: {id} turn_complete received.")
        self.end_turn_if_over(force_turn_end=True)

    def create_actor(self, role):
        spawn_point = self._spawn_points.pop() if self._spawn_points else HecsCoord(0, 0, 0)
        asset_id = AssetId.PLAYER if role == Role.LEADER else AssetId.FOLLOWER_BOT
        actor = Actor(self._id_assigner.alloc(), asset_id, role, spawn_point)
        self._actors[actor.actor_id()] = actor
        self._action_history[actor.actor_id()] = []
        self._synced[actor.actor_id()] = False
        # Mark clients as desynced.
        self.desync_all()
        return actor.actor_id()

    def free_actor(self, actor_id):
        if actor_id in self._actors:
            del self._actors[actor_id]
        if actor_id in self._action_history:
            del self._action_history[actor_id]
        if actor_id in self._objectives_stale:
            del self._objectives_stale[actor_id]
        if actor_id in self._turn_history:
            del self._turn_history[actor_id]
        self._id_assigner.free(actor_id)
        # Mark clients as desynced.
        self.desync_all()

    def get_actor(self, player_id):
        return self._actors[player_id]

    def desync(self, actor_id):
        self._synced[actor_id] = False

    def desync_all(self):
        for a in self._actors:
            actor = self._actors[a]
            self._synced[actor.actor_id()] = False

    def is_synced(self, actor_id):
        return self._synced[actor_id]

    def is_synced_all(self):
        for a in self._actors:
            if not self.synced(self._actors[a].actor_id()):
                return False
        return True
    
    def has_pending_messages(self):
        for actor_id in self._actors:
            if not self.is_synced(actor_id):
                return True
            if len(self._action_history[actor_id]) > 0:
                return True
            if self._objectives_stale[actor_id]:
                return True
            if not self._turn_history[actor_id].empty():
                return True
        return False

    def drain_message(self, player_id):
        """ Returns a MessageFromServer object to send to the indicated player.

            If no message is available, returns None.
        """
        map_update = self.drain_map_update(player_id)
        if map_update is not None:
            logger.info(
                f'Room {self._room_id} drained map update {map_update} for player_id {player_id}')
            return message_from_server.MapUpdateFromServer(map_update)

        if not self.is_synced(player_id):
            state_sync = self.sync_message_for_transmission(player_id)
            logger.info(
                f'Room {self._room_id} drained state sync: {state_sync} for player_id {player_id}')
            msg = message_from_server.StateSyncFromServer(state_sync)
            return msg

        actions = self.drain_actions(player_id)
        if len(actions) > 0:
            logger.info(
                f'Room {self._room_id} drained {len(actions)} actions for player_id {player_id}')
            msg = message_from_server.ActionsFromServer(actions)
            return msg

        objectives = self.drain_objectives(player_id)
        if len(objectives) > 0:
            logger.info(
                f'Room {self._room_id} drained {len(objectives)} texts for player_id {player_id}')
            msg = message_from_server.ObjectivesFromServer(objectives)
            return msg
        
        turn_state = self.drain_turn_state(player_id)
        if not turn_state is None:
            logger.info(
                f'Room {self._room_id} drained ts {turn_state} for player_id {player_id}')
            msg = message_from_server.GameStateFromServer(turn_state)
            return msg

        # Nothing to send.
        return None

    def drain_actions(self, actor_id):
        if not actor_id in self._action_history:
            return []
        action_history = self._action_history[actor_id]
        # Log actions sent to client.
        for action in action_history:
            self._sent_log.info(f"to: {actor_id} action: {action}")
        self._action_history[actor_id] = []
        return action_history

    def drain_objectives(self, actor_id):
        if not actor_id in self._objectives_stale:
            self._objectives_stale[actor_id] = True
        
        if not self._objectives_stale[actor_id]:
            return []
        
        # Send the latest objective list and mark as fresh for this player.
        self._objectives_stale[actor_id] = False
        self._sent_log.info(f"to: {actor_id} objectives: {self._objectives}")
        return self._objectives
    
    def drain_map_update(self, actor_id):
        if not actor_id in self._map_stale:
            self._map_stale[actor_id] = True
        
        if not self._map_stale[actor_id]:
            return None
        
        # Send the latest map and mark as fresh for this player.
        self._map_stale[actor_id] = False
        self._sent_log.info(f"to: {actor_id} map: {self._map_update}")
        return self._map_update


    # Returns the current state of the game.
    def state(self, actor_id=-1):
        actor_states = []
        for a in self._actors:
            actor = self._actors[a]
            actor_states.append(actor.state())
        return state_sync.StateSync(len(self._actors), actor_states, actor_id)

    # Returns the current state of the game.
    # Calling this message comes with the assumption that the response will be transmitted to the clients.
    # Once this function returns, the clients are marked as synchronized.
    def sync_message_for_transmission(self, actor_id):
        # This won't do... there might be some weird oscillation where an
        # in-flight invalid packet triggers another sync. need to communicate
        # round trip.
        sync_message = self.state(actor_id)
        self._synced[actor_id] = True
        return sync_message

    def valid_action(self, actor_id, action):
        if (action.action_type == ActionType.TRANSLATE):
            cartesian = action.displacement.cartesian()
            # Add a small delta for floating point comparison.
            if (math.sqrt(cartesian[0]**2 + cartesian[1]**2) > 1.001):
                return False
        if (action.action_type == ActionType.ROTATE):
            if (action.rotation > 60.01):
                return False
        return True


class Actor(object):
    def __init__(self, actor_id, asset_id, role, spawn):
        self._actor_id = actor_id
        self._asset_id = asset_id
        self._actions = Queue()
        self._location = spawn
        self._heading_degrees = 0
        self._role = role

    def turn():
        pass

    def actor_id(self):
        return self._actor_id

    def asset_id(self):
        return self._asset_id

    def role(self):
        return self._role

    def add_action(self, action):
        self._actions.put(action)

    def has_actions(self):
        return not self._actions.empty()

    def location(self):
        return self._location

    def heading_degrees(self):
        return int(self._heading_degrees)

    def state(self):
        return state_sync.Actor(self.actor_id(), self.asset_id(),
                                self._location, self._heading_degrees)

    def peek(self):
        """ Peeks at the next action without consuming it. """
        return self._actions.queue[0]

    def step(self):
        """ Executes & consumes an action from the queue."""
        if not self.has_actions():
            return
        action = self._actions.get()
        self._location = HecsCoord.add(self._location, action.displacement)
        self._heading_degrees += action.rotation

    def drop(self):
        """ Drops an action instead of acting upon it."""
        if not self.has_actions():
            return
        _ = self._actions.get()
