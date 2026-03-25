import os
from pathlib import Path

#####################################################
#                Global Definitions                 #
#####################################################
BASE_DIR = Path(__file__).resolve().parent
PATTERN_PATH = BASE_DIR.parent / "patterns"


def load_prompt_template(name, template_type):
    if (not template_type == 'prompt_template' and
            not template_type == 'standard_task' and
            not template_type == 'system_prompt'):
        print("Invalid template type ...")
        return None

    template_path = PATTERN_PATH / (template_type + "s")
    template_name = name + ".md"

    available_templates = os.listdir(template_path)
    if template_name not in available_templates:
        print("Template name does not exist ...")
        return None

    with open(template_path / template_name, "r", encoding="utf-8") as file:
        prompt_template = file.read()
    return prompt_template
