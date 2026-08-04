import { useSyncExternalStore } from "react";

import { getCellHosts, subscribeCellHosts } from "../../cells/host";

export const useCellHosts = () =>
  useSyncExternalStore(subscribeCellHosts, getCellHosts, getCellHosts);
