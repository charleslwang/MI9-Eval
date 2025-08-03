# MI9: Agentic AI Governance Framework & Synthetic Evaluation

MI9 is a framework for the synthetic generation, governance, and evaluation of agentic AI scenarios. It provides a suite of tools to automate the creation of complex scenarios, apply governance policies, and evaluate the outcomes using large language models.

## Overview

The framework operates in a three-stage pipeline:

1.  **Generate Scenarios**: Create diverse and complex scenarios based on predefined classes or archetypes. These are saved in a structured JSON format.
2.  **Generate Governance**: Apply a governance model to the generated scenarios. This stage produces a set of governance logs, also in JSON format, detailing the agent's reasoning and decisions.
3.  **Evaluate Governance**: Use an LLM as a judge to evaluate the quality and effectiveness of the generated governance based on the original scenario.

## Getting Started

### Installation

1.  Clone the repository:
    ```bash
    git clone <your-repo-url>
    cd MI9-Framework
    ```

2.  Install the required Python packages:
    ```bash
    pip install google-generativeai
    ```

3.  Set your API key. The scripts require a Google API key for the Gemini models. You can provide it in two ways:
    *   **Environment Variable (Recommended)**: `export GOOGLE_API_KEY='your-api-key-here'`
    *   **Command-line Argument**: Use the `--api-key` flag when running a script.

## Usage

The core logic is split into three scripts located in the `src/` directory.

### 1. Generating Scenarios

The `generate_scenario.py` script creates new scenarios concurrently. It uses a multithreaded worker queue to speed up the generation of multiple scenarios.

```bash
python src/generate_scenario.py \
    --output-dir data/ \
    --count 5 \
    --classes 'Autonomous Vehicle Navigation' 'Medical Diagnosis Assistant' \
    --num-workers 8
```

**Arguments**:
*   `--output-dir`: The base directory to save the output folders (default: `data`).
*   `--count`: The number of scenarios to generate *for each* class (default: `1`).
*   `--classes`: (Optional) A space-separated list of scenario classes to generate. If omitted, scenarios for all defined classes will be generated.
*   `--num-workers`: The number of concurrent threads to use for generation (default: `4`).
*   `--model`: The Gemini model to use (default: `gemini-1.5-flash-latest`).
*   `--api-key`: Your Google API key.
*   `--scenario-prompt`: Path to the scenario prompt file (default: `prompts/scenario_prompt.txt`).

### 2. Generating Governance

The `generate_governance.py` script takes the generated scenarios and produces corresponding governance documents. It uses `asyncio` for high-performance, concurrent API calls.

```bash
python src/generate_governance.py data/ --concurrency 10
```

**Arguments**:
*   `base_dir`: (Positional) The root directory containing the scenario run folders (default: `data`).
*   `--concurrency`: The number of parallel API requests to make (default: `5`).
*   `--model`: The Gemini model to use (default: `gemini-1.5-flash-latest`).
*   `--api-key`: Your Google API key.
*   `--governance-prompt`: Path to the governance prompt file (default: `prompts/governance_prompt.txt`).
*   `--overwrite`: By default, the script will skip any directory that already contains a `governance.json` file. Use this flag to force regeneration.

### 3. Evaluating Governance

The `evaluate_governance.py` script assesses the quality of the generated governance. It uses a multithreaded approach to evaluate multiple runs in parallel, producing a detailed quantitative analysis for each run and a final summary report.

After processing all individual run directories, the script generates two types of output:
1.  **`evaluation.json`**: Inside each run directory (e.g., `data/1/`), a detailed JSON file is created containing the performance and coverage analysis for that specific scenario.
2.  **`evaluation_summary.json`**: In the root of the input directory (e.g., `data/`), a single summary file is created that aggregates statistics across all runs, providing totals for the number of samples, a breakdown of scenario categories, and a count of emergent risk types. This file is ideal for generating appendix tables for a research paper.

```bash
python src/evaluate_governance.py \
    --input-dir data/ \
    --num-workers 8
```

**Arguments**:
*   `--input-dir`: The root directory containing the run folders to be evaluated (default: `data`).
*   `--num-workers`: The number of concurrent threads to use for evaluation (default: `4`).
*   `--model`: The Gemini model to use (default: `gemini-1.5-flash-latest`).
*   `--api-key`: Your Google API key.
*   `--evaluation-prompt`: Path to the evaluation prompt file (default: `prompts/evaluation.txt`).

## Project Structure

```
.
├── data/                     # Default output directory for generated data
├── prompts/
│   ├── scenario_prompt.txt   # Prompt for generating high-level scenarios
│   ├── governance_prompt.txt # Prompt for generating detailed traces and logs
│   └── evaluation.txt        # Prompt for quantitative evaluation
├── src/
│   ├── generate_scenario.py    # Script for generating scenario files
│   ├── generate_governance.py  # Script for generating governance logs
│   └── evaluate_governance.py  # Script for evaluating generated data
└── README.md                 # This file
```

## Customization

The framework is designed to be highly customizable by modifying the prompt files in the `prompts/` directory:

-   **`scenario_prompt.txt`**: Change the structure and content of the generated scenarios.
-   **`governance_prompt.txt`**: Change how the agent trace and multi-system logs are generated. This is where you define the behavior of the governance components.
-   **`evaluation.txt`**: Change the evaluation criteria and the metrics to be extracted by the LLM judge.
