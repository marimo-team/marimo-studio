export const ownRecordValue = <Value>(
  record: Readonly<Record<string, Value>>,
  key: string,
): Value | undefined => (Object.hasOwn(record, key) ? record[key] : undefined);
