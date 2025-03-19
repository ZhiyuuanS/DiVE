import sys
from collections import defaultdict

class StatsDescriptor:
    """Describes changes in player's stats and inventory."""
    
    def describe_changes(self, prev_inventory_stats, curr_inventory_stats, inventory_name):
        changes = curr_inventory_stats - prev_inventory_stats
        if changes > 0:
            return f'The {inventory_name} increased by {changes}'
        elif changes < 0:
            return f'The {inventory_name} decreased by {abs(changes)}'
        return None

    def describe(self, episode_history, initial_index, steps):
        stats_description = [dict() for _ in range(min(steps, len(episode_history['action']) - initial_index))]
        
        for inventory, data in episode_history.items():
            if inventory.startswith('ainventory') or inventory == 'reward':
                inventory_name = '_'.join(inventory.split('_')[1:]) if inventory.count('_') > 1 else inventory.split('_')[1]
                for step_i in range(steps):
                    corresponding_step_i = step_i + initial_index
                    if corresponding_step_i >= len(data):
                        break
                    curr_inventory_stats = data[corresponding_step_i]
                    stats_description[step_i][inventory_name] = curr_inventory_stats
        
        return stats_description


class ActionDescriptor:
    """Describes actions taken by the player."""
    
    def __init__(self):
        self._initialize_action_mapping()

    def _initialize_action_mapping(self):
        self._action_mapping = {
            0: "noop", 1: "moving left", 2: "moving right", 3: "move up", 4: "move down",
            5: "do", 6: "sleep", 7: "place stone", 8: "place table", 9: "place furnace",
            10: "place plant", 11: "make wood pickaxe", 12: "make stone pickaxe",
            13: "make iron pickaxe", 14: "make wood sword", 15: "make stone sword", 16: "make iron sword"
        }

    def remap_do_actions(self, description, do_actions_indices, episode_history, initial_index, steps):
        for achievement, data in episode_history.items():
            if not achievement.startswith('achievement_'):
                continue
            achievement_name = achievement.removeprefix('achievement_')
            achievements = [0] * steps if initial_index == 0 else data[initial_index - 1:initial_index + steps]
            
            for i, do_index in enumerate(do_actions_indices):
                if do_index < len(achievements):
                    prev_index = do_index - 1
                    if achievements[do_index] - achievements[prev_index] > 0:
                        description[prev_index] = achievement_name

        for action_i in range(len(description)):
            if description[action_i] == 'do':
                description[action_i] = 'do(mine or collect or attack)'

        return description

    def describe(self, episode_history, initial_index, steps):
        description = []
        episode_action = episode_history.get('action', [])
        for action_i in range(initial_index, min(initial_index + steps, len(episode_action))):
            action = episode_action[action_i]
            description.append(self._action_mapping.get(action, 'unknown_action'))
        
        # replace 'do' action with a specific action
        do_actions_indices = [i + 1 for i, action in enumerate(description) if action == 'do']
        actions = self.remap_do_actions(description, do_actions_indices, episode_history, initial_index, steps)
        return ['_'.join(action.split(' ')) for action in actions]


class StateDescriptor:
    """Describes the state of the game environment based on scene, stats, and actions."""
    
    def __init__(self):
        self.stats_descriptor = StatsDescriptor()
        self.action_descriptor = ActionDescriptor()

    def _describe_state(self, initial_index, scene_description, stats_description, action_description, time):
        state_description = ''
        for index, scene in enumerate(scene_description):
            day = (initial_index + 90 + index) // 300
            state_description += f'On day {day} and at the time {time[index]}, the player sees: {scene}\n'
            state_description += f'Player takes action: {action_description[index]}\n'
            stats_desc = ', '.join(stats_description[index])
            state_description += f'Player stats and inventory information: {stats_desc}\n'
        return state_description

    def describe(self, episode_history, initial_index, steps):
        initial_index = max(initial_index, 2)  # first index's image is null
        scene_description = episode_history['text_description'][initial_index:initial_index + steps]
        stats_description = self.stats_descriptor.describe(episode_history, initial_index, steps)
        action_description = self.action_descriptor.describe(episode_history, initial_index, steps)
        time = episode_history['time'][initial_index:initial_index + steps]
        return self._describe_state(initial_index, scene_description, stats_description, action_description, time)

    def describe_subtask(self, episode_history, initial_index, steps):
        initial_index = max(initial_index, 2)
        action_description = self.action_descriptor.describe(episode_history, initial_index, steps)
        subtask = []
        subtask_index = 0
        movement = ['noop', 'moving_left', 'moving_right', 'move_up', 'move_down', 'do(mine_or_collect_or_attack)']
        for action in action_description:
            if action not in movement:
                subtask.append({action: subtask_index})
            subtask_index += 1
        return subtask

    def describe_inventory(self, episode_history, initial_index, steps):
        initial_index = max(initial_index, 2)
        return self.stats_descriptor.describe(episode_history, initial_index, steps)

    def describe_action(self, episode_history, initial_index, steps):
        initial_index = max(initial_index, 1)
        action_description = self.action_descriptor.describe(episode_history, initial_index, steps)
        return [{action: idx} for idx, action in enumerate(action_description)]


class SceneDescriptor:
    def __init__(self):
        self._initialize_directions()
        self.described_items = defaultdict(set)
        self.common_items = []
        self.scene_description_index = []
        self.nearby_item = []
        self._cave_material = ['stone', 'coal', 'diamond', 'lava', 'iron', 'path']
        self._grass_material = ['tree', 'grass']
        self._water_material = ['sand', 'water']
        self._unexplored_material = ['unexplored_area']

    def _initialize_directions(self):
        self._directions = {
            (-1, 0): "North", (1, 0): "South",
            (0, -1): "West", (0, 1): "East",
            (-1, -1): "North West", (1, -1): "South West",
            (-1, 1): "North East", (1, 1): "South East",
        }

    def describe(self, info):
        scene = info['text_description']
        time_step = info['time_step']
        hours = int(((90 + time_step) % 300) / 300 * 24)
        if 5 < hours < 20:
            time_description = f"It is daytime"
        else:
            time_description = f"It is nighttime"

        return self._natural_text_description(scene, time_description)

    def _natural_text_description(self, text_description, time_description):
        player_pos = None
        for r, row in enumerate(text_description):
            for c, item in enumerate(row):
                if 'player' in item:
                    player_pos = (r, c)

        grouped_description = self._group_elements(text_description, player_pos)
        facing_object, direction = self._find_face_items(text_description, player_pos)
        closed_objects = self._find_closest_items(text_description, facing_object, player_pos)
        description = self._generate_description(grouped_description, closed_objects, (facing_object, direction))
        with_time_description = f"{time_description}\n" + description
        return with_time_description

    def _group_elements(self, text_description, player_pos):
        grouped_description = defaultdict(lambda: defaultdict(list))
        for r, row in enumerate(text_description):
            for c, item in enumerate(row):
                self._add_nearby_items(r, c, item, player_pos)
                if 'arrow' in item:
                    if item == 'arrow-down' and c == player_pos[1] and r < player_pos[0]:
                        item = 'an arrow is moving southward and will hit you'
                    elif item == 'arrow-up' and c == player_pos[1] and r > player_pos[0]:
                        item = 'an arrow is moving northward and will hit you'
                    elif item == 'arrow-left' and r == player_pos[0] and c > player_pos[1]:
                        item = 'an arrow is moving westward and will hit you'
                    elif item == 'arrow-right' and r == player_pos[0] and c < player_pos[1]:
                        item = 'an arrow is moving eastward and will hit you'
                    else:
                        continue
                direction, distance = self._get_direction_and_distance(r, c, player_pos)
                if direction:
                    grouped_description[direction][item].append(distance)
        return grouped_description

    def _add_nearby_items(self, r, c, item, player_pos):
        if max(abs(r - player_pos[0]), abs(c - player_pos[1])) == 1:
            direction, _ = self._get_direction_and_distance(r, c, player_pos)
            if direction and item != 'grass':
                self.nearby_item.append('{} on {}'.format(item, direction))

    def _get_direction_and_distance(self, r, c, player_pos):
        row_diff, col_diff = r - player_pos[0], c - player_pos[1]
        if row_diff == 0 and col_diff == 0:
            return None, None
        normalized_row_diff = row_diff / abs(row_diff) if row_diff != 0 else 0
        normalized_col_diff = col_diff / abs(col_diff) if col_diff != 0 else 0
        direction = self._directions.get((normalized_row_diff, normalized_col_diff))
        if direction is None:
            raise ValueError("Invalid direction")
        distance = abs(row_diff) + abs(col_diff)
        return direction, distance

    def _find_face_items(self, scene, player_pos):
        direction_key = scene[player_pos[0]][player_pos[1]]
        direction_mapping = {
            'player-up': ('north', (-1, 0)),
            'player-down': ('south', (1, 0)),
            'player-left': ('west', (0, -1)),
            'player-right': ('east', (0, 1)),
            'player-sleep': ('Nothing', None)
        }
        
        if direction_key in direction_mapping:
            direction, offset = direction_mapping[direction_key]
            if direction == 'Nothing':
                return 'Nothing', 'None'
            next_pos = (player_pos[0] + offset[0], player_pos[1] + offset[1])
            try:
                returned_item = (scene[next_pos[0]][next_pos[1]], direction)
                return returned_item
            except:
                return 'Nothing', 'None'
        else:
            raise ValueError("Invalid player position: " + direction_key)

    def _find_closest_items(self, scene, face_item, player_pos):
        closest_items = defaultdict(lambda: {'distance': float('inf'), 'path': []})
        for r, row in enumerate(scene):
            for c, item in enumerate(row):
                if item == 'unexplored_area':
                    continue
                if 'player' not in item:
                    direction, distance, path = self._get_direction_distance_and_path(r, c, player_pos, scene)
                    if distance < closest_items[item]['distance']:
                        closest_items[item].update({
                            'item': item,
                            'direction': direction,
                            'distance': distance,
                            'path': path
                        })

        descriptions = "Closest:\n"
        for item, info in closest_items.items():
            objects_in_between = set(info['path'])
            if len(set(info['path'])) == 0:
                objects_in_between = None

            if (info['direction'] in ['North', 'South', 'East', 'West'] and info['distance'] == 1) or (info['direction'] not in ['North', 'South', 'East', 'West'] and info['distance'] == 2):
                s_distance = 'immediate'
            elif info['distance'] <= 10:
                s_distance = 'nearby'
            elif info['distance'] <= 20:
                s_distance = 'distant'
            else:
                s_distance = 'remote'

            if 'arrow' in item and s_distance in ['immediate', 'nearby']:
                if item == 'arrow-down' and direction == 'North':
                    item = 'an arrow is moving southward and will hit you'
                elif item == 'arrow-up' and direction == 'South':
                    item = 'an arrow is moving northward and will hit you'
                elif item == 'arrow-left' and direction == 'East':
                    item = 'an arrow is moving westward and will hit you'
                elif item == 'arrow-right' and direction == 'West':
                    item = 'an arrow is moving eastward and will hit you'
                else:
                    continue   
                descriptions += f"- {item} {info['distance']} blocks away ({s_distance}) (objects in between: {objects_in_between}) \n"
            else:
                descriptions += f"- {info['item']}: {info['direction']} {info['distance']} blocks away ({s_distance}) (objects in between: {objects_in_between}) \n"
        return descriptions


    def _get_direction_distance_and_path(self, r, c, player_pos, scene):
        row_diff, col_diff = r - player_pos[0], c - player_pos[1]
        if row_diff == 0 and col_diff == 0:
            return None, None, []

        normalized_row_diff = row_diff / abs(row_diff) if row_diff != 0 else 0
        normalized_col_diff = col_diff / abs(col_diff) if col_diff != 0 else 0
        direction = self._directions.get((normalized_row_diff, normalized_col_diff))
        
        distance = abs(row_diff) + abs(col_diff)
        path = self._trace_path(player_pos, (r, c), scene)
        return direction, distance, path


    def _trace_path(self, start_pos, end_pos, scene):
        path = []
        x_step = 1 if start_pos[0] <= end_pos[0] else -1
        y_step = 1 if start_pos[1] <= end_pos[1] else -1
        
        for x in range(start_pos[0], end_pos[0] + x_step, x_step):
            for y in range(start_pos[1], end_pos[1] + y_step, y_step):
                if (x, y) != start_pos and (x, y) != end_pos:
                    path.append(scene[x][y])

        return path


    def _generate_description(self, grouped_description, closed_objects, facing_object_and_direction):
        description = ['State description: \n']
        for direction, items in sorted(grouped_description.items()):
            items_descriptions = {
                'immediate': [],
                'nearby': [],
                'distant': [],
                'remote': []
            }
            for item in items:
                min_distance = min(items[item])
                if (direction in ['North', 'South', 'East', 'West'] and min_distance== 1) or (direction not in ['North', 'South', 'East', 'West'] and min_distance == 2):
                    items_descriptions['immediate'].append((min_distance, item))
                elif min_distance <= 10:
                    items_descriptions['nearby'].append((min_distance, item))
                elif min_distance <= 20:
                    items_descriptions['distant'].append((min_distance, item))
                else:
                    items_descriptions['remote'].append((min_distance, item))

            for category in items_descriptions:
                items_descriptions[category] = sorted(items_descriptions[category])
            
            description.append(f"- {direction}: ")
            for category, items in items_descriptions.items():
                if items:
                    description.append(f"{category} ({', '.join([f'{item}' for _, item in items])}); ")
            description.append('\n')
        (facing_object, direction) = facing_object_and_direction
        description.append(closed_objects)
        description.append(f"- Facing {facing_object} on the {direction}.")
        return ''.join(description)


class SimplifiedStatsDescriptor:
    """Describes player's status and inventory in a simplified manner."""
    
    def describe(self, info):
        max_values = {'health': 9, 'food': 9, 'drink': 9, 'energy': 9}
        status_items = ['health', 'food', 'drink', 'energy']
        inventory = info['inventory']
        status_output = "Your status:\n"
        inventory_output = ""

        for item, value in inventory.items():
            if item in status_items:
                max_value = max_values.get(item, 9)
                status_output += f"- {item}: {value}/{max_value}\n"
            else:
                if item != 'reward' and value > 0:
                    inventory_output += f"- {item}: {value}\n"

        inventory_output = "Your inventory:\n" + inventory_output if inventory_output else "You have nothing in your inventory."
        return status_output + inventory_output


class SimplifiedStateDescriptor:
    """Provides a simplified description of the game state."""
    
    def __init__(self):
        self.scene_descriptor = SceneDescriptor()
        self.stats_descriptor = SimplifiedStatsDescriptor()

    def describe(self, episode_history):
        scene_description = self.scene_descriptor.describe(episode_history)
        stats_description = self.stats_descriptor.describe(episode_history)
        return f"{scene_description}\n{stats_description}"
