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
