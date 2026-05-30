import { getNodeText } from '../tree-sitter-helpers';
import type { LanguageExtractor, ExtractorContext } from '../tree-sitter-types';
import type { Node as SyntaxNode } from 'web-tree-sitter';

/**
 * Julia Language Extractor
 *
 * Julia has named, positional, and short-form function syntax:
 *   function foo(x, y) ... end          → function_definition
 *   foo(x) = expr                        → assignment (lhs = call_expression)
 *   macro mymacro(x) ... end             → macro_definition
 *
 * Julia's tree-sitter grammar does NOT use named fields (childForFieldName
 * returns nothing). Children are accessed by index.
 *
 * Key node kinds:
 *   function_definition — `function foo(...) ... end`
 *     child[0]: `function` keyword
 *     child[1]: `signature` node containing a `call_expression(identifier, argument_list)`
 *     child[2]: `block`
 *     child[3]: `end`
 *
 *   macro_definition — `macro foo(...) ... end`
 *     Same structure as function_definition.
 *
 *   assignment — `x = expr` or `foo() = expr` (short function)
 *     child[0]: identifier OR call_expression (short function LHS)
 *     child[1]: operator (`=`)
 *     child[2]: value
 *
 *   const_statement — `const x = expr`
 *     child[0]: `const` keyword
 *     child[1]: inner `assignment` node
 *
 *   using_statement — `using Pkg` / `using Statistics: mean`
 *   import_statement — `import CSV` / `import Base: show`
 *
 *   struct_definition — `struct Point ... end`
 *   abstract_definition — `abstract type Animal end`
 *
 *   call_expression — `foo(args...)` — used for call edges
 */

/**
 * Extract the function/macro name from a function_definition or macro_definition node.
 *
 * Both have:  keyword  signature(call_expression(identifier  argument_list))  block  end
 * The name is the first named child of the call_expression inside the signature.
 */
function extractFuncName(node: SyntaxNode, source: string): string | undefined {
  // child[1] is the signature node
  const signature = node.child(1);
  if (!signature || signature.type !== 'signature') return undefined;
  // signature's first (and only named) child is a call_expression
  const callExpr = signature.namedChild(0);
  if (!callExpr || callExpr.type !== 'call_expression') return undefined;
  // call_expression's first named child is the identifier
  const ident = callExpr.namedChild(0);
  if (!ident) return undefined;
  return getNodeText(ident, source);
}

/**
 * Extract the parameter text from a function/macro signature.
 * Returns the argument_list text (e.g. "(x, y::Int)").
 */
function extractParams(node: SyntaxNode, source: string): string | undefined {
  const signature = node.child(1);
  if (!signature || signature.type !== 'signature') return undefined;
  const callExpr = signature.namedChild(0);
  if (!callExpr || callExpr.type !== 'call_expression') return undefined;
  // argument_list is the second named child
  const argList = callExpr.namedChild(1);
  if (!argList) return undefined;
  return getNodeText(argList, source);
}

/**
 * Extract module name from a using_statement or import_statement.
 *
 * Forms:
 *   using Pkg              → identifier "Pkg"
 *   using Statistics: mean → selected_import "Statistics: mean"
 *   import Base: show      → selected_import "Base: show"
 */
function extractImportModule(node: SyntaxNode, source: string): string {
  // The second child (index 1) is either identifier or selected_import
  const target = node.child(1) ?? node.namedChild(0);
  if (!target) return getNodeText(node, source);
  if (target.type === 'selected_import') {
    // module is the first named child of selected_import
    const mod = target.namedChild(0);
    return mod ? getNodeText(mod, source) : getNodeText(target, source);
  }
  return getNodeText(target, source);
}

export const juliaExtractor: LanguageExtractor = {
  // All interesting patterns are handled by visitNode below.
  functionTypes: [],
  classTypes: [],
  methodTypes: [],
  interfaceTypes: [],
  structTypes: [],
  enumTypes: [],
  typeAliasTypes: [],
  importTypes: [],
  callTypes: ['call_expression'],
  variableTypes: [],

  // Field names — not used for Julia (no named fields), but required by interface
  nameField: 'name',
  bodyField: 'body',
  paramsField: 'parameters',
  returnField: undefined,

  isAsync: () => false,
  isStatic: () => false,

  extractImport: () => null, // handled entirely in visitNode

  /**
   * Custom visitor for Julia's AST.
   *
   * Handles:
   *   function_definition / macro_definition  → 'function' node
   *   assignment with call_expression LHS     → short-form function
   *   assignment with identifier LHS          → variable node
   *   const_statement                         → constant node (via inner assignment)
   *   using_statement / import_statement      → import node
   *   struct_definition                       → struct node
   *   abstract_definition                     → interface node
   */
  visitNode: (node: SyntaxNode, ctx: ExtractorContext): boolean => {
    const type = node.type;

    // ── function_definition / macro_definition ─────────────────────────────
    if (type === 'function_definition' || type === 'macro_definition') {
      const name = extractFuncName(node, ctx.source);
      if (!name) return false;

      const params = extractParams(node, ctx.source);
      const funcNode = ctx.createNode('function', name, node, {
        signature: params,
        isAsync: false,
        isStatic: false,
      });
      if (funcNode) {
        ctx.pushScope(funcNode.id);
        // child[2] is the block body
        const body = node.child(2);
        if (body && body.type === 'block') {
          ctx.visitFunctionBody(body, funcNode.id);
        }
        ctx.popScope();
      }
      return true;
    }

    // ── assignment ─────────────────────────────────────────────────────────
    if (type === 'assignment') {
      const lhs = node.child(0);
      const rhs = node.child(2);
      if (!lhs || !rhs) return false;

      if (lhs.type === 'call_expression') {
        // Short-form function: greet() = hello("world")
        const ident = lhs.namedChild(0);
        if (!ident || ident.type !== 'identifier') return false;
        const name = getNodeText(ident, ctx.source);
        const argList = lhs.namedChild(1);
        const params = argList ? getNodeText(argList, ctx.source) : undefined;

        const funcNode = ctx.createNode('function', name, node, {
          signature: params,
          isAsync: false,
          isStatic: false,
        });
        if (funcNode) {
          ctx.pushScope(funcNode.id);
          ctx.visitFunctionBody(rhs, funcNode.id);
          ctx.popScope();
        }
        return true;
      }

      if (lhs.type === 'identifier') {
        // Plain variable assignment: x = 42
        const name = getNodeText(lhs, ctx.source);
        const initValue = getNodeText(rhs, ctx.source).slice(0, 100);
        const initSignature = initValue
          ? `= ${initValue}${initValue.length >= 100 ? '...' : ''}`
          : undefined;
        ctx.createNode('variable', name, node, { signature: initSignature });
        // Visit rhs so we capture any calls in the initializer
        ctx.visitNode(rhs);
        return true;
      }

      return false;
    }

    // ── const_statement ────────────────────────────────────────────────────
    if (type === 'const_statement') {
      // child[1] is the inner assignment
      const inner = node.child(1);
      if (!inner || inner.type !== 'assignment') return false;
      const lhs = inner.child(0);
      const rhs = inner.child(2);
      if (!lhs || lhs.type !== 'identifier') return false;
      const name = getNodeText(lhs, ctx.source);
      const initValue = rhs ? getNodeText(rhs, ctx.source).slice(0, 100) : undefined;
      const initSignature = initValue
        ? `= ${initValue}${initValue.length >= 100 ? '...' : ''}`
        : undefined;
      ctx.createNode('constant', name, node, { signature: initSignature });
      return true;
    }

    // ── using_statement / import_statement ─────────────────────────────────
    if (type === 'using_statement' || type === 'import_statement') {
      const moduleName = extractImportModule(node, ctx.source);
      const importText = getNodeText(node, ctx.source);
      ctx.createNode('import', moduleName, node, { signature: importText });
      return true;
    }

    // ── struct_definition ──────────────────────────────────────────────────
    if (type === 'struct_definition') {
      // struct Foo ... end
      // child[0]: `struct` keyword  (may have `mutable` prefix handled differently)
      // The type_head child holds the name
      let nameText: string | undefined;
      for (let i = 0; i < node.childCount; i++) {
        const child = node.child(i);
        if (child && child.type === 'type_head') {
          const ident = child.namedChild(0);
          nameText = ident ? getNodeText(ident, ctx.source) : getNodeText(child, ctx.source);
          break;
        }
      }
      if (!nameText) return false;
      ctx.createNode('struct', nameText, node, {});
      return true;
    }

    // ── abstract_definition ────────────────────────────────────────────────
    if (type === 'abstract_definition') {
      // abstract type Animal end
      let nameText: string | undefined;
      for (let i = 0; i < node.childCount; i++) {
        const child = node.child(i);
        if (child && child.type === 'type_head') {
          const ident = child.namedChild(0);
          nameText = ident ? getNodeText(ident, ctx.source) : getNodeText(child, ctx.source);
          break;
        }
      }
      if (!nameText) return false;
      ctx.createNode('interface', nameText, node, {});
      return true;
    }

    return false; // let default walker handle other nodes
  },
};
