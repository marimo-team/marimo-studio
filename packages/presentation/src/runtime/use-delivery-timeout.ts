import { useEffect, useState } from "react";

import { CELL_DELIVERY_TIMEOUT_MS, type DeliveryTimeout, deliveryTimedOut } from "./cell-state";

export const useDeliveryTimeout = (
  waiting: boolean,
  identity: string | null | undefined,
): boolean => {
  const [timeout, setTimeoutState] = useState<DeliveryTimeout | null>(null);

  useEffect(() => {
    if (!waiting) {
      return;
    }
    const timer = globalThis.setTimeout(
      () => setTimeoutState({ identity }),
      CELL_DELIVERY_TIMEOUT_MS,
    );
    return () => globalThis.clearTimeout(timer);
  }, [identity, waiting]);

  return deliveryTimedOut(waiting, identity, timeout);
};
