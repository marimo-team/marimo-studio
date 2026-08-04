const MARIMO_OUTLINE_XPATH = /^\/\/(H[1-6])\[contains\(\., "(.*)"\)\]$/su;

const xpathLiteral = (value: string): string => {
  if (!value.includes('"')) {
    return `"${value}"`;
  }
  if (!value.includes("'")) {
    return `'${value}'`;
  }
  return `concat(${value
    .split('"')
    .map((part) => `"${part}"`)
    .join(", '\"', ")})`;
};

export const repairOutlineXPath = (path: string): string | undefined => {
  const match = MARIMO_OUTLINE_XPATH.exec(path);
  if (!match) {
    return undefined;
  }
  const [, tag, title] = match;
  return `//${tag}[contains(., ${xpathLiteral(title)})]`;
};

type XPathDocument = Pick<Document, "evaluate">;

export const installEditorOutlineGuard = (document: XPathDocument): (() => void) => {
  const original = document.evaluate;
  const guarded: Document["evaluate"] = (expression, contextNode, resolver, type, result) => {
    try {
      return original.call(document, expression, contextNode, resolver, type, result);
    } catch (error) {
      const repaired = repairOutlineXPath(expression);
      if (!repaired) {
        throw error;
      }
      return original.call(document, repaired, contextNode, resolver, type, result);
    }
  };
  document.evaluate = guarded;

  return () => {
    if (document.evaluate === guarded) {
      document.evaluate = original;
    }
  };
};
