from __init__ import *

def map_action(text_action):
    if 'face' in text_action:
        text_action = text_action.replace('face', 'move')
    for action, number in action_mapping.items():
        if action in text_action:
            return action, number
        
    return 'do(mine, collect, attack)', 5