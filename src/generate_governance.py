import os
import json
import sys
import asyncio
import argparse
import re
from typing import Optional, Dict, List

def load_json_file(file_path: str) -> Optional[Dict]:
    """Loads a JSON file from the specified path."""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"[ERROR] Could not load or parse JSON from {file_path}: {e}")
        return None

def load_prompt_template(path: str) -> Optional[str]:
    """Loads a prompt template from a file."""
    try:
        with open(path, 'r') as f:
            return f.read()
    except FileNotFoundError:
        print(f"[ERROR] Prompt file not found at: {path}")
        return None

async def call_gemini_api(prompt: str, api_key: str, model: str) -> Optional[str]:
    """Asynchronously call Google Gemini API."""
    try:
        import google.generativeai as genai
    except ImportError:
        print("[ERROR] The 'google-generativeai' package is not installed. Please run: pip install google-generativeai")
        sys.exit(1)

    genai.configure(api_key=api_key)
    model_instance = genai.GenerativeModel(model)
    
    request_options = {"timeout": 180}  # 3 minutes
    generation_config = {
        "temperature": 0.7,
        "max_output_tokens": 8192
    }

    response = await model_instance.generate_content_async(
        prompt,
        generation_config=generation_config,
        request_options=request_options
    )
    return response.text

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

async def generate_governance(scenario_data: Dict, api_key: str, model: str, prompt_template: str) -> Optional[str]:
    """Asynchronously generates a governance log JSON string based on a scenario, with retries."""
    scenario_json_str = json.dumps(scenario_data, indent=2)
    prompt = prompt_template.replace("{scenario_json}", scenario_json_str)
    
    max_retries = 3
    for attempt in range(max_retries):
        print(f"Generating governance log for scenario: {scenario_data.get('scenario_name', 'N/A')} (Attempt {attempt + 1}/{max_retries})")
        response_text = await call_gemini_api(prompt, api_key, model)
        
        if not response_text:
            print(f"[WARNING] API call failed for scenario: {scenario_data.get('scenario_name', 'N/A')}. Retrying...")
            await asyncio.sleep(2) # Wait before retrying
            continue

        extracted_json = extract_json_from_response(response_text)
        if not extracted_json:
            print(f"[WARNING] Failed to extract JSON on attempt {attempt + 1}. Response: {response_text[:200]}... Retrying...")
            await asyncio.sleep(2)
            continue

        try:
            json.loads(extracted_json)
            return extracted_json # Success!
        except (json.JSONDecodeError, TypeError):
            print(f"[ERROR] Failed to parse governance JSON from API response: {extracted_json}")
            return None

    print(f"[ERROR] Failed to generate a valid governance log for scenario {scenario_data.get('scenario_name', 'N/A')} after {max_retries} attempts.")
    return None

async def process_directory(data_dir: str, api_key: str, model: str, prompt_template: str, semaphore: asyncio.Semaphore, overwrite: bool):
    """Process a single data directory to generate governance logs, respecting the semaphore."""
    async with semaphore:
        try:
            scenario_path = os.path.join(data_dir, 'scenario.json')
            if not os.path.exists(scenario_path):
                return

            governance_path = os.path.join(data_dir, 'governance.json')
            if os.path.exists(governance_path) and not overwrite:
                print(f"[INFO] Skipping {os.path.basename(data_dir)} because 'governance.json' already exists. Use --overwrite to regenerate.")
                return

            print(f"--- Processing directory: {data_dir} ---")
            scenario_data = load_json_file(scenario_path)
            if not scenario_data:
                print(f"[WARNING] Could not load scenario from {scenario_path}, skipping.")
                return

            governance_json_str = await generate_governance(scenario_data, api_key, model, prompt_template)

            if governance_json_str:
                with open(governance_path, 'w') as f:
                    parsed_json = json.loads(governance_json_str)
                    json.dump(parsed_json, f, indent=2)
                print(f"Successfully generated and saved governance log to {governance_path}")
            else:
                print(f"[ERROR] Failed to generate governance log for {data_dir}, skipping.")
        finally:
            semaphore.release()

async def run_all(subdirectories: List[str], concurrency: int, api_key: str, model: str, prompt_template: str, overwrite: bool):
    """Sets up and runs the asyncio tasks for all subdirectories."""
    semaphore = asyncio.Semaphore(concurrency)
    tasks = [
        process_directory(data_dir, api_key, model, prompt_template, semaphore, overwrite)
        for data_dir in subdirectories
    ]
    await asyncio.gather(*tasks)

def main():
    # Determine project root to build absolute paths for defaults
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_base_dir = os.path.join(project_root, 'data')
    default_prompt_path = os.path.join(project_root, 'prompts', 'governance_prompt.txt')

    parser = argparse.ArgumentParser(description="Generate governance logs for scenarios in a directory.")
    parser.add_argument("base_dir", default=default_base_dir, nargs='?', help="Path to the base data directory containing run subdirectories.")
    parser.add_argument("--model", default="gemini-1.5-flash-latest", help="Gemini model for generation.")
    parser.add_argument("--api-key", help="Google API key (or set GOOGLE_API_KEY).")
    parser.add_argument("--governance-prompt", default=default_prompt_path, help="Path to the governance prompt file.")
    parser.add_argument("--concurrency", type=int, default=5, help="Number of parallel requests to make.")
    parser.add_argument("--overwrite", action='store_true', help="Overwrite existing governance.json files.")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("[ERROR] Google API key must be provided via --api-key or GOOGLE_API_KEY env var.")
        sys.exit(1)

    prompt_template = load_prompt_template(args.governance_prompt)
    if not prompt_template:
        sys.exit(1)

    if not os.path.isdir(args.base_dir):
        print(f"[ERROR] Base directory not found: {args.base_dir}")
        sys.exit(1)

    all_subdirectories = [
        os.path.join(args.base_dir, d)
        for d in os.listdir(args.base_dir)
        if os.path.isdir(os.path.join(args.base_dir, d))
    ]

    if not args.overwrite:
        subdirectories_to_process = []
        for d in all_subdirectories:
            if os.path.exists(os.path.join(d, 'governance.json')):
                print(f"[INFO] Skipping {os.path.basename(d)} because 'governance.json' already exists. Use --overwrite to regenerate.")
            else:
                subdirectories_to_process.append(d)
    else:
        subdirectories_to_process = all_subdirectories

    if not subdirectories_to_process:
        print(f"No new directories to process in {args.base_dir}.")
        return

    print(f"\nFound {len(subdirectories_to_process)} directories to process.")
    asyncio.run(run_all(subdirectories_to_process, args.concurrency, api_key, args.model, prompt_template, args.overwrite))

    print("\n--- Governance generation complete. ---")

if __name__ == "__main__":
    main()
