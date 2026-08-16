import { jsonValueSchema, type JsonValue } from "@marimo-studio/protocol/runtime-config";

export const responseJson = async (response: Response): Promise<JsonValue> =>
  jsonValueSchema.parse(await response.json());

export const responseJsonOrNull = async (response: Response): Promise<JsonValue> => {
  try {
    return await responseJson(response);
  } catch {
    return null;
  }
};

export const messageJson = (event: MessageEvent<unknown>): JsonValue | undefined => {
  const parsed = jsonValueSchema.safeParse(event.data);
  return parsed.success ? parsed.data : undefined;
};
