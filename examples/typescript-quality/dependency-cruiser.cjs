// Example boundaries, owned and adapted by the consuming repository.
module.exports = {
  forbidden: [
    {
      name: "no-circular-dependencies",
      severity: "error",
      from: {},
      to: { circular: true },
    },
    {
      name: "no-unresolved-imports",
      severity: "error",
      from: {},
      to: { couldNotResolve: true },
    },
    {
      name: "client-cannot-import-server",
      severity: "error",
      from: { path: "^(src/client|apps/web|packages/ui)/" },
      to: { path: "^(src/server|apps/api|packages/(database|server))/" },
    },
    {
      name: "contracts-cannot-import-applications",
      severity: "error",
      from: { path: "^(src/contracts|packages/contracts)/" },
      to: { path: "^(src/(client|server)|apps)/" },
    },
  ],
  options: {
    doNotFollow: { path: "node_modules" },
    tsPreCompilationDeps: true,
    tsConfig: { fileName: "tsconfig.json" },
  },
};
