import tseslint from "typescript-eslint";

// Copy and tune in the consumer; this example does not select a Proof mode.
export default tseslint.config(
  { ignores: ["coverage/**", "dist/**", "node_modules/**"] },
  {
    files: ["src/**/*.ts"],
    extends: [...tseslint.configs.recommendedTypeChecked],
    languageOptions: {
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    rules: {
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/no-misused-promises": "error",
      "@typescript-eslint/no-non-null-assertion": "error",
      "no-empty": ["error", { allowEmptyCatch: false }],
      "no-unsafe-finally": "error",
    },
  },
);
