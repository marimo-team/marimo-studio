export const appendUrlPath = (source: string, path: string, base: string): string => {
  const url = new URL(source, base);
  const prefix = url.pathname.endsWith("/") ? url.pathname : `${url.pathname}/`;
  url.pathname = `${prefix}${path.replace(/^\/+/, "")}`;
  return url.toString();
};
