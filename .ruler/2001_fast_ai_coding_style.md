---
alwaysApply: true
---
# Description: fastai Python coding style

## Naming
- Use `CamelCase` for classes and `snake_case` for variables and functions.
- Apply Huffman coding: short names for common concepts.
  - Example: `sz` for "size"
- Use `o` for objects in comprehensions, `i` for indices, `x` for tensor-like variables.
- Name functions/methods with a verb+object (e.g. `load_segments`, `save_preds`) and avoid vague adjectives like `safe` or `enhanced`.
- Match paper and domain terminology where appropriate.

## Layout

- Write one-liners with `:` or ternary expressions. Example: `if x: y()` or `z = a if cond else b`
- Define short functions in one line. Example: `def f(): return x`
- Align similar logic to emphasize structure.
  - Example:
    ```python
    if cond: x = f(a, b)  # comment to explain why the logic is necessary or for what objective it is used
    else:    x = f(b, a)  # comment can be added after the statement if it is not too long
    ```
- Use tuple unpacking for member assignment.
  - Example: `self.x, self.y = x, y`
- Import multiple modules per line.
  - Example: `import os, sys`
- Use spacing to mirror math or domain conventions.
  - Example: `x = a*b + c`
- Do not leave trailing whitespace.

## Imports

- Keep general module imports on a single line as shown above.
- When working with constants modules (e.g. `guess_class_libs.entities.common_keys`), prefer `from ...common_keys import *` so lookups like `cfg[DB_STR]` stay concise.

## Code style

- Avoid verbose comments, place short comments at the end of line, or after parameter in fn def
- Example:
     ```python
    def print_var(var1: str # extra not obvious information about the variable that is not obvious from the variable name
        ) -> None: 
    """ Additional info about the function logic, parameters, return value, etc. that is not obvious from the function name or parameters. """
    print(var1)
    ```
    
- Use backticks for parameter names in docstrings.
- Reference equation numbers when implementing from papers.
- Use type hints for all functions.
- Keep inline `#` comments concise: place them at the end of a statement or immediately after a parameter to capture the intent without adding extra lines.
- Reserve `try/except` blocks for unstable external interactions (network, subprocess, filesystem). Let internal errors propagate so tests can surface real failures.

- **Minimal Comments**: No unnecessary comments; fit everything in one line when possible
- **One-Line Functions**: Keep simple functions on single lines
- **Modern Typing**: Use `dict[str, any]` instead of `Dict[str, Any]`
- **Generic Typing**: Prefer built-in generic types where possible


## Other principles

### DRY Principle Implementation
- **Function Extraction**: Always validate if code can be extracted to reusable functions
- **Parameterization**: Avoid hard-coding; use parameters for flexibility
- **Code Reuse Analysis**: Before implementing, check if similar functionality exists

### No Magic Strings => centralized const definitions
- **Constants File**: Import keys from `guess_class_libs.entities.common_keys` (or add a `{module}_common_keys.py` alongside the code you are authoring) so `config[BATCH_SIZE]` replaces `config['batch_size']`. Define new constants there before using them.


### Performance
- **Concurrent Processing**: Use `fastcore.parallel.parallel()` for concurrent operations

### In case of inconsistency or bug
Always try to find the root cause and communicate about fixing it. It is not a good solution to just patch the code to make a given part of the code work.


### Test functions in .py files
When you write test cases use test_{module_name}.py and unittest.TestCase for normal python modules. This rule does not apply to notebook implemented functions.
