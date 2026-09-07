export class PreparedProjectionCapabilityError extends Error {
  readonly code: "prepared-stdin-unsupported";

  constructor(code: "prepared-stdin-unsupported", message: string) {
    super(message);
    this.name = "PreparedProjectionCapabilityError";
    this.code = code;
  }
}
