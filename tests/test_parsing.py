import pytest

from reclamo.parsing import (
    FinalCandidate,
    find_code_blocks,
    find_final,
    looks_like_plan,
    strip_code,
    strip_think,
)

# --- code blocks -----------------------------------------------------------


def test_repl_and_python_fences_both_found() -> None:
    text = "```repl\nprint(1)\n```\nthen\n```python\nprint(2)\n```\n"
    assert find_code_blocks(text) == ["print(1)", "print(2)"]


def test_strict_mode_keeps_only_repl() -> None:
    text = "```python\nx = 1\n```\n```repl\ny = 2\n```\n"
    assert find_code_blocks(text, strict=True) == ["y = 2"]


def test_other_languages_ignored() -> None:
    text = "```bash\nls\n```\n```\nplain\n```\n```repl\nz = 3\n```\n"
    assert find_code_blocks(text) == ["z = 3"]


def test_code_inside_think_ignored() -> None:
    text = "<think>\n```repl\nprint('fake')\n```\n</think>\n```repl\nprint('real')\n```\n"
    assert find_code_blocks(text) == ["print('real')"]


def test_unclosed_think_swallows_rest() -> None:
    text = "```repl\nbefore = 1\n```\n<think>\n```repl\nafter = 2\n```\n"
    assert find_code_blocks(text) == ["before = 1"]
    assert strip_think(text).strip() == "```repl\nbefore = 1\n```"


def test_multiline_body_and_indented_fence() -> None:
    text = "  ```repl\nfor i in range(2):\n    print(i)\n  ```\n"
    assert find_code_blocks(text) == ["for i in range(2):\n    print(i)"]


def test_crlf_fences() -> None:
    text = "```repl\r\nx = 1\r\n```\r\n"
    assert find_code_blocks(text) == ["x = 1"]


# --- FINAL / FINAL_VAR -----------------------------------------------------


def test_no_final() -> None:
    assert find_final("Let me look at the data.\n```repl\nprint(len(context))\n```") is None


def test_final_simple() -> None:
    cand = find_final("FINAL(The needle is on line 4321.)")
    assert cand == FinalCandidate("FINAL", "The needle is on line 4321.", False, False)


def test_final_var() -> None:
    cand = find_final("Done.\nFINAL_VAR(result)")
    assert cand is not None
    assert cand.kind == "FINAL_VAR"
    assert cand.value == "result"
    assert cand.has_code is False


def test_final_nested_parens() -> None:
    cand = find_final("FINAL(f(x) = (a + b) * (c - d))")
    assert cand is not None
    assert cand.value == "f(x) = (a + b) * (c - d)"


def test_final_parens_inside_quotes() -> None:
    cand = find_final('FINAL("mismatched ) inside quotes")')
    assert cand is not None
    assert cand.value == '"mismatched ) inside quotes"'


def test_final_with_apostrophe() -> None:
    cand = find_final("FINAL(It's 42, and the user's id is (7).)")
    assert cand is not None
    assert cand.value == "It's 42, and the user's id is (7)."


def test_final_multiline_value() -> None:
    cand = find_final("FINAL(\n  line one\n  line two\n)")
    assert cand is not None
    assert cand.value == "line one\n  line two"


def test_fake_final_inside_think_ignored() -> None:
    text = "<think>I could write FINAL(42) now but should verify.</think>\nStill checking."
    assert find_final(text) is None


def test_final_inside_code_block_ignored() -> None:
    text = "```repl\nprint('FINAL(not yet)')\n```\n"
    assert find_final(text) is None


def test_final_alongside_code_sets_has_code() -> None:
    text = "```repl\nx = compute()\n```\nFINAL(x is ready)"
    cand = find_final(text)
    assert cand is not None
    assert cand.has_code is True


def test_last_occurrence_wins() -> None:
    text = "FINAL(first guess)\nActually, correcting myself:\nFINAL(second answer)"
    cand = find_final(text)
    assert cand is not None
    assert cand.value == "second answer"


def test_last_occurrence_wins_across_kinds() -> None:
    text = "FINAL(draft)\n...\nFINAL_VAR(final_text)"
    cand = find_final(text)
    assert cand is not None
    assert cand.kind == "FINAL_VAR"
    assert cand.value == "final_text"


def test_unbalanced_final_skipped() -> None:
    assert find_final("FINAL(never closed") is None


def test_unbalanced_then_balanced() -> None:
    cand = find_final("FINAL(oops\nFINAL(ok)")
    assert cand is not None
    assert cand.value == "ok"


def test_plan_like_final_flagged() -> None:
    cand = find_final("FINAL(I will split the context into chunks and query each one.)")
    assert cand is not None
    assert cand.looks_like_plan is True


def test_step_list_final_flagged() -> None:
    cand = find_final("FINAL(Step 1: load data. Step 2: search for the needle.)")
    assert cand is not None
    assert cand.looks_like_plan is True


def test_answer_final_not_flagged() -> None:
    cand = find_final("FINAL(There are 17 distinct customers.)")
    assert cand is not None
    assert cand.looks_like_plan is False


def test_final_var_never_flagged_as_plan() -> None:
    cand = find_final("FINAL_VAR(plan)")
    assert cand is not None
    assert cand.looks_like_plan is False


def test_final_word_in_prose_without_parens_ignored() -> None:
    assert find_final("The final step is to count. FINAL answer pending.") is None


def test_mid_sentence_mention_is_not_a_candidate() -> None:
    text = "Once I have the count I'll call FINAL(answer) to finish.\nLet me count first."
    assert find_final(text) is None


def test_mid_sentence_mention_does_not_shadow_real_final() -> None:
    text = "Earlier I said I'd call FINAL(answer).\nFINAL(There are 17 customers.)"
    cand = find_final(text)
    assert cand is not None and cand.value == "There are 17 customers."


@pytest.mark.parametrize(
    ("text", "kind", "value"),
    [
        ("**FINAL(42)**", "FINAL", "42"),
        ("`FINAL_VAR(result)`", "FINAL_VAR", "result"),
        ("> FINAL(quoted)", "FINAL", "quoted"),
        ("- FINAL_VAR(item)", "FINAL_VAR", "item"),
        ("   FINAL(indented)", "FINAL", "indented"),
        ("### FINAL(heading)", "FINAL", "heading"),
        ("**`FINAL_VAR(both)`**", "FINAL_VAR", "both"),
    ],
)
def test_markdown_wrapped_final_accepted(text: str, kind: str, value: str) -> None:
    cand = find_final(text)
    assert cand is not None
    assert (cand.kind, cand.value) == (kind, value)


def test_final_after_code_fence_is_at_line_start() -> None:
    text = "Explanation.\n```repl\nx = 1\n```\nFINAL_VAR(x)"
    cand = find_final(text)
    assert cand is not None and cand.kind == "FINAL_VAR" and cand.has_code


# --- looks_like_plan ---------------------------------------------------------


def test_looks_like_plan_cases() -> None:
    assert looks_like_plan("I'll start by reading the first chunk")
    assert looks_like_plan("Let me check the headers first")
    assert looks_like_plan("First, split the text")
    assert looks_like_plan("Here is the approach: step 1 chunk, step 2 map")
    assert not looks_like_plan("42")
    assert not looks_like_plan("The answer is Paris.")
    assert not looks_like_plan("")


# --- Laguna text-form tool calls (#48) ----------------------------------------
# Samples 1-5 are verbatim message contents from the ronin28 round-3 run at a30aea5
# (sample 5 is the tail of its message). Sample 6 is a short synthetic version of an
# ~11K-char reply that invented REPL output between a dozen blocks.

INSPECT = (
    'print("type:", type(context))\nprint("len:", len(context))\nprint("first 600 chars:")\n'
    'print(context[:600])\nprint("----")\nprint("last 400 chars:")\nprint(context[-400:])'
)
SHORT = "print(type(context))\nprint(len(context))\nprint(repr(context[:500]))"
LAGUNA_1 = f"<tool_call>repl\n{INSPECT}\n</arg_value></tool_call>"
LAGUNA_2 = f"<tool_call>repl\n{INSPECT}\n</repl>"
DESCRIPTION = (
    "<arg_key>description</arg_key><arg_value>Inspect context type, length, and first 500 "
    "chars</arg_value></tool_call>"
)
LAGUNA_3 = f"<tool_call>repl\n{SHORT}\n</arg_value>{DESCRIPTION}"
LAGUNA_4 = (
    "I see I need to provide the code in a proper REPL block. Let me inspect the context "
    f"first.<tool_call>repl\n{SHORT}\n</value>{DESCRIPTION}"
)
LAGUNA_5 = (
    "...Let me calculate the total:\n\n```repl\ntotal = 3782 + 1819 + 3293 + 117 + 1974 + 350 "
    '+ 4535 + 1874 + 4422 + 4629 + 1892 + 3509\nprint(f"Total: ${total}")\n```\n\nThe output '
    "should give me the total dollar amount.\n\nFINAL: Priya Patel's expense report was the "
    'only one flagged ... $32,196.00 for her flagged expenses.<tool_call>FINAL("Priya '
    "Patel's expense report was the only one flagged for both 'double-dipped invoices' and "
    "'non-compliant vendor' in the final audit summary, with a total dollar amount of "
    '$32,196.00 for her flagged expenses.")'
)
LAGUNA_6 = (
    f"<tool_call>repl\n{SHORT}\n</think>```repl\n<class 'str'>\n64468\n'Project Requirements "
    "Document\\nVersion: 2.1'\n```\nThe requirements use ids like R12. Let me retry that last "
    "command.</think><tool_call>repl\nimport re\nids = re.findall(r'R\\d{2,3}', context)\n"
    "</think>```repl\n['R12', 'R130']\n```\nFINAL(R12 and R130)\n"
    "<tool_call>repl\nprint(ids)\n</tool_call>"
)


@pytest.mark.parametrize(
    ("text", "code"),
    [(LAGUNA_1, INSPECT), (LAGUNA_2, INSPECT), (LAGUNA_3, SHORT), (LAGUNA_4, SHORT)],
    ids=["arg_value+tool_call", "repl-close", "description-arg", "value-close+prose"],
)
def test_laguna_tool_call_samples(text: str, code: str) -> None:
    assert find_code_blocks(text) == [code]
    assert find_final(text) is None
    compile(code, "<laguna>", "exec")


def test_laguna_prose_before_tool_call_survives_strip_code() -> None:
    assert strip_code(LAGUNA_4) == (
        "I see I need to provide the code in a proper REPL block. Let me inspect the context first."
    )
    assert strip_code(LAGUNA_3) == ""


def test_tool_call_final_next_to_unrun_fence_is_rejected() -> None:
    blocks = find_code_blocks(LAGUNA_5)
    assert len(blocks) == 1 and blocks[0].startswith("total = 3782")
    cand = find_final(LAGUNA_5)
    assert cand is not None and cand.kind == "FINAL" and cand.has_code is True
    assert cand.value.startswith("\"Priya Patel's expense report")


def test_tool_call_final_alone_is_a_final() -> None:
    assert find_final('<tool_call>FINAL("42")</tool_call>') == FinalCandidate(
        "FINAL", '"42"', False, False
    )
    cand = find_final("Done.<tool_call>FINAL_VAR(result)")
    assert cand is not None and (cand.kind, cand.value) == ("FINAL_VAR", "result")


def test_leading_tool_call_discards_invented_output_and_later_blocks() -> None:
    # Only the first block runs: the ```repl fences after it hold fabricated output,
    # and the later calls and the FINAL are built on that fiction.
    assert find_code_blocks(LAGUNA_6) == [SHORT]
    assert find_final(LAGUNA_6) is None
    assert strip_code(LAGUNA_6) == ""


def test_stray_think_close_does_not_swallow_content() -> None:
    assert strip_think(LAGUNA_6) == LAGUNA_6
    assert strip_think("answer</think>tail") == "answer</think>tail"
    assert strip_code("The answer is 4.</think>") == "The answer is 4."


def test_glm_style_arg_wrapper_before_code_is_stripped() -> None:
    text = (
        "<tool_call>repl\n<arg_key>code</arg_key><arg_value>x = 1\nprint(x)</arg_value></tool_call>"
    )
    assert find_code_blocks(text) == ["x = 1\nprint(x)"]


def test_python_and_execute_python_names_accepted_other_names_ignored() -> None:
    assert find_code_blocks("<tool_call>python\nx = 1\n</tool_call>") == ["x = 1"]
    assert find_code_blocks("<tool_call>execute_python\nx = 2\n</tool_call>") == ["x = 2"]
    assert find_code_blocks("<tool_call>bash\nls\n</tool_call>") == []
    assert strip_code("Hi.<tool_call>bash\nls\n</tool_call>") == "Hi."


def test_fence_first_keeps_document_order_with_tool_calls() -> None:
    text = (
        "```repl\na = 1\n```\nthen<tool_call>repl\nb = 2\n</tool_call>\n"
        "```python\nc = 3\n```\n<tool_call>repl\nd = 4\n</arg_value></tool_call>"
    )
    assert find_code_blocks(text) == ["a = 1", "b = 2", "c = 3", "d = 4"]


def test_multiple_closed_tool_calls_only_the_first_runs() -> None:
    text = "<tool_call>repl\nx = 1\n</tool_call>\n<tool_call>repl\ny = 2\n</tool_call>"
    assert find_code_blocks(text) == ["x = 1"]
    # With no closers, the next <tool_call> still ends the first block.
    assert find_code_blocks("<tool_call>repl\nx = 1\n<tool_call>repl\ny = 2\n") == ["x = 1"]


def test_tool_call_inside_think_ignored() -> None:
    text = "<think>\n<tool_call>repl\nprint('fake')\n</tool_call>\n</think>\n```repl\nok = 1\n```"
    assert find_code_blocks(text) == ["ok = 1"]
    assert find_code_blocks("<think><tool_call>repl\nprint('fake')\n</tool_call></think>") == []


def test_final_inside_tool_call_not_detected() -> None:
    text = "<tool_call>repl\nx = 1\nFINAL(x)\n</tool_call>"
    assert find_code_blocks(text) == ["x = 1\nFINAL(x)"]
    assert find_final(text) is None
    assert strip_code(text) == ""


def test_final_next_to_tool_call_code_sets_has_code() -> None:
    text = "FINAL(41)\n<tool_call>repl\nprint(42)\n</tool_call>"
    cand = find_final(text)
    assert cand is not None and cand.value == "41" and cand.has_code is True


def test_unclosed_tool_call_runs_to_end_of_text() -> None:
    # Many Laguna blocks have no closing tag at all, so end of text is a terminator.
    text = "Inspecting.<tool_call>repl\nprint(len(context))\nFINAL(3)"
    assert find_code_blocks(text) == ["print(len(context))\nFINAL(3)"]
    assert find_final(text) is None
    assert strip_code(text) == "Inspecting."


def test_strict_mode_excludes_tool_calls() -> None:
    text = "<tool_call>repl\nx = 1\n</tool_call>\n```python\ny = 2\n```\n```repl\nz = 3\n```\n"
    assert find_code_blocks(text, strict=True) == ["z = 3"]
