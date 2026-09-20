import type { StagedHostPreservation } from "../projections/host-runtime.ts";

export const stageShellSwap = (
  current: HTMLElement,
  next: HTMLElement,
  hosts: StagedHostPreservation,
) => {
  let committed = false;
  let finalized = false;
  const rollback = () => {
    if (finalized) {
      return;
    }
    if (committed) {
      // State-preserving host moves require both shells to remain connected.
      next.before(current);
      try {
        hosts.rollback();
      } finally {
        next.remove();
        committed = false;
      }
      return;
    }
    hosts.rollback();
  };
  return {
    commit() {
      if (committed || finalized) {
        return;
      }
      current.before(next);
      try {
        hosts.commit();
      } catch (error) {
        next.remove();
        throw error;
      }
      current.remove();
      committed = true;
    },
    rollback,
    finalize() {
      if (!committed || finalized) {
        return;
      }
      hosts.finalize();
      finalized = true;
    },
    discard: rollback,
  };
};
