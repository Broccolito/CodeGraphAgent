import { getNodeText } from '../tree-sitter-helpers';
import type { LanguageExtractor, ExtractorContext } from '../tree-sitter-types';
import type { Node as SyntaxNode } from 'web-tree-sitter';

/**
 * Perl Language Extractor
 *
 * Key node kinds confirmed by empirical AST inspection of tree-sitter-perl
 * v1.0.2 (vendored WASM):
 *
 *   subroutine_declaration_statement — `sub NAME { ... }`
 *     namedChild[0]: bareword  — subroutine name
 *     namedChild[1]: block     — body
 *     (no named fields; tree-sitter-perl does not use childForFieldName)
 *
 *   function_call_expression — `foo(args)`
 *     child[0]: `function` node — callee name
 *     (no named fields)
 *
 *   ambiguous_function_call_expression — `print foo(args)`
 *     child[0]: `function` node — outer callee
 *     child[1]: nested call expression
 *
 *   method_call_expression — `$obj->method(args)` / `Class->method(args)`
 *     child[0]: receiver (scalar or bareword)
 *     child[2]: `method` node — method name
 *
 *   use_statement — `use Module;` / `use Module qw(...);`
 *     namedChild[0]: package — module name
 *
 *   require_expression — `require Module;`
 *     namedChild[0]: bareword — module name
 *
 *   package_statement — `package MyPackage;`
 *     namedChild[0]: package — package name (the identifier, not the keyword)
 *     Note: namedChild[0].type === 'package' for BOTH the keyword (unnamed)
 *     and the name (named). The grammar re-uses the node type 'package' for
 *     the name — we take the first **named** child.
 *
 * Perl has no native class syntax (bless/Moose are runtime constructs), no
 * typed variables, and no async keyword. Imports are `use` and `require`.
 */

export const perlExtractor: LanguageExtractor = {
  // All interesting patterns handled in visitNode below.
  functionTypes: [],
  classTypes: [],
  methodTypes: [],
  interfaceTypes: [],
  structTypes: [],
  enumTypes: [],
  typeAliasTypes: [],
  importTypes: [],
  // Call types captured via the standard callTypes dispatch:
  callTypes: ['function_call_expression', 'ambiguous_function_call_expression', 'method_call_expression'],
  variableTypes: [],

  // Field names — Perl grammar uses no named fields; required by interface.
  nameField: 'name',
  bodyField: 'body',
  paramsField: 'parameters',
  returnField: undefined,

  isAsync: () => false,
  isStatic: () => false,

  extractImport: () => null, // handled in visitNode

  /**
   * Custom visitor for Perl's AST.
   *
   * Handles:
   *   subroutine_declaration_statement → 'function' node
   *   use_statement                    → 'import' node
   *   require_expression               → 'import' node
   *   package_statement                → 'module' node (package namespace marker)
   */
  visitNode: (node: SyntaxNode, ctx: ExtractorContext): boolean => {
    const type = node.type;

    // ── subroutine_declaration_statement ──────────────────────────────────────
    if (type === 'subroutine_declaration_statement') {
      // namedChild[0] = bareword (name), namedChild[1] = block (body)
      const nameNode = node.namedChild(0);
      if (!nameNode || nameNode.type !== 'bareword') return false;
      const name = getNodeText(nameNode, ctx.source);

      const bodyNode = node.namedChild(1);

      const funcNode = ctx.createNode('function', name, node, {
        signature: `sub ${name}`,
        isAsync: false,
        isStatic: false,
      });

      if (funcNode && bodyNode && bodyNode.type === 'block') {
        ctx.pushScope(funcNode.id);
        ctx.visitFunctionBody(bodyNode, funcNode.id);
        ctx.popScope();
      }
      return true;
    }

    // ── use_statement ─────────────────────────────────────────────────────────
    if (type === 'use_statement') {
      // namedChild[0] is the package (module) name.
      // Skip pragmas: strict, warnings, feature, etc. — they're not module imports
      // but we still emit an import node so the graph captures all dependencies.
      const pkgNode = node.namedChild(0);
      if (!pkgNode) return false;
      const moduleName = getNodeText(pkgNode, ctx.source);
      const signature = getNodeText(node, ctx.source).replace(/;$/, '').trim();
      ctx.createNode('import', moduleName, node, { signature });
      return true;
    }

    // ── require_expression ────────────────────────────────────────────────────
    if (type === 'require_expression') {
      // namedChild[0] is the bareword or string module name
      const modNode = node.namedChild(0);
      if (!modNode) return false;
      const moduleName = getNodeText(modNode, ctx.source);
      const signature = getNodeText(node, ctx.source).trim();
      ctx.createNode('import', moduleName, node, { signature });
      return true;
    }

    // ── package_statement ─────────────────────────────────────────────────────
    if (type === 'package_statement') {
      // namedChild[0] is the package name (type='package', but it IS the name)
      const pkgNode = node.namedChild(0);
      if (!pkgNode) return false;
      const packageName = getNodeText(pkgNode, ctx.source);
      ctx.createNode('module', packageName, node, { signature: `package ${packageName}` });
      return true;
    }

    return false;
  },

  /**
   * Override call name resolution for Perl.
   *
   * The standard resolver looks for the `nameField` ('name') on call nodes,
   * but Perl's grammar uses unnamed children:
   *   function_call_expression         → child[0] has type 'function'
   *   ambiguous_function_call_expression → child[0] has type 'function'
   *   method_call_expression           → child[2] has type 'method'
   *
   * We use resolveName to extract the callee text for all three forms.
   */
  resolveName: (node: SyntaxNode, source: string): string | undefined => {
    const type = node.type;

    if (type === 'function_call_expression' || type === 'ambiguous_function_call_expression') {
      // child[0] is the function node (type='function')
      const callee = node.child(0);
      if (!callee) return undefined;
      return getNodeText(callee, source);
    }

    if (type === 'method_call_expression') {
      // child[2] is the method node (type='method')
      const methodNode = node.child(2);
      if (!methodNode) return undefined;
      return getNodeText(methodNode, source);
    }

    return undefined;
  },
};
