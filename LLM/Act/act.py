from plan import *
from __init__ import *
from utils import *
from descriptor import SimplifiedStateDescriptor


class Actor:

    def __init__(self, save_dir='./Act/trajectory', 
                 assets_dir='./Act/assets', 
                 initial_size=(600, 600), map_size=64, 
                 seed=1):
        # Load actions
        with open('./Act/action.json', 'r') as f:
            self._action = json.load(f)

        self._planner = Subtask_Planner()
        self._state_descriptor = SimplifiedStateDescriptor()
        
        self._time_step = 0
        self._total_reward = 0.0
        self._episode_history = dict()
        now = datetime.datetime.now()
        time_str = now.strftime("%Y-%m-%d_%H-%M-%S")
        if not os.path.exists(os.path.join(save_dir, str(seed))):
            os.makedirs(os.path.join(save_dir, str(seed)))
        self._img_save_dir = os.path.join(save_dir, str(seed), f'{time_str}', 'images')
        if not os.path.exists(self._img_save_dir):
            os.makedirs(self._img_save_dir)
        self._save_path = os.path.join(save_dir, str(seed), f'{time_str}', 'trajectory.json')

        self._transition = {'subtask': None}
        
        self._map_size = map_size
        self._initial_size = initial_size
        self._external_map = [['unexplored_area' for _ in range(64)] for _ in range(64)]
        self._seed = seed

        self._set_up_env(save_dir)
        self._set_up_assests(assets_dir)
        self._subtask_max_steps = 25
        # self.visualize_map()


    def _set_up_env(self, save_path):
        self._env = crafter.Env(seed=self._seed)
        self._env = crafter.Recorder(
            self._env, save_path,
            save_stats=False,
            save_episode=False,
            save_video=False,
        )
        self._env.reset()
        self._env.step(0)

        self._env.render()
        self._update_map()


    def _set_up_assests(self, assets_dir):
        self._assets = dict()
        for asset in os.listdir(assets_dir):
            asset_name = asset.removesuffix('.png')
            self._assets[asset_name] = Image.open(os.path.join(assets_dir, asset))


    def _update_map(self, player_rel_pos=(3, 4)):
        text_description = self._env.text_description()
        player_pos = self._env._player.pos
        # Since text_description is accessed via text_description.T, player_pos must be inverted for alignment.
        player_pos = (player_pos[1], player_pos[0])
        offset = tuple(player_pos_i - player_rel_pos_i for player_pos_i, player_rel_pos_i in zip(player_pos, player_rel_pos))
        
        for row_i, row in enumerate(text_description):
            for col_j, text_object in enumerate(row):
                object_pos = (offset[0] + row_i, offset[1] + col_j)

                if 0 <= object_pos[0] < len(self._external_map) and 0 <= object_pos[1] < len(self._external_map[0]):
                    self._external_map[object_pos[0]][object_pos[1]] = text_object
                else:
                    continue


    def visualize_map(self, image_size=16):
        canvas = Image.new('RGBA', (self._map_size*image_size, self._map_size*image_size))
        for y, row in enumerate(self._external_map):
            for x, element in enumerate(row):
                canvas.paste(self._assets[element], (x * image_size, y * image_size)) 

        plt.figure(figsize=(image_size, image_size))
        plt.imshow(canvas)
        plt.axis('off')
        plt.show()


    def main(self):
        done = False
        mapped_action = 0
        self._transition['previous_actions'] = []

        while not done:
            obs = self._env.render(self._initial_size) 
            import cv2
            obs = cv2.cvtColor(obs, cv2.COLOR_BGR2RGB)
            cv2.imwrite(os.path.join(self._img_save_dir, f'{self._time_step}.png'), obs)
            self._update_map()

            info = {
                'text_description': self._external_map,
                'inventory': self._env.get_player_inventory(),
                'time_step': self._time_step,
            }
            state_description = self._state_descriptor.describe(info)
            available_actions = self._env._player._available_action(state_description)
            self._transition.update([('state_description', state_description), 
                                     ('available_actions', available_actions), 
                                     ('inventory', info['inventory']),
                                     ('external_map', self._external_map), 
                                     ('text_description', self._env.text_description().tolist())])

            self.act()
            action = self._transition['action']
            _, mapped_action = map_action(action)   
            _, reward, done, _ = self._env.step(mapped_action)
            self._total_reward += reward
            
            self._episode_history[self._time_step] = {
                'subgoal': self._transition['subgoal'],
                'subtask': self._transition['subtask'], 
                'state_description': self._transition['state_description'], 
                'termination': self._transition['termination'], 
                'action': self._transition['action'], 
                'previous_actions': self._transition['previous_actions'][-3:],
                'evolved_dynamics': self._transition['filtered_evolved_dynamics'],
                'unfiltered_evolved_dynamics': self._transition['evolved_dynamics'],
                'total_reward': self._total_reward,
            }
            with open(self._save_path, 'w') as f:
                json.dump(self._episode_history, f, indent=4)

            self._time_step += 1
            print('toatl reward:', self._total_reward)
            print('state_description:', state_description)
            print('action', self._transition['action'])
            print('seed', self._seed)
            print('==========================================================================================')
        

    def act(self):
        if self._env._player.sleeping:
            return 
        termination, termination_reason = self._terminate_plan()
        self._transition['termination'] = {termination: termination_reason}

        if self._subtask_max_steps == 0:
            self._transition['subtask'] = None
            self._transition['previous_subtask'] = f"The previous subtask: {self._transition['subtask']} has been terminated, because the maximum steps have been reached."
            self._transition['initial_state_description'] = self._transition['state_description']
            print('Terminating: Maximum steps have been reached.')
            transition = self._planner.plan(self._transition)
            self._transition = transition
            self._transition.update([('previous_actions', [])])
            self._subtask_max_steps = 25

        if termination:
            previous_subtask = f"The previous subtask: {self._transition['subtask']} has been terminated, because {termination_reason}."
            print('Terminating: ', termination_reason)
            self._transition['previous_subtask'] = previous_subtask
            self._transition['initial_state_description'] = self._transition['state_description']
            transition = self._planner.plan(self._transition)
            self._transition = transition
            self._transition.update([('previous_actions', [])])
            self._subtask_max_steps = 25
        self.select_action()
        

    def _terminate_plan(self):
        if self._transition['subtask'] is None:
            return True, None
        
        prefix_prompt = "You are a helpful assistant, tasked with deciding whether the current subtask should be terminated or not. Please answer in JSON format."
        output_format = '{"Justification": "...", "Termination_decision": "True/False"}'
        prompt = f"""
        Given the following details:
        - Subtask description: {self._transition['subtask']},
        - Current observation: {self._transition['state_description']},
        - Initial observation: {self._transition['initial_state_description']},
        - Previous executed actions: {self._transition['previous_actions'][-3:]}
        you are asked to decide whether the subtask should be terminated or not.

        For deciding whether to terminate the subtask, consider:
        - The previous action, provided it was executed successfully.
        - The difference between the initial and current observations, including the inventory changes.

        The subtask should be terminated, and the output should be 'True' only if any of its termination conditions are met. 
        Otherwise, if none of the termination conditions are met, the subtask should continue running, and the output should be 'False'.
        
        Justify whether the termination conditions are met or not first, and then provide the termination decision.
        Output in this format: {output_format}.
        """
        terminiation_decision = None
        while terminiation_decision is None:
            termination = gpt_json(prefix_prompt, prompt)
            termination = json.loads(termination)
            try:
                terminiation_decision = termination['Termination_decision']
                justification = termination['Justification']
            except KeyError:
                terminiation_decision = None
        if 'true' in str(terminiation_decision).lower():
            return True, justification
        return False, justification


    def select_action(self):
        action = None
        feedback = set()
        while action not in self._transition['available_actions']:
            prefix_prompt = "You are a helpful assistant, tasked with selecting the best action for completing the current subtask. Please provide your answer in JSON format."
            action_format = """{
                'subtask_related_objects': {'object_1_name': {'location': object 1's location, 'dynamic': object 1's dynamic}, ......},
                'top_3_actions_objects': {'action_name_1': {'object_1_name': {'location': object 1's location, 'dynamic': object 1's dynamic}, ......}
                                          'action_name_2': ......
                                          'action_name_3': ......},
                'top_3_actions_consequences': {'action_name_1': 'consequences', 'action_name_2': 'consequences', 'action_name_3': 'consequences'},
                'action_name': 'action_name',
                'action_justification': 'justification'
            }"""
            prompt = f"""
            Given the following details:
            - Current observation: {self._transition['state_description']}
            - Current subtask's description: {self._transition['subtask']}
            - Previous actions: {self._transition['previous_actions'][-3:]}
            - Primitive dynamics: {self._transition['primitive_dynamics']}
            - Evolved dynamics: {self._transition['filtered_evolved_dynamics']}

            You are asked to:
            - identify the objects related to the current subtask and provide their locations and dynamics.
            - select the top 3 actions that contributes to the subtask by either moving closer to the object or interacting with the object; and provide all the objects and dynamics directly related with each action.
            - based on each action's related objects, provide the rationale and detailed consequences of executing each action on the objects.
            - select the best action to execute next and provide the justification for your choice.

            Lastly, select the action only from the available actions: {self._transition['available_actions']}; {feedback}.

            Note: Avoid unnecessary crafting and placement if the items are within reachable distance.
            
            Please format your response in the following format: {action_format}
            """
            action_and_thoughts = gpt_json(prefix_prompt, prompt)
            try:
                action_and_thoughts = json.loads(action_and_thoughts)
                action = action_and_thoughts['action_name']
                thoughts = f"At timestep {self._time_step}, you executed {action} because {action_and_thoughts['action_justification']}."
            except:
                print('keyerror')
                print(action_and_thoughts)
                action = None
            if action not in self._transition['available_actions']:
                print('invalid action: ', action)
                feedback.add(f'{action} is not available in the current state.')
                continue
        self._transition['action'] = action
        self._transition['previous_actions'].append(thoughts)
        self._subtask_max_steps -= 1


if __name__ == '__main__':
    actor = Actor()
    actor.main()