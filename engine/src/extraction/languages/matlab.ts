import { getNodeText, getChildByField } from '../tree-sitter-helpers';
import type { LanguageExtractor, ExtractorContext } from '../tree-sitter-types';
import type { Node as SyntaxNode } from 'web-tree-sitter';

/**
 * MATLAB Language Extractor
 *
 * MATLAB function syntax:
 *   function greet()                       — no output
 *   function result = hello(name)          — single output
 *   function [a, b] = swap(x, y)           — multiple outputs
 *
 * Grammar used: acristoffers/tree-sitter-matlab (vendored WASM)
 *
 * Key node kinds confirmed by AST inspection:
 *   function_definition — function definitions (all three forms above)
 *     field 'name': identifier — the function name
 *     field 'function_arguments': argument list node
 *     function_output (optional named child): single or multi-return marker
 *     block: function body
 *
 *   function_call — foo(args)
 *     field 'name': identifier — callee name
 *
 *   assignment — x = expr
 *     field 'left': lhs (identifier or complex expression)
 *     field 'right': rhs
 *
 * MATLAB has no class or import syntax in the file-based sense (classdef
 * exists but is handled separately; scripts have no module imports). We
 * focus on functions, calls, and top-level variable assignments.
 */

export const matlabExtractor: LanguageExtractor = {
  // All interesting patterns handled by visitNode
  functionTypes: [],
  classTypes: [],
  methodTypes: [],
  interfaceTypes: [],
  structTypes: [],
  enumTypes: [],
  typeAliasTypes: [],
  importTypes: [],
  callTypes: ['function_call'],
  variableTypes: [],

  // Field names — used as fallbacks; primary extraction is in visitNode
  nameField: 'name',
  bodyField: 'body',
  paramsField: 'function_arguments',
  returnField: undefined,

  isAsync: () => false,
  isStatic: () => false,

  extractImport: () => null,

  /**
   * Custom visitor for MATLAB's AST.
   *
   * Handles:
   *   function_definition  → 'function' node (all return forms)
   *   assignment with identifier lhs → 'variable' node (top-level only)
   */
  visitNode: (node: SyntaxNode, ctx: ExtractorContext): boolean => {
    const type = node.type;

    // ── function_definition ────────────────────────────────────────────────
    if (type === 'function_definition') {
      // The 'name' field always holds the function identifier
      const nameNode = getChildByField(node, 'name');
      if (!nameNode) return false;
      const name = getNodeText(nameNode, ctx.source);

      // Build signature string: [outputs] = name(params)
      // Find function_output (optional) and function_arguments among named children
      let outputText = '';
      let paramsText = '';
      let bodyNode: SyntaxNode | null = null;

      for (let i = 0; i < node.childCount; i++) {
        const child = node.child(i);
        if (!child || !child.isNamed) continue;
        if (child.type === 'function_output') {
          outputText = getNodeText(child, ctx.source); // e.g. "result =" or "[a, b] ="
        } else if (child.type === 'function_arguments') {
          paramsText = getNodeText(child, ctx.source); // e.g. "(name)" or "()"
        } else if (child.type === 'block') {
          bodyNode = child;
        }
      }

      const signature = outputText
        ? `${outputText} ${name}${paramsText}`
        : `${name}${paramsText}`;

      const funcNode = ctx.createNode('function', name, node, {
        signature,
        isAsync: false,
        isStatic: false,
      });
      if (funcNode && bodyNode) {
        ctx.pushScope(funcNode.id);
        ctx.visitFunctionBody(bodyNode, funcNode.id);
        ctx.popScope();
      }
      return true;
    }

    // ── assignment ─────────────────────────────────────────────────────────
    if (type === 'assignment') {
      const lhsNode = getChildByField(node, 'left');
      const rhsNode = getChildByField(node, 'right');
      if (!lhsNode || !rhsNode) return false;

      // Only extract simple identifier assignments at script scope
      if (lhsNode.type !== 'identifier') return false;

      const name = getNodeText(lhsNode, ctx.source);
      const initValue = getNodeText(rhsNode, ctx.source).slice(0, 100);
      const initSignature = initValue
        ? `= ${initValue}${initValue.length >= 100 ? '...' : ''}`
        : undefined;

      ctx.createNode('variable', name, node, { signature: initSignature });
      // Visit rhs to capture any calls in the initializer
      ctx.visitNode(rhsNode);
      return true;
    }

    return false;
  },
};
