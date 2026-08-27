// @vitest-environment jsdom

import { strict as assert } from "node:assert";
import { act, type RefCallback, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { test } from "vite-plus/test";

import { composeRefs, useComposedRefs } from "../src/radix-compose-refs.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("composeRefs reuses an identical ref tuple", () => {
  const objectRef = { current: null };
  const callbackRef = () => {};

  assert.equal(
    composeRefs<HTMLDivElement>(objectRef, callbackRef),
    composeRefs<HTMLDivElement>(objectRef, callbackRef),
  );
});

test("bare composed state refs settle after attaching one node", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const callbacks: RefCallback<HTMLDivElement>[] = [];
  let renders = 0;

  const Harness = () => {
    renders += 1;
    const objectRef = useRef<HTMLDivElement>(null);
    const [, setNode] = useState<HTMLDivElement | null>(null);
    const composed = composeRefs<HTMLDivElement>(objectRef, setNode);
    callbacks.push(composed);
    return <div ref={composed} />;
  };

  act(() => root.render(<Harness />));
  assert.equal(callbacks[0], callbacks.at(-1));
  assert.ok(renders <= 2);
  act(() => root.unmount());
});

test("composed refs keep one callback and use changed refs on the next attachment", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const identities: Array<(node: HTMLDivElement | null) => void> = [];
  const events: string[] = [];

  const Harness = ({ generation, nodeKey }: { generation: number; nodeKey: number }) => {
    const objectRef = useRef<HTMLDivElement>(null);
    const composed = useComposedRefs<HTMLDivElement>(objectRef, (node) => {
      if (node) {
        events.push(`attach:${generation}`);
        return () => {
          events.push(`cleanup:${generation}`);
        };
      }
    });
    identities.push(composed);
    return <div key={nodeKey} ref={composed} />;
  };

  act(() => root.render(<Harness generation={1} nodeKey={1} />));
  act(() => root.render(<Harness generation={2} nodeKey={1} />));
  assert.equal(identities[0], identities[1]);
  assert.deepEqual(events, ["attach:1"]);

  act(() => root.render(<Harness generation={2} nodeKey={2} />));
  act(() => root.unmount());

  assert.equal(identities[1], identities[2]);
  assert.deepEqual(events, ["attach:1", "cleanup:1", "attach:2", "cleanup:2"]);
});
