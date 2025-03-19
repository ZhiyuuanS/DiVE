import os
import time
import json
import sys
import datetime
import pathlib
import argparse
import collections
from PIL import Image
from collections import Counter
from collections import defaultdict 
import matplotlib.pyplot as plt

import tqdm
import numpy as np
import imageio
import tiktoken
from typing import List, Optional
from openai import OpenAI

sys.path.append('../')

import random
import crafter

ACTION_SPACE_NUM = 17
CONTEXT_WINDOWS = 128000
GPT_VERSION = 'gpt-4o'
OPENAI_API_KEY = ""

client = OpenAI(api_key=OPENAI_API_KEY)

action_mapping = {
    'idle': 0,
    'move_west': 1,
    'move_east': 2,
    'move_north': 3,
    'move_south': 4,
    'do': 5,
    'sleep': 6,
    'place_stone': 7,
    'place_table': 8,
    'place_furnace': 9,
    'place_plant': 10,
    'make_wood_pickaxe': 11,
    'make_stone_pickaxe': 12,
    'make_iron_pickaxe': 13,
    'make_wood_sword': 14,
    'make_stone_sword': 15,
    'make_iron_sword': 16,
    }

def gpt(prefix_prompt: str, description: str) -> str:
    num_retries = 20
    retry_interval = 5
    for i in range(num_retries):
        try:
            response = client.chat.completions.create(
                model=GPT_VERSION,
                messages=[
                    {"role": "system", "content": prefix_prompt},
                    {"role": "user", "content": description},
                ],
                seed=0
            )
            return response.choices[0].message.content
        except Exception as e:
            handle_error(e, i, num_retries, retry_interval)

def gpt_json(prefix_prompt: str, description: str) -> str:
    num_retries = 20
    retry_interval = 5
    for i in range(num_retries):
        try:
            response = client.chat.completions.create(
                model=GPT_VERSION,
                messages=[
                    {"role": "system", "content": prefix_prompt},
                    {"role": "user", "content": description},
                ],
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content
        except Exception as e:
            handle_error(e, i, num_retries, retry_interval)


def gpt_3_json(prefix_prompt: str, description: str) -> str:
    num_retries = 20
    retry_interval = 5
    for i in range(num_retries):
        try:
            response = client.chat.completions.create(
                model='gpt-3.5-turbo-0125',
                messages=[
                    {"role": "system", "content": prefix_prompt},
                    {"role": "user", "content": description},
                ],
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content
        except Exception as e:
            handle_error(e, i, num_retries, retry_interval)

            

def handle_error(e, current_retry, max_retries, retry_interval):
    print(f"An error occurred: {e}")
    if current_retry < max_retries - 1:
        print(f"Retrying in {retry_interval} seconds...")
        time.sleep(retry_interval)
    else:
        print("Reached maximum number of retries. Exiting.")
