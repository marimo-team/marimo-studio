import { noReflectGetRule } from "../rules/no-reflect-get.ts";
import { ruleTester } from "./rule-tester.ts";

const error = { messageId: "reflectGet" };

ruleTester.run("anti-slop/no-reflect-get", noReflectGetRule, {
  valid: [
    "const Reflect = { get() {} }; Reflect.get(target, 'value');",
    "import { Reflect } from './owner'; Reflect.get(target, 'value');",
    "const globalThis = { Reflect: { get() {} } }; globalThis.Reflect.get(target, 'value');",
    "let reflection = Reflect; reflection.get(target, 'value');",
    "const local = { get() {} }; const reflection = Reflect; reflection = local; reflection.get(target, 'value');",
    "let { get: read } = Reflect; read(target, 'value');",
    "const local = { get() {} }; local.get.call(local, target, 'value');",
    "const first = second; const second = first; first.get(target, 'value');",
    "const first = second; const second = first; first(target, 'value');",
  ],
  invalid: [
    { code: "Reflect.get(target, 'value');", errors: [error] },
    { code: "(Reflect?.get)(target, 'value');", errors: [error] },
    { code: "Reflect[`get`](target, 'value');", errors: [error] },
    { code: "Reflect['get'!](target, 'value');", errors: [error] },
    { code: "Reflect[<string>'get'](target, 'value');", errors: [error] },
    {
      code: "(Reflect as typeof Reflect).get(target, 'value');",
      errors: [error],
    },
    {
      code: "const first = Reflect; const reflection = first; reflection.get(target, 'value');",
      errors: [error],
    },
    {
      code: "const read = Reflect.get; read(target, 'value');",
      errors: [error],
    },
    { code: "globalThis.Reflect.get(target, 'value');", errors: [error] },
    {
      code: "const root = globalThis; root.Reflect.get(target, 'value');",
      errors: [error],
    },
    {
      code: "const { ['get']: read } = Reflect; read(target, 'value');",
      errors: [error],
    },
    { code: "Reflect.get.call(Reflect, target, 'value');", errors: [error] },
    { code: "Reflect.get.apply(Reflect, [target, 'value']);", errors: [error] },
    {
      code: "const { get: read } = Reflect; read.apply(Reflect, [target, 'value']);",
      errors: [error],
    },
    {
      code: "const read = Reflect.get.bind(Reflect); read(target, 'value');",
      errors: [error],
    },
    {
      code: "const method = Reflect.get; const read = method.bind(Reflect); read(target, 'value');",
      errors: [error],
    },
    { code: "Reflect.get.bind(Reflect)(target, 'value');", errors: [error] },
  ],
});
