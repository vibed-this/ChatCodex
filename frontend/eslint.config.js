import js from "@eslint/js";
import jsxA11y from "eslint-plugin-jsx-a11y";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";
export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "*.config.js", "build-all.mjs"] }, js.configs.recommended,
  ...tseslint.configs.strictTypeChecked.map((c) => ({ ...c, files: ["**/*.{ts,tsx}"] })),
  { files: ["**/*.{ts,tsx}"], languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } }, plugins: { react, "react-hooks": reactHooks, "jsx-a11y": jsxA11y }, settings: { react: { version: "detect" } }, rules: { ...react.configs.recommended.rules, ...reactHooks.configs.recommended.rules, ...jsxA11y.configs.recommended.rules, "react/react-in-jsx-scope": "off", "react/prop-types": "off", "@typescript-eslint/consistent-type-imports": "error", "@typescript-eslint/no-explicit-any": "error", "@typescript-eslint/no-unnecessary-condition": "off", "@typescript-eslint/no-unsafe-assignment": "off", "@typescript-eslint/no-unsafe-argument": "off", "@typescript-eslint/no-unsafe-call": "off", "@typescript-eslint/no-unsafe-member-access": "off", "@typescript-eslint/no-unsafe-return": "off", "@typescript-eslint/no-base-to-string": "off", "@typescript-eslint/restrict-template-expressions": "off", "@typescript-eslint/no-unnecessary-type-parameters": "off", "@typescript-eslint/unbound-method": "off", "@typescript-eslint/no-non-null-assertion": "off", "@typescript-eslint/no-floating-promises": "off", "@typescript-eslint/no-misused-promises": "off", "@typescript-eslint/require-await": "off", "@typescript-eslint/prefer-promise-reject-errors": "off", "@typescript-eslint/use-unknown-in-catch-callback-variable": "off", "@typescript-eslint/no-redundant-type-constituents": "off", "@typescript-eslint/no-misused-spread": "off", "@typescript-eslint/no-dynamic-delete": "off", "no-console": "error" } },
  { files: ["**/*.{test,spec}.{ts,tsx}", "src/lib/hooks.ts", "src/lib/openai.ts", "src/panel/api.ts", "src/panel/main.tsx", "src/widgets/ask-user.tsx", "src/widgets/diff.tsx", "src/widgets/workspace-setup.tsx"], rules: { "@typescript-eslint/no-explicit-any": "off" } },
  { files: ["src/lib/DirBrowser.tsx", "src/lib/hooks.ts"], rules: { "react-hooks/exhaustive-deps": "off" } },
  { files: ["src/panel/main.tsx"], rules: { "jsx-a11y/no-autofocus": "off" } },
  { files: ["src/components/ui/card.tsx"], rules: { "jsx-a11y/heading-has-content": "off" } },
  { files: ["src/components/ui/label.tsx"], rules: { "jsx-a11y/label-has-associated-control": "off" } },
  { files: ["tests/**/*.mjs"], languageOptions: { globals: { console: "readonly" } }, rules: { "no-undef": "error", "no-useless-escape": "off" } }
);
