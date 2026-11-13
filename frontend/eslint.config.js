// ESLint flat config - the same rule set the old .eslintrc.cjs ran (eslint:recommended,
// typescript-eslint's recommended set, and the two react-hooks rules), moved to the format
// ESLint 9+ requires.
import js from '@eslint/js';
import globals from 'globals';
import reactHooks from 'eslint-plugin-react-hooks';
import tseslint from 'typescript-eslint';
import { defineConfig } from 'eslint/config';

export default defineConfig(
  { ignores: ['dist', 'vite.config.ts', 'test-results', 'playwright-report', 'blob-report'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [js.configs.recommended, tseslint.configs.recommended],
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      globals: globals.browser,
    },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      // Only the two classic hooks rules. eslint-plugin-react-hooks 7's own `recommended`
      // preset also turns on the React Compiler rules (purity, refs, set-state-in-effect,
      // ...); adopting those is a separate decision from this upgrade.
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
  {
    files: ['e2e/**/*.ts', 'playwright.config.ts'],
    languageOptions: { globals: globals.node },
  }
);
