import assert from "node:assert/strict";
import test from "node:test";
import { parseLimit, readProject } from "../src/server/access.ts";

const project = { id: "project-1", tenantId: "tenant-a" };

test("an administrator can read a project in their own tenant", () => {
  assert.deepEqual(
    readProject({ tenantId: "tenant-a", role: "admin" }, project),
    { id: "project-1" },
  );
});

test("an unauthenticated caller cannot read a project", () => {
  assert.throws(() => readProject(null, project), /^Error: unauthenticated$/);
});

test("a valid foreign project ID does not bypass tenant isolation", () => {
  assert.throws(
    () => readProject({ tenantId: "tenant-b", role: "admin" }, project),
    /^Error: not_found$/,
  );
});

test("membership does not grant an administrator operation", () => {
  assert.throws(
    () => readProject({ tenantId: "tenant-a", role: "member" }, project),
    /^Error: forbidden$/,
  );
});

test("pagination accepts its inclusive boundaries", () => {
  assert.equal(parseLimit(1), 1);
  assert.equal(parseLimit(100), 100);
});

for (const value of [
  0,
  -1,
  101,
  1.5,
  NaN,
  Infinity,
  "10",
  null,
  undefined,
  {},
]) {
  test(`invalid pagination value ${String(value)} fails safely`, () => {
    assert.throws(() => parseLimit(value), /^Error: invalid_limit$/);
  });
}
