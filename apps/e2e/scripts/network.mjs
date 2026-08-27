const OFFSET_ENV = "MARIMO_STUDIO_E2E_PORT_OFFSET";
const MAX_OFFSET = 65_535 - 4_334;

const readPortOffset = (source) => {
  if (!/^\d+$/.test(source)) {
    throw new TypeError(`${OFFSET_ENV} must be a non-negative integer`);
  }
  const value = Number(source);
  if (!Number.isSafeInteger(value) || value > MAX_OFFSET) {
    throw new RangeError(`${OFFSET_ENV} must be between 0 and ${MAX_OFFSET}`);
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
    }),
    provider: Object.freeze({
      live: endpoint(4_331, portOffset),
      gallery: endpoint(4_332, portOffset),
      story: endpoint(4_333, portOffset),
      external: endpoint(4_334, portOffset),
    }),
  });
};

export const e2eNetwork = createE2ENetwork(process.env[OFFSET_ENV]);
