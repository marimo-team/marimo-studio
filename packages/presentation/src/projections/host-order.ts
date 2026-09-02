export const hostsInDocumentOrder = <Host extends Element>(
  hosts: Iterable<Host>,
): readonly Host[] =>
  Array.from(hosts).sort((left, right) => {
    if (left === right || left.ownerDocument !== right.ownerDocument) {
      return 0;
    }
    const position = left.compareDocumentPosition(right);
    if (position & Node.DOCUMENT_POSITION_FOLLOWING) {
      return -1;
    }
    if (position & Node.DOCUMENT_POSITION_PRECEDING) {
      return 1;
    }
    return 0;
  });
