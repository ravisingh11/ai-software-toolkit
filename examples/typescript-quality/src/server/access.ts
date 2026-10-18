// Deliberately small example behavior for the defensive test recipe.
export interface Session {
  tenantId: string;
  role: "member" | "admin";
}

export interface Project {
  id: string;
  tenantId: string;
}

export function readProject(
  session: Session | null,
  project: Project,
): { id: string } {
  if (session === null) {
    throw new Error("unauthenticated");
  }
  if (session.tenantId !== project.tenantId) {
    throw new Error("not_found");
  }
  if (session.role !== "admin") {
    throw new Error("forbidden");
  }
  return { id: project.id };
}

export function parseLimit(value: unknown): number {
  if (
    typeof value !== "number" ||
    !Number.isInteger(value) ||
    value < 1 ||
    value > 100
  ) {
    throw new Error("invalid_limit");
  }
  return value;
}
