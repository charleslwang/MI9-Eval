import json
import os
import argparse
from collections import defaultdict
import numpy as np
from scipy.stats import wilcoxon

def load_evaluation_files(input_dir):
    """Find and load all individual evaluation.json files."""
    eval_files = []
    for root, _, files in os.walk(input_dir):
        if 'evaluation.json' in files:
            # Ignore the summary file in the root directory
            if os.path.samefile(root, input_dir):
                continue
            eval_files.append(os.path.join(root, 'evaluation.json'))
    return eval_files

def parse_scores(eval_files):
    """Parse all evaluation files and extract performance scores for each framework."""
    # A nested dictionary to hold lists of scores: metric -> framework -> [scores]
    scores = defaultdict(lambda: defaultdict(list))

    for file_path in eval_files:
        with open(file_path, 'r') as f:
            try:
                data = json.load(f)
                comparison_data = data.get('performance_comparison', {})

                for framework, framework_data in comparison_data.items():
                    # Collect governance maturity score
                    maturity_score = framework_data.get('governance_maturity_score')
                    if maturity_score is not None:
                        scores['governance_maturity_score'][framework].append(maturity_score)

                    # Collect detection metrics
                    detection_metrics = framework_data.get('detection_metrics', {})
                    for metric, value in detection_metrics.items():
                        if isinstance(value, (int, float)):
                            scores[metric][framework].append(value)

                    # Collect actionable intelligence metrics
                    actionable_intel = framework_data.get('actionable_intelligence', {})
                    for metric, value in actionable_intel.items():
                        if isinstance(value, (int, float)):
                            scores[metric][framework].append(value)

            except (json.JSONDecodeError, KeyError) as e:
                print(f"[WARNING] Skipping file {file_path} due to error: {e}")

    return scores

def print_statistics_report(scores):
    """Calculate and print the statistical analysis report."""
    frameworks = ['mi9_governance', 'opentelemetry', 'langchain']
    metrics = sorted(scores.keys())

    print("--- Statistical Performance Analysis ---")
    print(f"Based on {len(scores['governance_maturity_score']['mi9_governance'])} valid evaluation samples.\n")

    for metric in metrics:
        print(f"\n--- Metric: {metric} ---")
        header = f"{'Framework':<20} | {'Mean':<10} | {'Std Dev':<10}"
        print(header)
        print("-" * len(header))

        metric_scores = scores[metric]
        for framework in frameworks:
            if framework in metric_scores:
                mean = np.mean(metric_scores[framework])
                std = np.std(metric_scores[framework])
                print(f"{framework:<20} | {mean:<10.4f} | {std:<10.4f}")

        # Perform significance testing against MI9
        print("\n  Significance Tests (Wilcoxon signed-rank vs. mi9_governance):")
        mi9_scores = metric_scores.get('mi9_governance')
        if mi9_scores:
            for framework_to_compare in ['opentelemetry', 'langchain']:
                compare_scores = metric_scores.get(framework_to_compare)
                if compare_scores and len(mi9_scores) == len(compare_scores):
                    # Wilcoxon test requires non-zero differences
                    diff = np.array(mi9_scores) - np.array(compare_scores)
                    if np.any(diff):
                        stat, p_value = wilcoxon(diff)
                        significance = '***' if p_value < 0.001 else '**' if p_value < 0.01 else '*' if p_value < 0.05 else 'ns'
                        print(f"    - vs. {framework_to_compare:<15}: p-value = {p_value:.4e} ({significance})")
                    else:
                        print(f"    - vs. {framework_to_compare:<15}: No difference in scores.")

    print("\n--- End of Report ---")
    print("Significance levels: *** p < 0.001, ** p < 0.01, * p < 0.05, ns (not significant)")

def main():
    parser = argparse.ArgumentParser(description="Perform statistical analysis on MI9 evaluation results.")
    parser.add_argument(
        '--input-dir',
        type=str,
        default='../data',
        help='Directory containing the per-scenario evaluation run folders.'
    )
    args = parser.parse_args()

    print(f"Running analysis on: {os.path.abspath(args.input_dir)}")
    eval_files = load_evaluation_files(args.input_dir)

    if not eval_files:
        print("[ERROR] No 'evaluation.json' files found in the subdirectories. Aborting.")
        return

    scores = parse_scores(eval_files)
    print_statistics_report(scores)

if __name__ == '__main__':
    main()
