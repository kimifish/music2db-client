# pyright: basic
# pyright: reportAttributeAccessIssue=false

import logging
import re
from rich.pretty import pretty_repr
from rich.theme import Theme
from rich.traceback import install as install_rich_traceback
from rich.tree import Tree
# from deepdiff import DeepDiff
# from state import State
from kimiconfig import Config

cfg = Config()
log = logging.getLogger('ai_server.utils')
install_rich_traceback(show_locals=True)

# def _log_state(state: State, tabs: int = 0):
#     log.debug(pretty_repr(state, indent_size=4, max_string=50))


# def _parse_key(key: str):
#     # log.debug(f"key: {key}")
#     # Regular expression pattern to match root['path1']['path2']...[index]
#     pattern = r"^root(\['(?:[^']+)'\])+\[(\d+)\]$"
#     path_pattern = r"'\s*([^']*)\s*'"  # Pattern to extract individual path segments

#     main_match = re.match(pattern, key)
#     if main_match:
#         # Extract all path segments
#         path_segments = re.findall(path_pattern, main_match.group(0))

#         # Extract the index, assuming the last part of the main match
#         index = int(main_match.group(2))
#         return path_segments, index
#     else:
#         # log.error("Input string is not in the expected format")
#         # raise ValueError(f"Input string is not in the expected format: {key}")
#         return [], 0


# def _grow_branch(tree: Tree, action: str, list_of_names: list[str], index: int, value):
#     current_branch = tree
#     for name in list_of_names:
#         current_branch = current_branch.add(f"[light_steel_blue]+ {name}[/]")
#     for b in range(0, index):
#         current_branch.add(" ... ")
#     current_branch.add(pretty_repr(value))
#     return tree

def sep_line(name: str, length: int = 90, color: str = 'light steel blue', symbol: str = '─'):
    line_length = (length - len(name) - 2) // 2
    line = f"{symbol * line_length} {name} {symbol * line_length}"
    while len(line) < length:
        line += symbol
    while len(line) > length:
        line = line[:-1]
    log.debug(f"[{color}]{line}[/]")


# def log_diff(dict1, dict2):
#     diff = DeepDiff(dict1, dict2)
#     for key, value in diff.items():
#         try:
#             if key.endswith('added'):
#                 for k, v in value.items():
#                     log.debug(f'[chartreuse2 underline] + {k}:[/]\n{pretty_repr(v)}')
#             elif key.endswith('removed'):
#                 for k, v in value.items():
#                     log.debug(f'[deep_pink4 underline] - {k}:[/]\n{pretty_repr(v)}')
#             elif key.endswith('changed'):
#                 for k, v in value.items():
#                     log.debug(f'[orange3 underline] ~ {k}:[/]\n{pretty_repr(v)}')
#             else:
#                 log.debug(f"{key}:" + pretty_repr(value))
#         except AttributeError as e:
#             log.error(f'Key {key} does not contain items.')

common_theme = Theme({
    "repr.attrib_name": "khaki3",
    "repr.attrib_value": "medium_orchid3",
    "repr.number": "pale_turquoise1",
    "repr.str": "cadet_blue",
    "repr.none": "navajo_white3",
    "repr.bool_true": "medium_spring_green",
    "repr.bool_false": "light_salmon3",
    "repr.call": "medium_purple3",
    "repr.ellipsis": "medium_orchid3",
    'repr.uuid': "plum4",
    
    })

log_theme = Theme({
    "repr.attrib_name": "khaki3",
    "repr.attrib_value": "medium_orchid3",
    "repr.number": "pale_turquoise1",
    "repr.str": "cadet_blue",
    "repr.none": "navajo_white3",
    "repr.bool_true": "medium_spring_green",
    "repr.bool_false": "light_salmon3",
    "repr.call": "medium_purple3",
    "repr.ellipsis": "medium_orchid3",
    'repr.uuid': "plum4",
    
    })

prompt_theme = Theme({
    "repr.attrib_name": "tan",
    "repr.attrib_value": "orchid",
    "repr.number": "pale_turquoise1",
    "repr.str": "grey63",
    "repr.none": "navajo_white3",
    "repr.bool_true": "medium_spring_green",
    "repr.bool_false": "light_salmon3",
    "repr.call": "medium_purple3",
    "repr.ellipsis": "medium_orchid3",
    'repr.uuid': "plum4",
    
    })
