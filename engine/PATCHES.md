# Patches Layered on Top of Upstream

In this plan (foundation, v0.1.0-rc1) the engine is **unmodified** from the
pinned upstream commit recorded in `UPSTREAM.md`. The only deltas vs upstream
are:

- Upstream's `.github/` workflows have been removed (we run our own in the
  monorepo root's `.github/workflows/`).
- Upstream's `.git/` directory is absent (flat copy, see `UPSTREAM.md`).

Plan 2 (bio-languages) will add per-language patches for R, Julia, MATLAB,
Perl — each documented as a numbered entry below when it lands.

## Language additions

### R (added 2026-05-30)
- WASM grammar: `engine/src/extraction/wasm/tree-sitter-r.wasm` from r-lib/tree-sitter-r v1.2.0
- Extension map: `.R`, `.r` → `r`
- Extractor: `engine/src/extraction/languages/r.ts`
- Tests: added `R Extraction` describe block in `engine/__tests__/extraction.test.ts`
- Notes: R functions are anonymous expressions assigned to identifiers via
  `binary_operator` (`<-`, `=`, `->>`). The extractor uses a `visitNode` hook
  to intercept `binary_operator` nodes: rhs=`function_definition` → function
  node; plain rhs → variable node. No class support (S3/S4/R5/R6 are runtime
  constructs). `library()`/`require()` are extracted as plain function calls.

### Julia (added 2026-05-30)
- WASM grammar: `engine/src/extraction/wasm/tree-sitter-julia.wasm` from tree-sitter/tree-sitter-julia v0.25.0
- Extension map: `.jl` → `julia`
- Extractor: `engine/src/extraction/languages/julia.ts`
- Tests: added `Julia Extraction` describe block in `engine/__tests__/extraction.test.ts`
- Notes: Julia's tree-sitter grammar uses **no named fields** (all `childForFieldName` calls
  return null). The extractor uses `visitNode` throughout. Key AST quirks:
  - `function_definition`: children by index — `[0]=function`, `[1]=signature(call_expression(identifier, argument_list))`, `[2]=block`, `[3]=end`
  - Short-form functions `f() = expr` are parsed as `assignment` with a `call_expression` on the LHS (not a dedicated `short_function_definition` node)
  - `const_statement` wraps an inner `assignment` node
  - `macro_definition` has the same structure as `function_definition`
  - Call edges work via the standard `call_expression` in `callTypes`; `visitFunctionBody` recursively finds them

### MATLAB (added 2026-05-30)
- WASM grammar: `engine/src/extraction/wasm/tree-sitter-matlab.wasm` built locally from acristoffers/tree-sitter-matlab (upstream ships only Python wheels)
- Extension map: `.m` is shared with Objective-C; disambiguated by `detectLanguage(filePath, content)` content heuristic that checks for ObjC markers (`@interface`, `@implementation`, `#import`, `#include`) in the first 4 KB. `EXTENSION_MAP` still maps `.m` → `objc` as the default; the heuristic overrides to `matlab` only when no ObjC markers are found.
- Extractor: `engine/src/extraction/languages/matlab.ts`
- Tests: extraction + disambiguation tests in `engine/__tests__/extraction.test.ts` (`MATLAB Extraction` describe block; 14 tests total)
- Notes: MATLAB grammar (acristoffers/tree-sitter-matlab) key AST facts confirmed empirically:
  - `function_definition`: field `'name'` → function identifier; `function_output` optional named child for return values; `function_arguments` named child for params; `block` named child for body
  - Three function forms: `function greet()`, `function result = hello(name)`, `function [a,b] = swap(x,y)` — all produce `function_definition` nodes with the same structure
  - `function_call`: field `'name'` → callee identifier; used for call edges via `callTypes: ['function_call']`
  - `assignment`: fields `'left'` and `'right'`; top-level identifier-lhs assignments → variable nodes
  - Grammar does NOT use `call_expression` (unlike most other languages); uses `function_call` instead
