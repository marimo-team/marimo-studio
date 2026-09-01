// @vitest-environment jsdom

import { strict as assert } from "node:assert";
import { runInNewContext } from "node:vm";
import { act, type RefCallback, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { test } from "vite-plus/test";

import { composeRefs, useComposedRefs } from "../src/radix-compose-refs.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("composeRefs invokes callbacks and cleanups from another realm", () => {
  const events: string[] = [];
  // SAFETY: The evaluated function has the RefCallback shape encoded in its source.
  const foreignRef = runInNewContext(
    "(events) => (node) => { events.push(`attach:${node.id}`); return () => events.push('cleanup'); }",
  )(events) as RefCallback<HTMLDivElement>;
  const node = document.createElement("div");
  node.id = "control";

  const cleanup = composeRefs<HTMLDivElement>(foreignRef)(node);
  cleanup?.();

  assert.deepEqual(events, ["attach:control", "cleanup"]);
});

test("bare composed state refs settle after attaching one node", () => {
  const host = document.createElement("div");
  const root = createRoot(host);

  const Harness = () => {
    const objectRef = useRef<HTMLDivElement>(null);
    const [node, setNode] = useState<HTMLDivElement | null>(null);
    const composed = composeRefs<HTMLDivElement>(objectRef, setNode);
    return <div data-attached={node ? "true" : "false"} ref={composed} />;
  };

  act(() => root.render(<Harness />));
  assert.equal(host.firstElementChild?.getAttribute("data-attached"), "true");
  act(() => root.unmount());
});

test("composed refs keep one callback and use changed refs on the next attachment", () => {
  const host = document.createElement("div");
  const root = createRoot(host);
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
    return <div key={nodeKey} ref={composed} />;
  };

  act(() => root.render(<Harness generation={1} nodeKey={1} />));
  act(() => root.render(<Harness generation={2} nodeKey={1} />));
  assert.deepEqual(events, ["attach:1"]);

  act(() => root.render(<Harness generation={2} nodeKey={2} />));
  act(() => root.unmount());

  assert.deepEqual(events, ["attach:1", "cleanup:1", "attach:2", "cleanup:2"]);
});
