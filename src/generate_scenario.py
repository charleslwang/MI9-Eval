import os
import sys
import json
import time
import argparse
from typing import Optional, Dict, List, Any
import queue
import threading
import re

# Global lock for thread-safe file and directory operations
file_lock = threading.Lock()

# --- Scenario Classes (Archetypes) ---
SCENARIO_CLASSES = [
    {"class_name": "Normal Operation", "description": "Baseline agent behavior without any induced faults."},
    {"class_name": "Goal Drift", "description": "Agent's goals diverge from initial objectives over time."},
    {"class_name": "Resource Overconsumption", "description": "Agent uses excessive computational or financial resources."},
    {"class_name": "Unauthorized Access Attempt", "description": "Agent attempts to access data or systems it is not authorized for."},
    {"class_name": "Prompt Injection Response", "description": "Agent's behavior is manipulated through malicious user prompts."},
    {"class_name": "Data Evasion Attack", "description": "Agent is fed misleading data to alter its performance."},
    {"class_name": "Model Inversion Attack", "description": "Agent's internal model parameters are reverse-engineered."}
]

def load_prompt_template(prompt_file: str) -> Optional[str]:
    """Loads a prompt template from a file."""
    try:
        with open(prompt_file, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"[ERROR] Prompt file not found at: {prompt_file}")
        return None

def extract_json_from_response(response_text: str) -> Optional[str]:
    """Extracts a JSON string from a response, handling markdown and other text."""
    if not response_text:
        return None

    # Regex to find JSON wrapped in markdown ```json ... ```
    match = re.search(r"```json\n(.*?)\n```", response_text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Fallback: find the first '{' or '[' and the last '}' or ']'
    start_bracket = -1
    end_bracket = -1

    first_curly = response_text.find('{')
    first_square = response_text.find('[')

    if first_curly == -1:
        start_bracket = first_square
    elif first_square == -1:
        start_bracket = first_curly
    else:
        start_bracket = min(first_curly, first_square)

    if start_bracket == -1:
        return None

    last_curly = response_text.rfind('}')
    last_square = response_text.rfind(']')
    end_bracket = max(last_curly, last_square)

    if end_bracket == -1 or end_bracket < start_bracket:
        return None

    return response_text[start_bracket:end_bracket + 1].strip()

def call_gemini_api(prompt: str, api_key: str, model: str) -> Optional[str]:
    """Calls the Google Gemini API and returns the response text."""
    try:
        import google.generativeai as genai
    except ImportError:
        print("[ERROR] The 'google-generativeai' package is not installed.")
        sys.exit(1)

    genai.configure(api_key=api_key)
    model_instance = genai.GenerativeModel(model_name=model)
    try:
        request_options = {"timeout": 120}
        response = model_instance.generate_content(prompt, request_options=request_options)
        return response.text
    except Exception as e:
        print(f"[ERROR] An error occurred with the Gemini API: {e}")
        return None

def generate_scenario(scenario_class: str, api_key: str, model: str, prompt_template: str) -> Optional[str]:
    """Generates a scenario JSON string based on a class."""
    print(f"Generating scenario for class '{scenario_class}'...")
    prompt = prompt_template.replace("{scenario_class}", scenario_class)

    response_text = call_gemini_api(prompt, api_key, model)
    if not response_text:
        print(f"[ERROR] API call for scenario failed for class '{scenario_class}'.")
        return None

    extracted_json = extract_json_from_response(response_text)
    if not extracted_json:
        print(f"[ERROR] Failed to extract scenario JSON from API response: {response_text}")
        return None

    try:
        json.loads(extracted_json)
        return extracted_json
    except (json.JSONDecodeError, TypeError):
        print(f"[ERROR] Failed to parse scenario JSON from API response: {extracted_json}")
        return None

def get_next_run_number(base_dir: str) -> int:
    """Gets the next available run number in a thread-safe manner."""
    os.makedirs(base_dir, exist_ok=True)
    existing_runs = [int(d) for d in os.listdir(base_dir) if d.isdigit()]
    return max(existing_runs) + 1 if existing_runs else 1

def worker(task_queue: queue.Queue, args: argparse.Namespace, api_key: str, prompt_template: str):
    """Worker thread function to process scenario generation tasks."""
    while not task_queue.empty():
        try:
            scenario_class = task_queue.get_nowait()
        except queue.Empty:
            break

        scenario_json_str = generate_scenario(scenario_class, api_key, args.model, prompt_template)

        if scenario_json_str:
            with file_lock:
                run_number = get_next_run_number(args.output_dir)
                run_dir = os.path.join(args.output_dir, str(run_number))
                os.makedirs(run_dir, exist_ok=True)

                scenario_path = os.path.join(run_dir, 'scenario.json')
                with open(scenario_path, 'w') as f:
                    f.write(scenario_json_str)
                print(f"Successfully generated and saved scenario to {scenario_path}")
        else:
            print(f"[ERROR] Failed to generate scenario for class '{scenario_class}', skipping.")

        task_queue.task_done()

def main():
    # Determine project root to build absolute paths for defaults
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_output_dir = os.path.join(project_root, 'data')
    default_prompt_path = os.path.join(project_root, 'prompts', 'scenario_prompt.txt')

    parser = argparse.ArgumentParser(description="Generate synthetic scenarios for MI9 evaluation.")
    parser.add_argument("--output-dir", default=default_output_dir, help="Base directory to save the output folders.")
    parser.add_argument("--count", type=int, default=1, help="Number of scenarios to generate per class.")
    parser.add_argument("--model", default="gemini-1.5-flash-latest", help="Gemini model for generation.")
    parser.add_argument("--api-key", help="Google API key (or set GOOGLE_API_KEY).")
    parser.add_argument("--classes", nargs='+', help="Specify one or more scenario classes to generate.")
    parser.add_argument("--scenario-prompt", default=default_prompt_path, help="Path to the scenario prompt file.")
    parser.add_argument("--num-workers", type=int, default=4, help="Number of concurrent threads.")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[ERROR] Google API key must be provided.")
        sys.exit(1)

    scenario_prompt_template = load_prompt_template(args.scenario_prompt)
    if not scenario_prompt_template:
        sys.exit(1)

    target_classes = [c['class_name'] for c in SCENARIO_CLASSES if c['class_name'] in args.classes] if args.classes else [c['class_name'] for c in SCENARIO_CLASSES]

    task_queue = queue.Queue()
    for scenario_class in target_classes:
        for _ in range(args.count):
            task_queue.put(scenario_class)

    threads = []
    for _ in range(args.num_workers):
        thread = threading.Thread(target=worker, args=(task_queue, args, api_key, scenario_prompt_template))
        threads.append(thread)
        thread.start()

    task_queue.join()

    for thread in threads:
        thread.join()

    print("\nAll scenarios generated.")

if __name__ == "__main__":
    main()
