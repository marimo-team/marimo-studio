export const E2E_PORT_OFFSET_ENV = "MARIMO_STUDIO_E2E_PORT_OFFSET";
const MAX_OFFSET = 65_535 - 4_336;
const WORKER_PORT_STRIDE = 100;

const readPortOffset = (source) => {
  if (!/^\d+$/.test(source)) {
    throw new TypeError(`${E2E_PORT_OFFSET_ENV} must be a non-negative integer`);
  }
  const value = Number(source);
  if (!Number.isSafeInteger(value) || value > MAX_OFFSET) {
    throw new RangeError(`${E2E_PORT_OFFSET_ENV} must be between 0 and ${MAX_OFFSET}`);
  }
  return value;
};

const endpoint = (basePort, portOffset) => {
  const port = basePort + portOffset;
  return Object.freeze({ origin: `http://127.0.0.1:${port}`, port });
};

export const createE2ENetwork = (source = "0") => {
  const portOffset = readPortOffset(source);
  return Object.freeze({
    portOffset,
    main: Object.freeze({
      studio: endpoint(4_321, portOffset),
      hosted: endpoint(4_322, portOffset),
      exported: endpoint(4_323, portOffset),
      recovery: endpoint(4_324, portOffset),
      collaboration: endpoint(4_325, portOffset),
      collaborationPeer: endpoint(4_326, portOffset),
      forcedInterruption: endpoint(4_327, portOffset),
      runInterruption: endpoint(4_328, portOffset),
      hostSession: endpoint(4_329, portOffset),
    }),
    provider: Object.freeze({
      live: endpoint(4_331, portOffset),
      gallery: endpoint(4_332, portOffset),
      story: endpoint(4_333, portOffset),
      external: endpoint(4_334, portOffset),
      web: endpoint(4_335, portOffset),
      reveal: endpoint(4_336, portOffset),
    }),
  });
};

export const workerPortOffset = (source = "0", workerIndex) => {
  const base = readPortOffset(source);
  if (workerIndex === undefined) return base;
  const index = readPortOffset(workerIndex);
  return readPortOffset(String(base + (index + 1) * WORKER_PORT_STRIDE));
};

export const e2eNetwork = createE2ENetwork(
  String(
    workerPortOffset(
      process.env[E2E_PORT_OFFSET_ENV],
      process.env.MARIMO_STUDIO_E2E_SUITE ? process.env.TEST_WORKER_INDEX : undefined,
    ),
  ),
);
