import { jsonValueSchema, type JsonValue } from "@marimo-studio/protocol/runtime-config";

export {
  jsonObjectSchema,
  jsonValueSchema,
  losslessRecordSchema,
  parseJson,
  parseJsonObject,
  parseJsonValue,
  type JsonObject,
  type JsonValue,
} from "@marimo-studio/protocol/json";

export const responseJson = async (response: Response): Promise<JsonValue> =>
  jsonValueSchema.parse(await response.json());

export const responseJsonOrNull = async (response: Response): Promise<JsonValue> => {
  try {
    return await responseJson(response);
  } catch {
    return null;
  }
};
