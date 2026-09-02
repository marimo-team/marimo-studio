interface ObservedDeferred<Value> {
  readonly promise: Promise<Value>;
  readonly resolve: (value: Value) => void;
  readonly reject: (cause: Error) => void;
}

export const createObservedDeferred = <Value>(): ObservedDeferred<Value> => {
  let resolve = (_value: Value) => {};
  let reject = (_cause: Error) => {};
  const promise = new Promise<Value>((complete, fail) => {
    resolve = complete;
    reject = fail;
  });
  void promise.catch(() => {});
  return { promise, reject, resolve };
};
