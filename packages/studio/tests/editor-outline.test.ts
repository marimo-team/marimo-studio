import { describe, expect, it } from "vite-plus/test";

import { installEditorOutlineGuard, repairOutlineXPath } from "../src/preview/editor-outline.ts";

describe("editor outline compatibility", () => {
  it.each([
    [
      'Wall Design From the Portfolio: "Decorative Art of Spanish California"',
      `//H3[contains(., 'Wall Design From the Portfolio: "Decorative Art of Spanish California"')]`,
    ],
    [
      'The painter\'s "Study"',
      `//H3[contains(., concat("The painter's ", '"', "Study", '"', ""))]`,
    ],
  ])("repairs a quoted heading locator", (title, expected) => {
    const path = `//H3[contains(., "${title}")]`;
    expect(repairOutlineXPath(path)).toBe(expected);
  });

  it("leaves unrelated XPath failures unchanged", () => {
    expect(repairOutlineXPath("//*[broken")).toBeUndefined();
  });

  it("retries a quoted heading locator and restores the native evaluator", () => {
    const title = 'Wall Design From the Portfolio: "Decorative Art of Spanish California"';
    const path = `//H3[contains(., "${title}")]`;
    const repaired = repairOutlineXPath(path);
    const match = { singleNodeValue: { title } } as unknown as XPathResult;
    const contextNode = {} as Node;
    const expressions: string[] = [];
    const nativeEvaluate: Document["evaluate"] = (expression) => {
      expressions.push(expression);
      if (expression === path) {
        throw new DOMException("Invalid XPath");
      }
      return match;
    };
    const editorDocument: Pick<Document, "evaluate"> = {
      evaluate: nativeEvaluate,
    };

    expect(() => editorDocument.evaluate(path, contextNode, null, 0, null)).toThrow();

    const dispose = installEditorOutlineGuard(editorDocument);
    expect(editorDocument.evaluate(path, contextNode, null, 0, null)).toBe(match);
    expect(expressions.slice(-2)).toEqual([path, repaired]);

    dispose();
    expect(editorDocument.evaluate).toBe(nativeEvaluate);
  });
});
