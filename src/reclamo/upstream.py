"""``planner_style = "upstream-rlm-v0"``: speak the format RLM-Qwen3-8B was trained on.

``mit-oasys/rlm-qwen3-8b-v0.1`` (uploaded 2026-01-15) is Qwen3-8B fine-tuned on
root-model turns from RLM(Qwen3-Coder-480B-A35B) trajectories. Its model card says
it "was trained on trajectories produced using a fixed system prompt" and "assumes
the environment/scaffold from our RLM repo". This module reproduces that scaffold
so the checkpoint can be the root planner here without retraining, while the loop
in ``rlm.py`` keeps our sandbox, sub-call caps, forced finish, nudges and logging.

Sources (see the README section "Using the paper's RLM-Qwen3-8B as planner"):

* Scaffold: alexzhang13/rlm at tag ``v1.0.0`` (commit
  ``18a936836103b62ed35770ed7001c22f114aea9a``, 2026-01-12, the last tag before
  the upload). ``rlm/utils/prompts.py`` (``build_rlm_system_prompt``,
  ``USER_PROMPT_WITH_ROOT``, ``build_user_prompt``), ``rlm/core/rlm.py`` (message
  order: system, then an *assistant* message with the context metadata, then per
  turn the assistant reply and one user message per executed code block, plus a
  fresh user prompt that is sent every turn but never stored) and
  ``rlm/utils/parsing.py`` (``format_iteration``, ``format_execution_result``;
  results cut at 20,000 characters).
* System prompt: arXiv 2512.24601 v2 (2026-01-28), App. C.1 (1c), the diff that
  turns the GPT-5 prompt (1a) into the prompt "for the fine-tuned Qwen3-8B
  experiment" (32K window), applied here to the text of (1a). (1a) is the repo's
  ``RLM_SYSTEM_PROMPT`` without ``llm_query_batched``.

The prompt strings below are copied verbatim (Python escapes included, so the
runtime text matches upstream where the text is shared) from:

    alexzhang13/rlm, MIT License
    Copyright (c) 2025 Alex Zhang

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

Upstream never calls ``.format()`` on the system prompt, so the model sees the
doubled braces (``{{chunk}}``) literally; they are kept. Where this module differs
from upstream on purpose (variable list, error line), the function says so.
"""

from __future__ import annotations

import json
from typing import Any

from reclamo.repl.base import ExecResult

STYLE = "upstream-rlm-v0"
# rlm/utils/parsing.py format_iteration(max_character_length=20000)
UPSTREAM_OUTPUT_CHARS = 20_000
_MAX_CHUNKS_LISTED = 100  # rlm/utils/prompts.py build_rlm_system_prompt

# --- verbatim (MIT, Copyright (c) 2025 Alex Zhang; see module docstring) --------
# arXiv 2512.24601 v2 App. C.1 (1a) with the (1c) Qwen3-8B diff applied.
UPSTREAM_SYSTEM_PROMPT = """You are tasked with answering a query with associated context. You can access, transform, and analyze this context interactively in a REPL environment that can recursively query sub-LLMs, which you are strongly encouraged to use as much as possible. You will be queried iteratively until you provide a final answer.

IMPORTANT: You have a total context window of approximately ~32k tokens. Be very careful about context length limits. The sub-LLMs you can query also have this same ~32k token limit, so you must be conservative with how much context you send in each call.

The REPL environment is initialized with:
1. A `context` variable that contains extremely important information about your query. You should check the content of the `context` variable to understand what you are working with. Make sure you look through it sufficiently as you answer your query.
2. A `llm_query` function that allows you to query an LLM (that can handle around ~100k chars, roughly 32k tokens) inside your REPL environment.
3. The ability to use `print()` statements to view the output of your REPL code and continue your reasoning.

You will only be able to see truncated outputs from the REPL environment, so you should use the query LLM function on variables you want to analyze. You will find this function especially useful when you have to analyze the semantics of the context. Use these variables as buffers to build up your final answer.
Make sure to explicitly look through the entire context in REPL before answering your query. An example strategy is to first look at the context and figure out a chunking strategy, then break up the context into smart chunks, and query an LLM per chunk with a particular question and save the answers to a buffer, then query an LLM with all the buffers to produce your final answer.

You can use the REPL environment to help you understand your context, especially if it is huge. Remember that your sub LLMs have a ~32k token limit (approximately ~24k characters) -- be careful not to exceed this. For example, a viable strategy is to feed 2-3 documents per sub-LLM query. Analyze your input data and see if it is sufficient to just fit it in a few sub-LLM calls!

IMPORTANT: Be very careful about using `llm_query` as it incurs high runtime costs. Always batch as much information as reasonably possible into each call while staying within the ~32k token limit (aim for around ~10k-15k characters per call to be safe). For example, if you have 1000 lines of information to process, it's much better to split into chunks of 50-100 and call `llm_query` on each chunk (10-20 calls total) rather than making 1000 individual calls. Minimize the number of `llm_query` calls by batching related information together, but always respect the ~32k token limit.

When you want to execute Python code in the REPL environment, wrap it in triple backticks with 'repl' language identifier. For example, say we want our recursive model to search for the magic number in the context (assuming the context is a string), and the context is very long, so we want to chunk it:
```repl
chunk = context[:1000]
answer = llm_query(f"What is the magic number in the context? Here is the chunk: {{chunk}}")
print(answer)
```

As an example, suppose you're trying to answer a question about a book. You can iteratively chunk the context section by section, query an LLM on that chunk, and track relevant information in a buffer.
```repl
query = "In Harry Potter and the Sorcerer's Stone, did Gryffindor win the House Cup because they led?"
for i, section in enumerate(context):
    if i == len(context) - 1:
        buffer = llm_query(f"You are on the last section of the book. So far you know that: {{buffers}}. Gather from this last section to answer {{query}}. Here is the section: {{section}}")
        print(f"Based on reading iteratively through the book, the answer is: {{buffer}}")
    else:
        buffer = llm_query(f"You are iteratively looking through a book, and are on section {{i}} of {{len(context)}}. Gather information to help answer {{query}}. Here is the section: {{section}}")
        print(f"After section {{i}} of {{len(context)}}, you have tracked: {{buffer}}")
```

As another example, when the context isn't that long (e.g. >100M characters), a simple but viable strategy is, based on the context chunk lengths, to combine them and recursively query an LLM over chunks. For example, if the context is a List[str], we ask the same query over each chunk:
```repl
query = "A man became famous for his book "The Great Gatsby". How many jobs did he have?"
# Suppose our context is ~1M chars, and we want each sub-LLM query to be ~0.1M chars so we split it into 5 chunks
chunk_size = len(context) // 10
answers = []
for i in range(10):
    if i < 9:
        chunk_str = "\n".join(context[i*chunk_size:(i+1)*chunk_size])
    else:
        chunk_str = "\n".join(context[i*chunk_size:])

    answer = llm_query(f"Try to answer the following query: {{query}}. Here are the documents:\n{{chunk_str}}. Only answer if you are confident in your answer based on the evidence.")
    answers.append(answer)
    print(f"I got the answer from chunk {{i}}: {{answer}}")
final_answer = llm_query(f"Aggregating all the answers per chunk, answer the original query about total number of jobs: {{query}}\\n\\nAnswers:\\n" + "\\n".join(answers))
```

As a final example, after analyzing the context and realizing its separated by Markdown headers, we can maintain state through buffers by chunking the context by headers, and iteratively querying an LLM over it:
```repl
# After finding out the context is separated by Markdown headers, we can chunk, summarize, and answer
import re
sections = re.split(r'### (.+)', context["content"])
buffers = []
for i in range(1, len(sections), 2):
    header = sections[i]
    info = sections[i+1]
    summary = llm_query(f"Summarize this {{header}} section: {{info}}")
    buffers.append(f"{{header}}: {{summary}}")
final_answer = llm_query(f"Based on these summaries, answer the original query: {{query}}\\n\\nSummaries:\\n" + "\\n".join(buffers))
```
In the next step, we can return FINAL_VAR(final_answer).
FINAL_VAR(final_answer)

IMPORTANT: When you are done with the iterative process, you MUST provide a final answer inside a FINAL function when you have completed your task, NOT in code or repl tags. Do not use these tags unless you have completed your task. You have two options:
1. Use FINAL(your final answer here) to provide the answer directly
2. Use FINAL_VAR(variable_name) to return a variable you have created in the REPL environment as your final output

Think step by step carefully, plan, and execute this plan immediately in your response -- do not just say "I will do this" or "I will do that". Output to the REPL environment and recursive LLMs as much as possible. Remember to explicitly answer the original query in your final answer.
"""  # noqa: E501

# rlm/utils/prompts.py at v1.0.0, verbatim.
USER_PROMPT_WITH_ROOT = """Think step-by-step on what to do using the REPL environment (which contains the context) to answer the original prompt: \"{root_prompt}\".\n\nContinue using the REPL environment, which has the `context` variable, and querying sub-LLMs by writing to ```repl``` tags, and determine your answer. Your next action:"""  # noqa: E501
FIRST_TURN_SAFEGUARD = "You have not interacted with the REPL environment or seen your prompt / context yet. Your next action should be to look through and figure out how to answer the prompt, so don't just provide a final answer yet.\n\n"  # noqa: E501
LATER_TURN_PREFIX = "The history before is your previous interactions with the REPL environment. "
# --- end verbatim ---------------------------------------------------------------


def _chunk_lengths(context: Any) -> tuple[str, list[int]]:
    """``QueryMetadata`` (rlm/core/types.py at v1.0.0): type name and per-chunk lengths."""

    def dumped(chunk: Any) -> int:
        try:
            return len(json.dumps(chunk, default=str))
        except Exception:  # mirror upstream's repr fallback
            return len(repr(chunk))

    if isinstance(context, str):
        return "str", [len(context)]
    if isinstance(context, dict):
        return "dict", [len(v) if isinstance(v, str) else dumped(v) for v in context.values()]
    if isinstance(context, list):
        if not context:
            return "list", [0]
        if isinstance(context[0], dict):
            if "content" in context[0]:
                return "list", [len(str(c.get("content", ""))) for c in context]
            return "list", [dumped(c) for c in context]
        return "list", [len(c) if isinstance(c, str) else dumped(c) for c in context]
    raise TypeError(f"context must be str, list or dict, not {type(context).__name__}")


def metadata_prompt(context: Any) -> str:
    """The assistant message upstream puts right after the system prompt."""
    kind, lengths = _chunk_lengths(context)
    total = sum(lengths)
    shown: Any = lengths
    if len(lengths) > _MAX_CHUNKS_LISTED:
        others = len(lengths) - _MAX_CHUNKS_LISTED
        shown = str(lengths[:_MAX_CHUNKS_LISTED]) + "... [" + str(others) + " others]"
    return (
        f"Your context is a {kind} with {total} total characters, and is broken up into "
        f"chunks of char lengths: {shown}."
    )


def initial_messages(context: Any) -> list[dict[str, str]]:
    """``build_rlm_system_prompt``: system prompt, then the metadata as an assistant turn."""
    return [
        {"role": "system", "content": UPSTREAM_SYSTEM_PROMPT},
        {"role": "assistant", "content": metadata_prompt(context)},
    ]


def user_prompt(query: str, iteration: int) -> str:
    """``build_user_prompt(root_prompt=query, iteration)``; ``iteration`` is 0-based.

    Upstream sends this after the stored history on every turn and never stores it;
    the loop does the same.
    """
    body = USER_PROMPT_WITH_ROOT.format(root_prompt=query)
    return (FIRST_TURN_SAFEGUARD if iteration == 0 else LATER_TURN_PREFIX) + body


def format_execution_result(res: ExecResult) -> str:
    """``format_execution_result``: stdout, stderr, then the variable names.

    Adapted: upstream appends ``"\\n<Type>: <message>"`` to stderr when the code
    raises; ours appends ``res.error``, the same line plus the line number.
    Upstream lists ``context_0`` and ``context`` and then the simple-typed user
    variables; our REPL has no ``context_0``, so the list is ``context`` followed by
    the user variables the worker reports.
    """
    parts: list[str] = []
    if res.stdout:
        parts.append(f"\n{res.stdout}")
    stderr = res.stderr
    if res.error:
        stderr = f"{stderr}\n{res.error}"
    if stderr:
        parts.append(f"\n{stderr}")
    names = ["context", *[v for v in res.vars if v != "context"]]
    parts.append(f"REPL variables: {names}\n")
    return "\n\n".join(parts)


def code_output_message(code: str, res: ExecResult, limit: int = UPSTREAM_OUTPUT_CHARS) -> str:
    """``format_iteration``: the user message for one executed block, cut at ``limit``."""
    result = format_execution_result(res)
    if len(result) > limit:
        result = result[:limit] + f"... + [{len(result) - limit} chars...]"
    return f"Code executed:\n```python\n{code.strip()}\n```\n\nREPL output:\n{result}"


__all__ = [
    "STYLE",
    "UPSTREAM_OUTPUT_CHARS",
    "UPSTREAM_SYSTEM_PROMPT",
    "code_output_message",
    "format_execution_result",
    "initial_messages",
    "metadata_prompt",
    "user_prompt",
]
