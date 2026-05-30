import { getNodeText, getChildByField } from '../tree-sitter-helpers';
import type { LanguageExtractor, ExtractorContext } from '../tree-sitter-types';
import type { Node as SyntaxNode } from 'web-tree-sitter';

/**
 * R Language Extractor
 *
 * R uses assignment operators (<-, =, ->>) to bind names to values.
 * Functions are anonymous expressions: `foo <- function(x) { ... }`
 * Tree-sitter-r parses all assignments as `binary_operator` with
 * fields `lhs`, `operator`, and `rhs`.
 *
 * Key node kinds:
 *   binary_operator  — all assignments (lhs, operator, rhs fields)
 *   function_definition — anonymous function literal (parameters, body fields)
 *   call             — function call (function, arguments fields)
 *   program          — root node
 *
 * R has no native classes (S3/S4/R5/R6 are runtime constructs), no import
 * statement (library()/require() are plain calls), and no async.
 */

/** Assignment operators that bind a name to a value. */
const ASSIGN_OPS = new Set(['<-', '<<-', '=', '->', '->>']);

/** Whether this binary_operator node is a forward assignment (-> or ->>) */
function isForwardAssign(op: string): boolean {
  return op === '->' || op === '->>';
}

export const rExtractor: LanguageExtractor = {
  // R function_definition is an anonymous expression — names come from the
  // surrounding binary_operator assignment, handled in visitNode below.
  functionTypes: [],
  classTypes: [],
  methodTypes: [],
  interfaceTypes: [],
  structTypes: [],
  enumTypes: [],
  typeAliasTypes: [],
  importTypes: [],
  callTypes: ['call'],
  // binary_operator covers all assignments; visitNode handles them.
  variableTypes: ['binary_operator'],

  // Field names on function_definition
  nameField: 'name',        // unused (no name field on function_definition)
  bodyField: 'body',        // body field of function_definition → braced_expression
  paramsField: 'parameters', // parameters field of function_definition

  getSignature: (node, source) => {
    // node here is the function_definition — extract its parameter list
    const params = getChildByField(node, 'parameters');
    return params ? getNodeText(params, source) : undefined;
  },

  isAsync: () => false,
  isStatic: () => false,
  extractImport: () => null,

  /**
   * Custom visitor for R's assignment-centric AST.
   *
   * R grammar:
   *   binary_operator { lhs: identifier, operator: <-, rhs: function_definition }
   *   binary_operator { lhs: identifier, operator: <-, rhs: <scalar/expression>  }
   *   binary_operator { lhs: function_definition, operator: ->, rhs: identifier  } (rare)
   *
   * Strategy:
   *   - If the assignment rhs (or lhs for ->/->>) is a function_definition,
   *     create a 'function' node named by the identifier on the other side.
   *   - Otherwise create a 'variable' node for simple assignments.
   *   - For non-assignment binary_operator (inside function bodies),
   *     return false and let the default walker handle call nodes inside.
   */
  visitNode: (node: SyntaxNode, ctx: ExtractorContext): boolean => {
    if (node.type !== 'binary_operator') return false;

    const lhs = getChildByField(node, 'lhs');
    const rhs = getChildByField(node, 'rhs');
    const opNode = getChildByField(node, 'operator');
    if (!lhs || !rhs || !opNode) return false;

    const op = getNodeText(opNode, ctx.source);
    if (!ASSIGN_OPS.has(op)) return false;  // e.g. arithmetic +, -, etc.

    // Determine name and function node based on assignment direction
    const forward = isForwardAssign(op);
    const nameNode = forward ? rhs : lhs;
    const valNode  = forward ? lhs : rhs;

    // Only handle simple identifier names (skip complex lhs like `obj$field`)
    if (!nameNode || nameNode.type !== 'identifier') return false;
    if (!valNode) return false;

    const name = getNodeText(nameNode, ctx.source);

    if (valNode.type === 'function_definition') {
      // Named function assignment: foo <- function(x) { ... }
      const funcNode = ctx.createNode('function', name, node, {
        signature: undefined,
        isAsync: false,
        isStatic: false,
      });
      if (funcNode) {
        ctx.pushScope(funcNode.id);
        const body = getChildByField(valNode, 'body');
        if (body) {
          ctx.visitFunctionBody(body, funcNode.id);
        }
        ctx.popScope();
      }
      return true; // handled
    }

    // Plain variable assignment: x <- 42, df <- data.frame(...)
    // Only extract at top/function scope (not inside other assignments)
    const initValue = getNodeText(valNode, ctx.source).slice(0, 100);
    const initSignature = initValue
      ? `<- ${initValue}${initValue.length >= 100 ? '...' : ''}`
      : undefined;
    ctx.createNode('variable', name, node, {
      signature: initSignature,
    });
    // Still visit the rhs so we capture any calls inside the initializer
    ctx.visitNode(valNode);
    return true; // handled
  },
};
