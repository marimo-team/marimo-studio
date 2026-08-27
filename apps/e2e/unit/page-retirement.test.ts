import { expect, test } from "vite-plus/test";

import { ExactPageRetirementWitness } from "../tests/page-retirement.ts";

test("page retirement owns requests across captured owners", () => {
  const witness = new ExactPageRetirementWitness<object>();
  const owners = [{ name: "document" }, { name: "preview" }];
  owners.forEach((owner) => witness.recordOwner(owner));
  owners.forEach((owner) => {
    expect(witness.recordAbort(owner, "net::ERR_ABORTED")).toBe(true);
  });
  witness.recordClosed();

  expect(witness.recover(true)).toBe(true);
  expect(witness.diagnostics()).toEqual([]);
});

test("page retirement rejects recovery before the close event", () => {
  const witness = new ExactPageRetirementWitness<object>();
  witness.recordOwner({});

  expect(witness.recover(false)).toBe(false);
  expect(witness.diagnostics()).toEqual(
    expect.arrayContaining([
      "expected page retirement recovered before the page closed",
      "expected page retirement observed no page close",
    ]),
  );
});

test("page retirement never claims a foreign request owner", () => {
  const witness = new ExactPageRetirementWitness<object>();
  const owned = {};
  witness.recordOwner(owned);

  expect(witness.recordAbort({}, "net::ERR_ABORTED")).toBe(false);
  expect(witness.recordAbort(owned, "net::ERR_FAILED")).toBe(false);
});
