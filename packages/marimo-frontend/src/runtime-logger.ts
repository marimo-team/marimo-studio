type LogMethod = (...data: unknown[]) => void;

interface RuntimeLogger {
  debug: LogMethod;
  log: LogMethod;
  warn: LogMethod;
  error: LogMethod;
  trace: LogMethod;
  get(namespace: string): RuntimeLogger;
  disabled(disabled?: boolean): RuntimeLogger;
}

const noop = () => {};

const DisabledLogger: RuntimeLogger = {
  debug: noop,
  log: noop,
  warn: noop,
  error: noop,
  trace: noop,
  get: () => DisabledLogger,
  disabled: () => DisabledLogger,
};

const isExpectedRuntimeClose = (data: unknown[]): boolean => {
  const [message, code, reason] = data;
  return message === "WebSocket closed" && code == null && reason == null;
};

const isExpectedRuntimeUnmount = (data: unknown[]): boolean =>
  data[0] === "useConnectionTransport is unmounting. This likely means there is a bug.";

const isExpectedOpaqueFrameLimitation = (data: unknown[]): boolean =>
  data[0] === "[iframe] localStorage unavailable - using fallback storage" ||
  data[0] === "[iframe] Fullscreen API unavailable" ||
  data[0] === "Not running in a secure context; interrupts are not available.";

const createLogger = (namespace?: string): RuntimeLogger => {
  const prefix = namespace ? [`[${namespace}]`] : [];
  const emit = (method: LogMethod, data: unknown[]) => method(...prefix, ...data);

  return {
    // Marimo's WebAssembly transport emits every worker message at debug level.
    // Keep diagnostics available through warnings and errors without flooding
    // the console during ordinary notebook execution.
    debug: noop,
    log: (...data) => emit(console.log, data),
    warn: (...data) => {
      if (
        isExpectedRuntimeUnmount(data) ||
        isExpectedRuntimeClose(data) ||
        isExpectedOpaqueFrameLimitation(data)
      ) {
        return;
      }
      emit(console.warn, data);
    },
    error: (...data) => emit(console.error, data),
    trace: (...data) => emit(console.trace, data),
    get: (child) => createLogger(namespace ? `${namespace}:${child}` : `marimo:${child}`),
    disabled: (disabled = true) => (disabled ? DisabledLogger : createLogger(namespace)),
  };
};

export const Logger = createLogger();
