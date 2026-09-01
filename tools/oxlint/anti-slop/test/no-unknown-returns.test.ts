import { noUnknownReturnsRule } from "../rules/no-unknown-returns.ts";
import { ruleTester } from "./rule-tester.ts";

const error = { messageId: "unknownReturn" };

ruleTester.run("anti-slop/no-unknown-returns", noUnknownReturnsRule, {
  valid: [
    "type Promise<T> = { readonly value: T }; function load(): Promise<unknown> { return { value: input }; }",
    "import type { Promise } from './promise'; declare function load(): Promise<unknown>;",
    "type PromiseLike<T> = { readonly value: T }; declare function load(): PromiseLike<unknown>;",
    "type Result = unknown; function outer() { type Result = { readonly id: string }; function load(): Result { return { id: 'one' }; } }",
    "type Awaited<T> = { readonly value: T }; declare function load(): Awaited<unknown>;",
    "import type { Awaited } from './owner'; declare function load(): Awaited<unknown>;",
    "namespace Domain { export type Promise<T> = { readonly value: T }; } namespace Domain { export declare function load(): Promise<unknown>; }",
    "namespace Domain { type Result = unknown; } namespace Domain { export declare function load(): Result; }",
    "import type * as Domain from './owner'; declare function load(): Domain.Result;",
    "namespace Domain { export type Result = unknown; } function outer<Domain>() { declare function load(): Domain.Result; }",
    "export {}; namespace globalThis { export type Promise<Value> = { value: Value }; } declare function load(): globalThis.Promise<unknown>;",
    "namespace Outer { export namespace Inner { export type Result = string; } } declare function load(): Outer.Inner.Result;",
    "namespace Domain { export type Result = string; } import Result = Domain.Result; declare function load(): Result;",
    "namespace Contracts { export type Payload = string; } import C = Contracts; declare function load(): C.Payload;",
    "type Raw = unknown; type Factory<T> = T extends infer Raw ? () => Raw : () => string;",
  ],
  invalid: [
    {
      code: "declare function load(): Promise<unknown>;",
      errors: [error],
    },
    {
      code: "declare function load(): PromiseLike<unknown>;",
      errors: [error],
    },
    {
      code: "const load = async (): Promise<unknown> => input;",
      errors: [error],
    },
    {
      code: "type Promise<T> = T; declare function load(): Promise<unknown>;",
      errors: [error],
    },
    {
      code: "type Identity<T> = T; declare function load(): Identity<unknown>;",
      errors: [error],
    },
    {
      code: "type Identity<T> = T; declare function load(): Identity<Identity<unknown>>;",
      errors: [error],
    },
    {
      code: "function outer() { type Result = unknown; function load(): Result { return input; } }",
      errors: [error],
    },
    {
      code: "function outer() { function load(): Result { return input; } type Result = unknown; }",
      errors: [error],
    },
    {
      code: "namespace Domain { type Result = unknown; export function load(): Result { return input; } }",
      errors: [error],
    },
    {
      code: "declare module 'domain' { type Result = unknown; function load(): Result; }",
      errors: [error],
    },
    {
      code: "declare function load(): Awaited<unknown>;",
      errors: [error],
    },
    {
      code: "declare function load(): Awaited<Promise<unknown>>;",
      errors: [error],
    },
    {
      code: "namespace Domain { export type Result = unknown; } namespace Domain { export declare function load(): Result; }",
      errors: [error],
    },
    {
      code: "namespace Domain { type Promise<T> = { readonly value: T }; } namespace Domain { export declare function load(): Promise<unknown>; }",
      errors: [error],
    },
    {
      code: "namespace Domain { export type Result = unknown; } declare function load(): Domain.Result;",
      errors: [error],
    },
    {
      code: "namespace Domain { export type Identity<T> = T; } declare function load(): Domain.Identity<unknown>;",
      errors: [error],
    },
    {
      code: "declare function load(): globalThis.Promise<unknown>;",
      errors: [error],
    },
    {
      code: "namespace Outer { export namespace Inner { export type Result = unknown; } } declare function load(): Outer.Inner.Result;",
      errors: [error],
    },
    {
      code: "namespace Domain { export type Result = unknown; } import Result = Domain.Result; declare function load(): Result;",
      errors: [error],
    },
    {
      code: "namespace Contracts { export type Payload = unknown; } import C = Contracts; declare function load(): C.Payload;",
      errors: [error],
    },
    {
      code: "type Identity<Value = unknown> = Value; declare function load(): Identity;",
      errors: [error],
    },
    {
      code: "type Raw = unknown; type Factory<T> = T extends (string extends infer Raw ? true : false) ? () => Raw : () => string;",
      errors: [error],
    },
  ],
});
