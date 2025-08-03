"""
Evaluate governance frameworks using LLMs as judges.
"""

import os
import json
import time
import argparse
import random
from typing import List, Dict, Any, Optional
import openai
import sys
import queue
import threading
import re
from collections import defaultdict
from datetime import datetime

try:
    import google.generativeai as genai
except ImportError:
    print("[ERROR] The 'google-generativeai' package is not installed or not in the current Python environment.")
    print("Please install it by running: pip install google-generativeai")
    sys.exit(1)


# Global lock for thread-safe operations
file_lock = threading.Lock()

def load_prompt_template(prompt_file: str) -> Optional[str]:
    """Load a prompt template from a file."""
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


def process_run_directory(run_dir, prompt_template, api_key, model):
    scenario_path = os.path.join(run_dir, 'scenario.json')
    governance_path = os.path.join(run_dir, 'governance.json')

    try:
        with open(scenario_path, 'r') as f:
            scenario_str = f.read()
        with open(governance_path, 'r') as f:
            all_logs = json.load(f)

        # Separate logs by framework for cleaner injection into the prompt
        mi9_logs = [log for log in all_logs if log.get('type') == 'MI9_GOVERNANCE']
        otel_logs = [log for log in all_logs if log.get('type') == 'OPENTELEMETRY']
        langchain_logs = [log for log in all_logs if log.get('type') == 'LANGCHAIN']

        prompt = prompt_template.format(
            scenario_json=scenario_str,
            mi9_logs_json=json.dumps(mi9_logs, indent=2),
            opentelemetry_logs_json=json.dumps(otel_logs, indent=2),
            langchain_logs_json=json.dumps(langchain_logs, indent=2)
        )

    except FileNotFoundError as e:
        print(f"[ERROR] Skipping directory {run_dir}: {e.filename} not found.")
        return None
    except json.JSONDecodeError:
        print(f"[ERROR] Skipping directory {run_dir}: Invalid JSON in data files.")
        return None

    # Call the Gemini API
    try:
        genai.configure(api_key=api_key)
        model_name = model if model.startswith("models/") else f"models/{model}"
        model = genai.GenerativeModel(model_name)
        
        request_options = {"timeout": 120}  # 120 seconds
        response = model.generate_content(
            prompt,
            request_options=request_options
        )
        return extract_json_from_response(response.text)
    except Exception as e:
        print(f"[ERROR] An error occurred with the Gemini API in {run_dir}: {e}")
        return None


def worker(
    task_queue: queue.Queue,
    results_list: list,
    file_lock: threading.Lock,
    api_key: str,
    model: str,
    prompt_template: str
):
    while True:
        try:
            run_dir = task_queue.get_nowait()
        except queue.Empty:
            break

        print(f"Evaluating governance for: {run_dir}")
        extracted_json = process_run_directory(run_dir, prompt_template, api_key, model)

        if extracted_json:
            # Save the individual evaluation file
            output_path = os.path.join(run_dir, 'evaluation.json')
            try:
                with open(output_path, 'w') as f:
                    # The extracted content might be a JSON string inside a markdown block
                    # So we load and dump it to ensure it's clean JSON
                    json_content = json.loads(extracted_json)
                    json.dump(json_content, f, indent=2)
                print(f"[SUCCESS] Saved evaluation for {run_dir}")
            except (json.JSONDecodeError, IOError) as e:
                print(f"[ERROR] Failed to save evaluation.json for {run_dir}: {e}")

            with file_lock:
                results_list.append(extracted_json)
                # print(f"Successfully evaluated for {run_dir}")
        else:
            print(f"[ERROR] Failed to evaluate for {run_dir}")
        
        task_queue.task_done()


def aggregate_and_save_summary(all_evaluations: List[str], output_dir: str):
    if not all_evaluations:
        print("[WARNING] No evaluation results to aggregate.")
        return

    all_parsed_evals = [json.loads(e) for e in all_evaluations if e]
    total_samples = len(all_parsed_evals)

    # --- Aggregate Performance Comparison --- #
    frameworks = ["mi9_governance", "opentelemetry", "langchain"]
    perf_data = {}
    for framework in frameworks:
        rates, positives, risk_coverage_rates = [], [], []
        detected_violations, missed_violations, false_positives = set(), set(), set()
        clarity_scores, predictive_scores, maturity_scores, proactive_intervention_rates = [], [], [], []

        for e in all_parsed_evals:
            comp = e.get("performance_comparison", {}).get(framework, {})
            if not comp: continue

            # Aggregate new maturity score
            maturity_scores.append(comp.get("governance_maturity_score", 0))

            # Aggregate detection metrics
            metrics = comp.get("detection_metrics", {})
            rates.append(metrics.get("detection_rate", 0))
            positives.append(metrics.get("false_positive_rate", 0))
            risk_coverage_rates.append(metrics.get("risk_coverage_rate", 0))
            for v in metrics.get("violations_detected", []): detected_violations.add(v)
            for v in metrics.get("violations_missed", []): missed_violations.add(v)
            for v in metrics.get("false_positives", []): false_positives.add(v)

            # Aggregate actionable intelligence metrics
            intelligence = comp.get("actionable_intelligence", {})
            clarity_scores.append(intelligence.get("causal_chain_clarity_score", 0))
            predictive_scores.append(intelligence.get("predictive_alerting_score", 0))
            proactive_intervention_rates.append(intelligence.get("proactive_intervention_rate", 0))
        
        if not rates: continue

        perf_data[framework] = {
            "governance_maturity_score_avg": sum(maturity_scores) / len(maturity_scores) if maturity_scores else 0,
            "detection_metrics_avg": {
                "detection_rate_avg": sum(rates) / len(rates),
                "false_positive_rate_avg": sum(positives) / len(positives),
                "risk_coverage_rate_avg": sum(risk_coverage_rates) / len(risk_coverage_rates) if risk_coverage_rates else 0,
                "total_violations_detected": sorted(list(detected_violations)),
                "total_violations_missed": sorted(list(missed_violations)),
                "total_false_positives": sorted(list(false_positives))
            },
            "actionable_intelligence_avg": {
                "causal_chain_clarity_score_avg": sum(clarity_scores) / len(clarity_scores) if clarity_scores else 0,
                "predictive_alerting_score_avg": sum(predictive_scores) / len(predictive_scores) if predictive_scores else 0,
                "proactive_intervention_rate_avg": sum(proactive_intervention_rates) / len(proactive_intervention_rates) if proactive_intervention_rates else 0
            }
        }

    # --- Aggregate Appendix Statistics --- #
    scenario_category_counts = defaultdict(int)
    emergent_risk_counts = defaultdict(int)
    scenario_keys_to_track = ["agent_type", "agent_architecture", "industry", "region", "attack_type", "safety_criticality"]
    scenario_breakdown = {key: defaultdict(int) for key in scenario_keys_to_track}

    for e in all_parsed_evals:
        details = e.get("scenario_details", {})
        scenario_category_counts[details.get("scenario_category", "Unknown")] += 1
        for risk in e.get("ground_truth", {}).get("emergent_risks_identified", []):
            emergent_risk_counts[risk] += 1
        
        for key in scenario_keys_to_track:
            if key in details:
                scenario_breakdown[key][details[key]] += 1

    summary = {
        "metadata": {
            "report_generated_at": datetime.utcnow().isoformat(),
            "total_scenarios_evaluated": total_samples
        },
        "performance_summary": perf_data,
        "appendix_statistics": {
            "scenario_category_distribution": dict(scenario_category_counts),
            "emergent_risk_distribution": dict(emergent_risk_counts),
            "scenario_attribute_breakdown": {k: dict(v) for k, v in scenario_breakdown.items()}
        }
    }

    output_path = os.path.join(output_dir, 'evaluation_summary.json')
    try:
        with open(output_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"[SUCCESS] Aggregated summary saved to {output_path}")
    except IOError as e:
        print(f"[ERROR] Could not write summary file to {output_path}: {e}")


def main():
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_input_dir = os.path.join(project_root, 'data')
    default_prompt_path = os.path.join(project_root, 'prompts', 'evaluation.txt')

    parser = argparse.ArgumentParser(description="Evaluate MI9 governance logs.")
    parser.add_argument("--input-dir", default=default_input_dir, help="Directory with run folders.")
    parser.add_argument("--num-workers", type=int, default=4, help="Number of concurrent threads.")
    parser.add_argument("--model", default="gemini-1.5-flash-latest", help="Gemini model for evaluation.")
    parser.add_argument("--api-key", help="Google API key.")
    parser.add_argument("--evaluation-prompt", default=default_prompt_path, help="Path to the evaluation prompt.")
    args = parser.parse_args()

    api_key = args.api_key or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("Error: GOOGLE_API_KEY not found.")
        sys.exit(1)

    prompt_template = load_prompt_template(args.evaluation_prompt)
    if not prompt_template:
        sys.exit(1)

    if not os.path.isdir(args.input_dir):
        print(f"Error: Input directory not found at {args.input_dir}")
        sys.exit(1)

    task_queue = queue.Queue()
    run_dirs = [os.path.join(args.input_dir, d) for d in os.listdir(args.input_dir) if os.path.isdir(os.path.join(args.input_dir, d))]
    for run_dir in run_dirs:
        task_queue.put(run_dir)

    if task_queue.empty():
        print("No run directories found to evaluate.")
        return

    results_list = []
    threads = []
    for _ in range(args.num_workers):
        thread = threading.Thread(target=worker, args=(task_queue, results_list, file_lock, api_key, args.model, prompt_template))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    aggregate_and_save_summary(results_list, args.input_dir)

if __name__ == "__main__":
    main()
