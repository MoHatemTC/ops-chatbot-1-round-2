"""Grounding and faithfulness evaluation suite.

This module defines LLM-as-judge evaluation prompts that measure two
core properties of the retrieval-grounded answering pipeline:

* **Grounding** — Is the answer actually based on retrieved KB evidence,
  or did the model use outside knowledge?
* **Faithfulness** — Is the answer *accurate* with respect to the
  retrieved evidence, or did the model distort, exaggerate, or
  hallucinate details?

The prompts are compatible with the existing ``evals/`` harness: each
metric is a dict with ``name`` and ``prompt`` keys.  They are
automatically discovered by ``evals/metrics/__init__.py`` when the
corresponding ``.md`` files are present, but this module also exposes
them programmatically so they can be imported by tests or CI scripts.
"""

from __future__ import annotations

import os
from pathlib import Path

GROUNDING_PROMPT = """\
You are an evaluation judge. Your task is to assess whether an AI \
assistant's answer is **grounded** in the retrieved knowledge-base \
evidence that was provided to it.

A grounded answer:
- Uses only facts present in the retrieved sources.
- Does not introduce claims, statistics, dates, or names that are \
  absent from the sources.
- Cites sources where appropriate.
- Refuses to answer when the sources do not contain relevant \
  information.

An ungrounded answer:
- Contains facts, advice, or claims not found in any retrieved source.
- Makes up plausible-sounding information.
- Answers confidently when no relevant source was retrieved.

Score the answer on a scale from 0 to 1:
- 1.0 = Fully grounded. Every claim traces to a retrieved source.
- 0.7 = Mostly grounded with minor unsupported elaboration.
- 0.4 = Partially grounded; some claims are unsupported.
- 0.0 = Not grounded at all; the answer ignores or contradicts sources.

Respond with a JSON object containing:
- "score": a float between 0 and 1
- "reasoning": a one-sentence explanation
"""

FAITHFULNESS_PROMPT = """\
You are an evaluation judge. Your task is to assess whether an AI \
assistant's answer is **faithful** to the retrieved knowledge-base \
evidence — that is, whether it accurately represents what the sources \
actually say.

A faithful answer:
- Accurately paraphrases or quotes retrieved source content.
- Does not distort, exaggerate, or selectively omit material facts.
- Preserves the meaning and intent of the original source.
- When the source is ambiguous, acknowledges the ambiguity.

An unfaithful answer:
- Misrepresents what a source says.
- Draws unsupported conclusions from the evidence.
- Cherry-picks facts to create a misleading impression.
- Attributes claims to sources that do not contain them.

Score the answer on a scale from 0 to 1:
- 1.0 = Fully faithful. The answer accurately represents every cited \
  source.
- 0.7 = Mostly faithful with minor inaccuracies or slight \
  exaggeration.
- 0.4 = Partially faithful; some claims distort or misrepresent the \
  sources.
- 0.0 = Not faithful; the answer contradicts or fabricates source \
  content.

Respond with a JSON object containing:
- "score": a float between 0 and 1
- "reasoning": a one-sentence explanation
"""

# ---------------------------------------------------------------------------
# Metric dicts compatible with the evals harness
# ---------------------------------------------------------------------------

grounding_metric: dict[str, str] = {
    "name": "grounding",
    "prompt": GROUNDING_PROMPT,
}

faithfulness_metric: dict[str, str] = {
    "name": "faithfulness",
    "prompt": FAITHFULNESS_PROMPT,
}

grounding_suite_metrics: list[dict[str, str]] = [
    grounding_metric,
    faithfulness_metric,
]


# ---------------------------------------------------------------------------
# Optional: write the prompts as .md files for the harness auto-loader
# ---------------------------------------------------------------------------


def install_prompt_files(prompts_dir: str | Path | None = None) -> list[Path]:
    """Write grounding and faithfulness prompts as .md files.

    The default ``evals/metrics/prompts/`` directory is used when no
    path is given.  Existing files are overwritten so the prompts stay
    in sync with this module.

    Returns:
        Paths of the written files.
    """
    if prompts_dir is None:
        prompts_dir = Path(
            os.path.join(os.path.dirname(__file__), "metrics", "prompts")
        )
    else:
        prompts_dir = Path(prompts_dir)

    prompts_dir.mkdir(parents=True, exist_ok=True)

    written: list[Path] = []
    for metric in grounding_suite_metrics:
        path = prompts_dir / f"{metric['name']}.md"
        path.write_text(metric["prompt"], encoding="utf-8")
        written.append(path)

    return written