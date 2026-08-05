import { describe, expect, it } from "vite-plus/test";

import { installEditorOutlineGuard } from "../src/features/preview/editor-outline.ts";

describe("editor outline compatibility", () => {
  it("repairs quoted heading locators without intercepting other XPath failures", () => {
    const title = 'The painter\'s "Study"';
    const path = `//H3[contains(., "${title}")]`;
    const repaired = `//H3[contains(., concat("The painter's ", '"', "Study", '"', ""))]`;
    const unrelated = "//*[broken";
    const match = { singleNodeValue: { title } } as unknown as XPathResult;
    const contextNode = {} as Node;
    const expressions: string[] = [];
    const nativeEvaluate: Document["evaluate"] = (expression) => {
      expressions.push(expression);
      if (expression === path || expression === unrelated) {
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
    expect(() => editorDocument.evaluate(unrelated, contextNode, null, 0, null)).toThrow(
      "Invalid XPath",
    );

    dispose();
    expect(editorDocument.evaluate).toBe(nativeEvaluate);
  });
});
