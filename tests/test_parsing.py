from reclamo.parsing import (
    FinalCandidate,
    find_code_blocks,
    find_final,
    looks_like_plan,
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


# --- looks_like_plan ---------------------------------------------------------


def test_looks_like_plan_cases() -> None:
    assert looks_like_plan("I'll start by reading the first chunk")
    assert looks_like_plan("Let me check the headers first")
    assert looks_like_plan("First, split the text")
    assert looks_like_plan("Here is the approach: step 1 chunk, step 2 map")
    assert not looks_like_plan("42")
    assert not looks_like_plan("The answer is Paris.")
    assert not looks_like_plan("")
