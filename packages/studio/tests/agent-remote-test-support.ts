export const deferred = <T>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
};

export interface JsonRequestInit extends RequestInit {
  readonly body: string;
}

export type JsonFetch = (url: string, init: JsonRequestInit) => Promise<Response>;
