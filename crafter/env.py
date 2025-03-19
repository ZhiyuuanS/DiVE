import collections

import numpy as np

from . import constants
from . import engine
from . import objects
from . import worldgen
import json

from typing import List, Optional

# Gym is an optional dependency.
try:
  import gym
  DiscreteSpace = gym.spaces.Discrete
  BoxSpace = gym.spaces.Box
  DictSpace = gym.spaces.Dict
  BaseClass = gym.Env
except ImportError:
  DiscreteSpace = collections.namedtuple('DiscreteSpace', 'n')
  BoxSpace = collections.namedtuple('BoxSpace', 'low, high, shape, dtype')
  DictSpace = collections.namedtuple('DictSpace', 'spaces')
  BaseClass = object


class Env(BaseClass):

  def __init__(
      self, area=(64, 64), view=(9, 9), size=(64, 64),
      reward=True, length=10000, seed=0, object_dict_path='../crafter_env/objects.json'):
    view = np.array(view if hasattr(view, '__len__') else (view, view))
    size = np.array(size if hasattr(size, '__len__') else (size, size))
    self._area = area
    self._view = view
    self._size = size
    self._reward = reward
    self._length = length
    self._seed = seed
    self._episode = 0
    self._world = engine.World(area, constants.materials, (12, 12), self._seed)
    self._textures = engine.Textures(constants.root / 'assets')
    item_rows = int(np.ceil(len(constants.items) / view[0]))
    self._local_view = engine.LocalView(
        self._world, self._textures, [view[0], view[1] - item_rows])
    self._item_view = engine.ItemView(
        self._textures, [view[0], item_rows])
    self._sem_view = engine.SemanticView(self._world, [
        objects.Player, objects.Cow, objects.Zombie,
        objects.Skeleton, objects.Arrow, objects.Plant])
    self._step = None
    self._player = None
    self._last_health = None
    self._unlocked = None
    # Some libraries expect these attributes to be set.
    self.reward_range = None
    self.metadata = None
    # For the additional text description
    self._text_description = None
    self._moments = None

  @property
  def observation_space(self):
    return BoxSpace(0, 255, tuple(self._size) + (3,), np.uint8)

  @property
  def action_space(self):
    return DiscreteSpace(len(constants.actions))

  @property
  def action_names(self):
    return constants.actions

  def reset(self):
    center = (self._world.area[0] // 2, self._world.area[1] // 2)
    self._episode += 1
    self._step = 0
    self._world.reset(seed=hash((self._seed, self._episode)) % (2 ** 31 - 1))
    self._update_time()
    self._player = objects.Player(self._world, center)
    self._last_health = self._player.health
    self._world.add(self._player)
    self._unlocked = set()
    worldgen.generate_world(self._world, self._player)
    return self._obs()

  def step(self, action):
    mat_map = self._world._mat_map
    self._step += 1
    self._update_time()
    self._player.action = constants.actions[action]
    for obj in self._world.objects:
      if self._player.distance(obj) < 2 * max(self._view):
        obj.update()
    if self._step % 10 == 0:
      for chunk, objs in self._world.chunks.items():
        # xmin, xmax, ymin, ymax = chunk
        # center = (xmax - xmin) // 2, (ymax - ymin) // 2
        # if self._player.distance(center) < 4 * max(self._view):
        self._balance_chunk(chunk, objs)
    obs = self._obs()
    reward = (self._player.health - self._last_health) / 10
    self._last_health = self._player.health
    unlocked = {
        name for name, count in self._player.achievements.items()
        if count > 0 and name not in self._unlocked}
    if unlocked:
      self._unlocked |= unlocked
      reward += 1.0
    dead = self._player.health <= 0
    over = self._length and self._step >= self._length
    done = dead or over
    info = {
        'inventory': self._player.inventory.copy(),
        'achievements': self._player.achievements.copy(),
        'discount': 1 - float(dead),
        'semantic': self._sem_view(),
        'player_pos': self._player.pos,
        'reward': reward,
    }
    if not self._reward:
      reward = 0.0
    return obs, reward, done, info

  def render(self, size=None):
    size = size or self._size
    unit = size // self._view
    canvas = np.zeros(tuple(size) + (3,), np.uint8)
    local_view, text_description = self._local_view(self._player, unit)
    text_description = np.array(text_description)
    item_view = self._item_view(self._player.inventory, unit)
    view = np.concatenate([local_view, item_view], 1)
    border = (size - (size // self._view) * self._view) // 2
    (x, y), (w, h) = border, view.shape[:2]
    canvas[x: x + w, y: y + h] = view

    # set text description
    self._text_description = text_description
    return canvas.transpose((1, 0, 2))

  def _obs(self):
    return self.render()

  def _update_time(self):
    # https://www.desmos.com/calculator/grfbc6rs3h
    progress = (self._step / 300) % 1 + 0.3
    daylight = 1 - np.abs(np.cos(np.pi * progress)) ** 3
    self._world.daylight = daylight

  def _balance_chunk(self, chunk, objs):
    light = self._world.daylight
    self._balance_object(
        chunk, objs, objects.Zombie, 'grass', 6, 0, 0.3, 0.4,
        lambda pos: objects.Zombie(self._world, pos, self._player),
        lambda num, space: (
            0 if space < 50 else 3.5 - 3 * light, 3.5 - 3 * light))
    self._balance_object(
        chunk, objs, objects.Skeleton, 'path', 7, 7, 0.1, 0.1,
        lambda pos: objects.Skeleton(self._world, pos, self._player),
        lambda num, space: (0 if space < 6 else 1, 2))
    self._balance_object(
        chunk, objs, objects.Cow, 'grass', 5, 5, 0.01, 0.1,
        lambda pos: objects.Cow(self._world, pos),
        lambda num, space: (0 if space < 30 else 1, 1.5 + light))

  def _balance_object(
      self, chunk, objs, cls, material, span_dist, despan_dist,
      spawn_prob, despawn_prob, ctor, target_fn):
    xmin, xmax, ymin, ymax = chunk
    random = self._world.random
    creatures = [obj for obj in objs if isinstance(obj, cls)]
    mask = self._world.mask(*chunk, material)
    target_min, target_max = target_fn(len(creatures), mask.sum())
    if len(creatures) < int(target_min) and random.uniform() < spawn_prob:
      xs = np.tile(np.arange(xmin, xmax)[:, None], [1, ymax - ymin])
      ys = np.tile(np.arange(ymin, ymax)[None, :], [xmax - xmin, 1])
      xs, ys = xs[mask], ys[mask]
      i = random.randint(0, len(xs))
      pos = np.array((xs[i], ys[i]))
      empty = self._world[pos][1] is None
      away = self._player.distance(pos) >= span_dist
      if empty and away:
        self._world.add(ctor(pos))
    elif len(creatures) > int(target_max) and random.uniform() < despawn_prob:
      obj = creatures[random.randint(0, len(creatures))]
      away = self._player.distance(obj.pos) >= despan_dist
      if away:
        self._world.remove(obj)


  #### Helper functions  ####

  def text_description(self):
    text_description = np.array(self._text_description)
    return text_description.T
  
  def get_player_food(self):
    return self._player.inventory['food']

  def get_player_drink(self):
    return self._player.inventory['drink']
  
  def get_player_energy(self):
    return self._player.inventory['energy'] 
  
  def get_player_health(self):
    return self._last_health
  
  def get_player_inventory(self):
    return self._player.inventory

  def get_player_nearby(self):
    return self._world.nearby(self._player.pos, 1)
  
  def set_up_player_inventory(self, inventory):
    for inventory_name, inventory_quantity in inventory.items():
      self._player.inventory[inventory_name] = int(inventory_quantity)
    if self._player.inventory['iron_pickaxe'] > 0:
        self._player.inventory['stone_pickaxe'] = max(self._player.inventory['stone_pickaxe'], 1)
        self._player.inventory['wood_pickaxe'] = max(self._player.inventory['wood_pickaxe'], 1)
    elif self._player.inventory['stone_pickaxe'] > 0:
        self._player.inventory['wood_pickaxe'] = max(self._player.inventory['wood_pickaxe'], 1)
    
  
  def set_up_player_nearby(self, nearby, distance=1):
      import random
      materials = ['None', 'water', 'grass', 'stone', 'path', 'sand', 'tree', 'lava', 'coal', 'iron', 'diamond', 'table', 'furnace']
      nearby_materials = []
      nearby_objects = []
      
      for obj in nearby:
          if obj in materials:
              nearby_materials.append(obj)
          else:
              nearby_objects.append(obj)
      
      player_pos = self._player.pos
      positions = []
      
      for dx in range(-distance, distance + 1):
          for dy in range(-distance, distance + 1):
              if dx == 0 and dy == 0:
                 continue
              if player_pos[0] + dx >= 64 or player_pos[1] + dy >= 64:
                 continue
              positions.append((player_pos[0] + dx, player_pos[1] + dy))
      
      random.shuffle(positions)
      
      min_count = min(len(positions), len(nearby_materials))
      used_materials = random.sample(nearby_materials, min_count)
      
      for i, pos in enumerate(positions):
          if i < len(used_materials):
              chosen_material = used_materials[i]
              self._world[pos] = chosen_material
          elif len(nearby_materials) > 0:
              chosen_material = random.choice(nearby_materials)  # Randomly select from nearby materials
              self._world[pos] = chosen_material

      from crafter.objects import Cow, Skeleton, Zombie
      for i, pos in enumerate(positions):
          existed_object = self._world[pos][1]
          if existed_object:
             continue
          if 'cow' in nearby_objects:
            cow = Cow(self._world, pos)
            self._world.add(cow)
            nearby_objects.remove('cow')
          elif 'zombie' in nearby_objects:
            zombie = Zombie(self._world, pos, self._player)
            self._world.add(zombie)
            nearby_objects.remove('zombie')
          elif 'skeleton' in nearby_objects:
            skeleton = Skeleton(self._world, pos, self._player)
            self._world.add(skeleton)
            nearby_objects.remove('skeleton')

  
  def remove_all_objects(self):
     for x in range(64):
        for y in range(64):
           existed_object = self._world[(x, y)][1] 
           if existed_object:
              if existed_object.__class__.__name__ == 'Player':
                 continue
              self._world.remove(existed_object)


  def set_up_specific_material(self, position, material):
     self._world[position] = material


  def player_pos(self):
     return self._player.pos

  def set_up_player_facing(self, object_name: str):
     from crafter.objects import Cow, Skeleton, Zombie
     materials = ['None', 'water', 'grass', 'stone', 'path', 'sand', 'tree', 'lava', 'coal', 'iron', 'diamond', 'table', 'furnace']
     player_pos = self._player.pos
     facing_pos = (player_pos[0] + self._player.facing[0], player_pos[1] + self._player.facing[1])
     
     if object_name in materials:
        self._world[facing_pos] = object_name
     else:
      if self._world[facing_pos][1] is not None:
          faced_object = self._world[facing_pos][1]
          faced_object_name = type(faced_object).__name__
          if faced_object_name.lower() == object_name:
             return
          else:
            self._world.remove(faced_object)
            if object_name == 'cow':
                cow = Cow(self._world, facing_pos)
                self._world.add(cow)
            elif object_name == 'zombie':
                zombie = Zombie(self._world, facing_pos, self._player)
                self._world.add(zombie)
            elif object_name == 'skeleton':
                skeleton = Skeleton(self._world, facing_pos, self._player)
                self._world.add(skeleton)
    

  def get_player_standing(self):
    player_pos = self._player.pos
    mat_map = self._world._mat_map
    mat_standing = mat_map[player_pos[0]][player_pos[1]]
    reverse_mat_id = {
        0: None,
        1: 'water',
        2: 'grass',
        3: 'stone',
        4: 'path',
        5: 'sand',
        6: 'tree',
        7: 'lava',
        8: 'coal',
        9: 'iron',
        10: 'diamond',
        11: 'table',
        12: 'furnace'
    }
    return reverse_mat_id[mat_standing]


  
        