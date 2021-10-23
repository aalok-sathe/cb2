import aiohttp
import asyncio
import fire
import hashlib
import json
import os
import time

from aiohttp import web
from hex import HecsCoord, HexBoundary, HexCell
from messages import map_update
from messages import message_from_server
from messages import message_to_server
from messages import state_sync
from state import State

from datetime import datetime

routes = web.RouteTableDef()

# A table of active websocket connections.
remote_table = {}

game_state = State()

@routes.get('/')
async def Index(request):
  global assets_map
  global remote_table
  server_state = {
    "assets": assets_map,
    "endpoints": remote_table,
  }
  return web.json_response(server_state)

async def stream_game_state(request, ws, agent_id):
  # mupdate = map_update.MapUpdate(20, 20, [map_update.Tile(1, HexCell(HecsCoord(1, 3, 7)))])
  global remote_table
  global game_state
  while not ws.closed:
    await asyncio.sleep(0.1)
    if not game_state.is_synced(agent_id):
      state_sync = game_state.sync_message_for_transmission(agent_id)
      msg = message_from_server.MessageFromServer(datetime.now(), message_from_server.MessageType.STATE_SYNC, None, None, state_sync)
      await ws.send_str(msg.to_json())
      remote_table[request.remote]["bytes_down"] += len(msg.to_json())
      remote_table[request.remote]["last_message_down"] = time.time()
    actions = game_state.drain_actions(agent_id)
    if len(actions) > 0:
      msg = message_from_server.MessageFromServer(datetime.now(), message_from_server.MessageType.ACTIONS, actions, None, None)
      await ws.send_str(msg.to_json())
      remote_table[request.remote]["bytes_down"] += len(msg.to_json())
      remote_table[request.remote]["last_message_down"] = time.time()
      

async def receive_agent_updates(request, ws, agent_id):
  global remote_table
  global game_state
  try:
    async for msg in ws:
      if msg.type == aiohttp.WSMsgType.ERROR:
        closed = True
        await ws.close()
        game_state.free_actor(agent_id)
        del remote_table[request.remote]
        print('ws connection closed with exception %s' % ws.exception())
        continue

      if msg.type != aiohttp.WSMsgType.TEXT:
        continue

      remote_table[request.remote]["last_message_up"] = time.time()
      remote_table[request.remote]["bytes_up"] += len(msg.data)

      if msg.data == 'close':
        closed = True
        await ws.close()
        game_state.free_actor(agent_id)
        del remote_table[request.remote]
        continue

      message = message_to_server.MessageToServer.from_json(msg.data)
      if message.type == message_to_server.MessageType.ACTIONS:
        print("Action received. Transmit: {0}, Type: {1}, Actions:")
        for action in message.actions:
          print("{0}:{1}".format(action.actor_id, action.destination))
          game_state.handle_action(agent_id, action)
      if message.type == message_to_server.MessageType.STATE_SYNC_REQUEST:
        game_state.desync(agent_id)
  finally:
    print("Disconnect detected")
    game_state.free_actor(agent_id)
    del remote_table[request.remote]

@routes.get('/player_endpoint')
async def PlayerEndpoint(request):
  global remote_table
  global game_state
  ws = web.WebSocketResponse(autoclose=True, heartbeat=1.0, autoping = 1.0)
  await ws.prepare(request)
  remote_table[request.remote] = {"last_message_up": time.time(), "last_message_down": time.time(), "ip": request.remote, "id":0, "bytes_up": 0, "bytes_down": 0}
  agent_id = game_state.create_actor()
  remote_table[request.remote]["id"] = agent_id
  await asyncio.gather(receive_agent_updates(request, ws, agent_id), stream_game_state(request, ws, agent_id))
  game_state.free_actor(agent_id)
  del remote_table[request.remote]
  return ws

def HashCollectAssets(assets_directory):
  assets_map = {}
  for item in os.listdir(assets_directory):
    assets_map[hashlib.md5(item.encode()).hexdigest()] = os.path.join(assets_directory, item)
  return assets_map

# A dictionary from md5sum to asset filename.
assets_map = {}

@routes.get('/assets/{asset_id}')
async def asset(request):
  asset_id = request.match_info.get('asset_id', "")
  if (asset_id not in assets_map):
    raise aiohttp.web.HTTPNotFound('/redirect')
  return web.FileResponse(assets_map[asset_id])

async def serve():
  app = web.Application()
  app.add_routes(routes)
  runner = runner = aiohttp.web.AppRunner(app)
  await runner.setup()
  site = web.TCPSite(runner, 'localhost', 8080)
  await site.start()

  print("======= Serving on http://localhost:8080/ ======")

  # pause here for very long time by serving HTTP requests and
  # waiting for keyboard interruption
  while True:
    await asyncio.sleep(1)
  
async def debug_print():
  global game_state
  while True:
    await asyncio.sleep(5)
    state = game_state.state()
    print(state)

def main(assets_directory = "assets/"):
  global assets_map
  global game_state
  game_state_task = asyncio.gather(game_state.update(), debug_print())
  assets_map = HashCollectAssets(assets_directory)
  tasks = asyncio.gather(game_state_task, serve())
  loop = asyncio.get_event_loop()
  try:
      loop.run_until_complete(tasks)
  except KeyboardInterrupt:
      pass
  game_state.end_game()
  loop.close()

if __name__ == "__main__":
  fire.Fire(main)