interface DisclosureMenuOwner {
  canClose: () => boolean;
  close: () => void;
  menu: HTMLDetailsElement;
}

type DisclosureMenuScope = Node;

const ownersByScope = new WeakMap<DisclosureMenuScope, Set<DisclosureMenuOwner>>();

const scopeFor = (menu: HTMLDetailsElement): DisclosureMenuScope =>
  menu.closest("#marimo-studio-root") ?? menu.getRootNode();

export const registerDisclosureMenu = (owner: DisclosureMenuOwner): (() => void) => {
  const scope = scopeFor(owner.menu);
  const owners = ownersByScope.get(scope) ?? new Set<DisclosureMenuOwner>();
  owners.add(owner);
  ownersByScope.set(scope, owners);

  return () => {
    owners.delete(owner);
    if (owners.size === 0) {
      ownersByScope.delete(scope);
    }
  };
};

export const requestDisclosureMenuOpen = (menu: HTMLDetailsElement): boolean => {
  const peers = Array.from(ownersByScope.get(scopeFor(menu)) ?? []).filter(
    (owner) => owner.menu !== menu && owner.menu.open,
  );
  if (peers.some((peer) => !peer.canClose())) {
    return false;
  }
  peers.forEach((peer) => peer.close());
  return true;
};
