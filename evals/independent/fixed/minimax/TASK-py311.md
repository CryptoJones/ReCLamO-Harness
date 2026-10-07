# Task: make Cerebex_selffix.py run on Python 3.11

`Cerebex_selffix.py` is an eval-task generator. On Python 3.11 it fails to import with
`SyntaxError: f-string expression part cannot include a backslash` (line ~158: a `’`
escape inside an f-string `{...}` expression; 3.12 allows this, 3.11 does not).

Write `Cerebex.py` = `Cerebex_selffix.py` with the SMALLEST change that makes it valid Python 3.11
syntax while producing BYTE-IDENTICAL output (same context/question/answer for every seed and size).
Typical fix: hoist the string containing the escape into a variable outside the f-string.
Do not change anything else. Verify:
1. `python3 -c "import ast;ast.parse(open('Cerebex.py').read(), feature_version=(3,11))"` succeeds.
2. For seeds 0,1,2 and sizes small/medium/large, generate() output of Cerebex.py == Cerebex_selffix.py
   (write a tiny comparison script and run it).
3. `python3 check.py Cerebex.py` passes.
Then stop. Do not edit Cerebex_selffix.py or check.py.
