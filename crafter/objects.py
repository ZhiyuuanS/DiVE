import numpy as np

from . import constants
from . import engine


class Object:

  def __init__(self, world, pos):
    self.world = world
    self.pos = np.array(pos)
    self.random = world.random
    self.inventory = {'health': 0}
    self.removed = False

  @property
  def texture(self):
    raise 'unknown'

  @property
  def walkable(self):
    return constants.walkable

  @property
  def health(self):
    return self.inventory['health']

  @health.setter
  def health(self, value):
    self.inventory['health'] = max(0, value)

  @property
  def all_dirs(self):
    return ((-1, 0), (+1, 0), (0, -1), (0, +1))

  def move(self, direction):
    direction = np.array(direction)
    target = self.pos + direction
    if self.is_free(target):
      self.world.move(self, target)
      return True
    return False

  def is_free(self, target, materials=None):
    materials = self.walkable if materials is None else materials
    material, obj = self.world[target]
    return obj is None and material in materials

  def distance(self, target):
    if hasattr(target, 'pos'):
      target = target.pos
    return np.abs(target - self.pos).sum()

  def toward(self, target, long_axis=True):
    if hasattr(target, 'pos'):
      target = target.pos
    offset = target - self.pos
    dists = np.abs(offset)
    if (dists[0] > dists[1] if long_axis else dists[0] <= dists[1]):
      return np.array((np.sign(offset[0]), 0))
    else:
      return np.array((0, np.sign(offset[1])))

  def random_dir(self):
    return self.all_dirs[self.random.randint(0, 4)]


class Player(Object):

  def __init__(self, world, pos):
    super().__init__(world, pos)
    self.facing = (0, 1)
    self.inventory = {
        name: info['initial'] for name, info in constants.items.items()}
    self.achievements = {name: 0 for name in constants.achievements}
    self.action = 'noop'
    self.sleeping = False
    self._last_health = self.health
    self._hunger = 0
    self._thirst = 0
    self._fatigue = 0
    self._recover = 0

  @property
  def texture(self):
    if self.sleeping:
      return 'player-sleep'
    return {
        (-1, 0): 'player-left',
        (+1, 0): 'player-right',
        (0, -1): 'player-up',
        (0, +1): 'player-down',
    }[tuple(self.facing)]

  @property
  def walkable(self):
    return constants.walkable + ['lava']

  def update(self):
    target = (self.pos[0] + self.facing[0], self.pos[1] + self.facing[1])
    material, obj = self.world[target]
    action = self.action
    if self.sleeping:
      if self.inventory['energy'] < constants.items['energy']['max']:
        action = 'sleep'
      else:
        self.sleeping = False
        self.achievements['wake_up'] += 1
    if action == 'noop':
      pass
    elif action.startswith('move_'):
      self._move(action[len('move_'):])
    elif action == 'do' and obj:
      self._do_object(obj)
    elif action == 'do':
      self._do_material(target, material)
    elif action == 'sleep':
      if self.inventory['energy'] < constants.items['energy']['max']:
        self.sleeping = True
    elif action.startswith('place_'):
      self._place(action[len('place_'):], target, material)
    elif action.startswith('make_'):
      self._make(action[len('make_'):])
    self._update_life_stats()
    self._degen_or_regen_health()
    for name, amount in self.inventory.items():
      maxmium = constants.items[name]['max']
      self.inventory[name] = max(0, min(amount, maxmium))
    # This needs to happen after the inventory states are clamped
    # because it involves the health water inventory count.
    self._wake_up_when_hurt()

  def _available_action(self, state_description):
    # Action Dynamics discovered by LLMs

    available_actions = []
    directions = {
        'west': (-1, 0), 
        'east': (+1, 0), 
        'north': (0, -1), 
        'south': (0, +1)
    }
    
    # Check movements and interactions with adjacent tiles
    for direction, diff in directions.items():
        target = (self.pos[0] + diff[0], self.pos[1] + diff[1])
        material, obj = self.world[target]
        # obj_name = obj.__class__.__name__ if obj else None
        if obj:
            obj_texture = obj.texture
        else:
            obj_texture = None
    
        if material in ['grass', 'sand', 'path'] and obj_texture not in ['cow', 'skeleton', 'zombie', 'plant', 'plant-ripe']:
            available_actions.append(f'move_{direction}')
        elif diff != self.facing:
            if obj_texture in ['cow', 'skeleton', 'zombie', 'plant', 'plant-ripe']:
                available_actions.append(f'face_{direction}_obstructed_by_{obj_texture}')
            if material in ['tree', 'stone', 'coal', 'iron', 'diamond', 'water']:
                available_actions.append(f'face_{direction}_obstructed_by_{material}')
    
    current_facing = {v: k for k, v in directions.items()}[self.facing]
    # Check actions based on the material in front
    target = (self.pos[0] + self.facing[0], self.pos[1] + self.facing[1])
    material, obj = self.world[target]
    
    if material == 'water' and self.inventory['wood_pickaxe'] >= 1:
        available_actions.append(f'collect_drink_on_{current_facing}')
    if material == 'tree':
        available_actions.append(f'collect_wood_on_{current_facing}')
    if material == 'stone' and self.inventory['wood_pickaxe'] >= 1:
        available_actions.append(f'collect_stone_on_{current_facing}')
    if material == 'coal' and self.inventory['wood_pickaxe'] >= 1:
        available_actions.append(f'collect_coal_on_{current_facing}')
    if material == 'iron' and self.inventory['stone_pickaxe'] >= 1:
        available_actions.append(f'collect_iron_on_{current_facing}')
    if material == 'diamond' and self.inventory['iron_pickaxe'] >= 1:
        available_actions.append(f'collect_diamond_on_{current_facing}')
    if material == 'grass' and self.inventory['wood_pickaxe'] >= 1 and self.inventory['wood_sword'] >= 1:
        available_actions.append(f'collect_sapling_on_{current_facing}')
    if material == 'grass' and self.inventory['sapling'] >= 1 and self.inventory['wood_pickaxe'] >= 1 and self.inventory['wood_sword'] >= 1:
        available_actions.append(f'place_plant_on_{current_facing}')
    
    
    # Check crafting actions
    nearby, _ = self.world.nearby(self.pos, 1)

    # Check actions based on the object in front
    if obj:
        obj_texture = obj.texture
        if obj_texture == 'cow' and self.inventory['wood_sword'] >= 1 and self.inventory['wood_pickaxe'] >= 1:
            available_actions.append(f'eat_cow_on_{current_facing}')
        if obj_texture == 'skeleton' and self.inventory['wood_sword'] >= 1:
            available_actions.append(f'defeat_skeleton_on_{current_facing}')
        if obj_texture == 'zombie' and self.inventory['wood_sword'] >= 1:
            available_actions.append(f'defeat_zombie_on_{current_facing}')
        if obj_texture == 'plant-ripe' and 'stone' in nearby and self.inventory['iron_sword'] >= 1:
            available_actions.append(f'eat_plant_on_{current_facing}')


    if 'table' in nearby:
        if self.inventory['wood'] >= 1:
            available_actions.append('make_wood_pickaxe')
            if self.inventory['wood_pickaxe'] >= 1:
              available_actions.append('make_wood_sword')
        if self.inventory['wood'] >= 1 and self.inventory['stone'] >= 1:
            available_actions.append('make_stone_pickaxe')
            if self.inventory['stone_pickaxe'] >= 1:
              available_actions.append('make_stone_sword')
    if 'table' in nearby and 'furnace' in nearby:
        if self.inventory['wood'] >= 1 and self.inventory['coal'] >= 1 and self.inventory['iron'] >= 1:
            available_actions.append('make_iron_pickaxe')
            if self.inventory['iron_pickaxe'] >= 1:
              available_actions.append('make_iron_sword')
    
    if material in ['grass', 'path'] and obj is None:
      if self.inventory['wood'] >= 2:
          available_actions.append(f'place_table_on_{material}_to_{current_facing}')
      if self.inventory['stone'] >= 4 and ('table' in nearby):
          available_actions.append(f'place_furnace_on_{material}_to_{current_facing}')
    if material in ['grass', 'sand', 'path', 'water', 'lava'] and obj is None:
      if self.inventory['stone'] >= 1:
          available_actions.append(f'place_stone_on_{material}_to_{current_facing}')
    
        # Check energy and add sleep action if needed
    if 'stone' in nearby and 'path' in nearby and self.inventory['stone_sword'] >= 1:
      available_actions.append('sleep')
    # print('available_actions: ', available_actions)
    return available_actions

    
        
  def _update_life_stats(self):
    self._hunger += 0.5 if self.sleeping else 1
    if self._hunger > 25:
      self._hunger = 0
      self.inventory['food'] -= 1
    self._thirst += 0.5 if self.sleeping else 1
    if self._thirst > 20:
      self._thirst = 0
      self.inventory['drink'] -= 1
    if self.sleeping:
      self._fatigue = min(self._fatigue - 1, 0)
    else:
      self._fatigue += 1
    if self._fatigue < -10:
      self._fatigue = 0
      self.inventory['energy'] += 1
    if self._fatigue > 30:
      self._fatigue = 0
      self.inventory['energy'] -= 1

  def _degen_or_regen_health(self):
    necessities = (
        self.inventory['food'] > 0,
        self.inventory['drink'] > 0,
        self.inventory['energy'] > 0 or self.sleeping)
    if all(necessities):
      self._recover += 2 if self.sleeping else 1
    else:
      self._recover -= 0.5 if self.sleeping else 1
    if self._recover > 25:
      self._recover = 0
      self.health += 1
    if self._recover < -15:
      self._recover = 0
      self.health -= 1

  def _wake_up_when_hurt(self):
    if self.health < self._last_health:
      self.sleeping = False
    self._last_health = self.health

  def _move(self, direction):
    directions = dict(left=(-1, 0), right=(+1, 0), up=(0, -1), down=(0, +1))
    self.facing = directions[direction]
    self.move(self.facing)
    if self.world[self.pos][0] == 'lava':
      self.health = 0

  def _do_object(self, obj):
    damage = max([
        1,
        self.inventory['wood_sword'] and 2,
        self.inventory['stone_sword'] and 3,
        self.inventory['iron_sword'] and 5,
    ])
    if isinstance(obj, Plant):
      if obj.ripe:
        obj.grown = 0
        self.inventory['food'] += 4
        self.achievements['eat_plant'] += 1
    if isinstance(obj, Fence):
      self.world.remove(obj)
      self.inventory['fence'] += 1
      self.achievements['collect_fence'] += 1
    if isinstance(obj, Zombie):
      obj.health -= damage
      if obj.health <= 0:
        self.achievements['defeat_zombie'] += 1
    if isinstance(obj, Skeleton):
      obj.health -= damage
      if obj.health <= 0:
        self.achievements['defeat_skeleton'] += 1
    if isinstance(obj, Cow):
      obj.health -= damage
      if obj.health <= 0:
        self.inventory['food'] += 6
        self.achievements['eat_cow'] += 1
        # TODO: Keep track of previous inventory state to do this in a more
        # general way.
        self._hunger = 0

  def _do_material(self, target, material):
    if material == 'water':
      # TODO: Keep track of previous inventory state to do this in a more
      # general way.
      self._thirst = 0
    info = constants.collect.get(material)
    if not info:
      return
    for name, amount in info['require'].items():
      if self.inventory[name] < amount:
        return
    self.world[target] = info['leaves']
    if self.random.uniform() <= info.get('probability', 1):
      for name, amount in info['receive'].items():
        self.inventory[name] += amount
        self.achievements[f'collect_{name}'] += 1

  def _place(self, name, target, material):
    if self.world[target][1]:
      return
    info = constants.place[name]
    if material not in info['where']:
      return
    if any(self.inventory[k] < v for k, v in info['uses'].items()):
      return
    for item, amount in info['uses'].items():
      self.inventory[item] -= amount
    if info['type'] == 'material':
      self.world[target] = name
    elif info['type'] == 'object':
      cls = {
          'fence': Fence,
          'plant': Plant,
      }[name]
      self.world.add(cls(self.world, target))
    self.achievements[f'place_{name}'] += 1

  def _make(self, name):
    nearby, _ = self.world.nearby(self.pos, 1)
    info = constants.make[name]
    if not all(util in nearby for util in info['nearby']):
      return
    if any(self.inventory[k] < v for k, v in info['uses'].items()):
      return
    for item, amount in info['uses'].items():
      self.inventory[item] -= amount
    self.inventory[name] += info['gives']
    self.achievements[f'make_{name}'] += 1


class Cow(Object):

  def __init__(self, world, pos):
    super().__init__(world, pos)
    self.health = 3

  @property
  def texture(self):
    return 'cow'

  def update(self):
    if self.health <= 0:
      self.world.remove(self)
    if self.random.uniform() < 0.5:
      direction = self.random_dir()
      self.move(direction)


class Zombie(Object):

  def __init__(self, world, pos, player):
    super().__init__(world, pos)
    self.player = player
    self.health = 5
    self.cooldown = 0

  @property
  def texture(self):
    return 'zombie'

  def update(self):
    if self.health <= 0:
      self.world.remove(self)
    dist = self.distance(self.player)
    if dist <= 8 and self.random.uniform() < 0.9:
      self.move(self.toward(self.player, self.random.uniform() < 0.8))
    else:
      self.move(self.random_dir())
    dist = self.distance(self.player)
    if dist <= 1:
      if self.cooldown:
        self.cooldown -= 1
      else:
        if self.player.sleeping:
          damage = 7
        else:
          damage = 2
        self.player.health -= damage
        self.cooldown = 5


class Skeleton(Object):

  def __init__(self, world, pos, player):
    super().__init__(world, pos)
    self.player = player
    self.health = 3
    self.reload = 0

  @property
  def texture(self):
    return 'skeleton'

  def update(self):
    if self.health <= 0:
      self.world.remove(self)
    self.reload = max(0, self.reload - 1)
    dist = self.distance(self.player.pos)
    if dist <= 3:
      moved = self.move(-self.toward(self.player, self.random.uniform() < 0.6))
      if moved:
        return
    if dist <= 5 and self.random.uniform() < 0.5:
      self._shoot(self.toward(self.player))
    elif dist <= 8 and self.random.uniform() < 0.3:
      self.move(self.toward(self.player, self.random.uniform() < 0.6))
    elif self.random.uniform() < 0.2:
      self.move(self.random_dir())

  def _shoot(self, direction):
    if self.reload > 0:
      return
    if direction[0] == 0 and direction[1] == 0:
      return
    pos = self.pos + direction
    if self.is_free(pos, Arrow.walkable):
      self.world.add(Arrow(self.world, pos, direction))
      self.reload = 4


class Arrow(Object):

  def __init__(self, world, pos, facing):
    super().__init__(world, pos)
    self.facing = facing

  @property
  def texture(self):
    return {
        (-1, 0): 'arrow-left',
        (+1, 0): 'arrow-right',
        (0, -1): 'arrow-up',
        (0, +1): 'arrow-down',
    }[tuple(self.facing)]

  @engine.staticproperty
  def walkable():
    return constants.walkable + ['water', 'lava']

  def update(self):
    target = self.pos + self.facing
    material, obj = self.world[target]
    if obj:
      obj.health -= 2
      self.world.remove(self)
    elif material not in self.walkable:
      self.world.remove(self)
      if material in ['table', 'furnace']:
        self.world[target] = 'path'
    else:
      self.move(self.facing)


class Plant(Object):

  def __init__(self, world, pos):
    super().__init__(world, pos)
    self.health = 1
    self.grown = 0

  @property
  def texture(self):
    if self.ripe:
      return 'plant-ripe'
    else:
      return 'plant'

  @property
  def ripe(self):
    return self.grown > 300

  def update(self):
    self.grown += 1
    objs = [self.world[self.pos + dir_][1] for dir_ in self.all_dirs]
    if any(isinstance(obj, (Zombie, Skeleton, Cow)) for obj in objs):
      self.health -= 1
    if self.health <= 0:
      self.world.remove(self)


class Fence(Object):

  def __init__(self, world, pos):
    super().__init__(world, pos)

  @property
  def texture(self):
    return 'fence'

  def update(self):
    pass