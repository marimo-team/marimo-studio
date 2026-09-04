export class PreparedProjectionCapabilityError extends Error {
  readonly code: "prepared-functions-unsupported" | "prepared-stdin-unsupported";

  constructor(
    code: "prepared-functions-unsupported" | "prepared-stdin-unsupported",
    message: string,
  ) {
    super(message);
    this.name = "PreparedProjectionCapabilityError";
    this.code = code;
  }
}
