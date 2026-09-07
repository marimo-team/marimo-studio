import { syncProjectionHostAttributes } from "../cells/host.ts";
import { isArtifactProjectionHost } from "../projections/artifact-host.ts";

const PROJECTION_HOST_SELECTOR =
  "marimo-cell[data-hx-preserve][id], " +
  "marimo-output[data-hx-preserve][id], " +
  "[mo-value][data-hx-preserve][id]";

const isProjectionHost = (node: Node): node is HTMLElement =>
  node instanceof HTMLElement &&
  node.matches(PROJECTION_HOST_SELECTOR) &&
  isArtifactProjectionHost(node);

interface HostPosition {
  readonly ancestors: string;
  readonly localName: string;
  readonly path: string;
}

const elementIdentity = (element: Element): string =>
  `${element.namespaceURI ?? ""}\u0000${element.localName}`;

const hostPositions = (root: HTMLElement): Map<string, HostPosition> => {
  const positions = new Map<string, HostPosition>();
  const visit = (parent: Element, path: readonly number[], ancestors: readonly string[]) => {
    Array.from(parent.children).forEach((child, index) => {
      const childPath = [...path, index];
      if (isProjectionHost(child)) {
        positions.set(child.id, {
          ancestors: ancestors.join("\u0001"),
          localName: child.localName,
          path: childPath.join("."),
        });
        return;
      }
      visit(child, childPath, [...ancestors, elementIdentity(child)]);
    });
  };
  visit(root, [], [elementIdentity(root)]);
  return positions;
};

export const sameProjectionHostTopology = (current: HTMLElement, next: HTMLElement): boolean => {
  const left = hostPositions(current);
  const right = hostPositions(next);
  return (
    left.size === right.size &&
    Array.from(left).every(
      ([id, position]) =>
        right.get(id)?.localName === position.localName &&
        right.get(id)?.path === position.path &&
        right.get(id)?.ancestors === position.ancestors,
    )
  );
};

const syncAttributes = (current: Element, source: Element): void => {
  Array.from(current.attributes).forEach((attribute) => {
    if (!source.hasAttribute(attribute.name)) {
      current.removeAttribute(attribute.name);
    }
  });
  Array.from(source.attributes).forEach((attribute) => {
    if (current.getAttribute(attribute.name) !== attribute.value) {
      current.setAttribute(attribute.name, attribute.value);
    }
  });
};

const removeUntil = (parent: Element, cursor: ChildNode | null, target: ChildNode): ChildNode => {
  let current = cursor;
  while (current && current !== target) {
    const next = current.nextSibling;
    if (isProjectionHost(current)) {
      throw new Error("Projection host topology changed during the document refresh");
    }
    current.remove();
    current = next;
  }
  if (current !== target || target.parentNode !== parent) {
    throw new Error("Projection host moved during the document refresh");
  }
  return target;
};

const morphChildren = (current: Element, source: Element): void => {
  let cursor = current.firstChild;
  for (const sourceChild of Array.from(source.childNodes)) {
    if (isProjectionHost(sourceChild)) {
      const live = Array.from(current.children).find(
        (child): child is HTMLElement => isProjectionHost(child) && child.id === sourceChild.id,
      );
      if (!live || live.localName !== sourceChild.localName) {
        throw new Error(`Projection host ${JSON.stringify(sourceChild.id)} is unavailable`);
      }
      removeUntil(current, cursor, live);
      syncProjectionHostAttributes(live, sourceChild);
      cursor = live.nextSibling;
      continue;
    }

    if (sourceChild instanceof Element) {
      let target: Element;
      if (
        cursor instanceof Element &&
        !isProjectionHost(cursor) &&
        cursor.namespaceURI === sourceChild.namespaceURI &&
        cursor.localName === sourceChild.localName
      ) {
        target = cursor;
      } else {
        const clone = sourceChild.cloneNode(false);
        if (!(clone instanceof Element)) {
          throw new Error("Unable to clone an authored shell element");
        }
        target = clone;
        current.insertBefore(target, cursor);
      }
      syncAttributes(target, sourceChild);
      morphChildren(target, sourceChild);
      cursor = target.nextSibling;
      continue;
    }

    if (cursor?.nodeType === sourceChild.nodeType && !isProjectionHost(cursor)) {
      if (cursor.nodeValue !== sourceChild.nodeValue) {
        cursor.nodeValue = sourceChild.nodeValue;
      }
      cursor = cursor.nextSibling;
      continue;
    }
    const inserted = sourceChild.cloneNode(true);
    current.insertBefore(inserted, cursor);
    cursor = inserted.nextSibling;
  }

  while (cursor) {
    const next = cursor.nextSibling;
    if (isProjectionHost(cursor)) {
      throw new Error("Projection host topology changed during the document refresh");
    }
    cursor.remove();
    cursor = next;
  }
};

export const morphAuthoredShell = (current: HTMLElement, source: HTMLElement): void => {
  if (!sameProjectionHostTopology(current, source)) {
    throw new Error("Projection host topology changed during the document refresh");
  }
  syncAttributes(current, source);
  morphChildren(current, source);
};
